"""Consistent backups; restores require an empty destination and verify the result."""
import hashlib
from contextlib import closing
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import tempfile

from sqlalchemy import inspect, text
from sqlalchemy.engine import make_url

from .database import make_engine
from .domain import utc_now


def checksum(path):
    with Path(path).open("rb") as file:
        return hashlib.file_digest(file, "sha256").hexdigest()


def counts(connection):
    # Table identifiers come from the database inspector, never request input.
    return {table: connection.scalar(text(f'SELECT COUNT(*) FROM "{table}"'))
            for table in inspect(connection).get_table_names()}


def pg_environment(url):
    return {**os.environ, "PGHOST": url.host or "localhost", "PGPORT": str(url.port or 5432),
            "PGUSER": url.username or "", "PGPASSWORD": url.password or "", "PGDATABASE": url.database or ""}


def backup_database(database_url, destination):
    destination = Path(destination).resolve()
    manifest = destination.with_suffix(destination.suffix + ".json")
    if destination.exists() or manifest.exists():
        raise ValueError("백업 대상 파일이 이미 있습니다. 새 파일명을 사용하세요.")
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".contestly-backup-", dir=destination.parent) as temporary:
        working = Path(temporary) / "snapshot"
        metadata = create_backup(database_url, working)
        working_manifest = Path(temporary) / "manifest.json"
        working_manifest.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
        # Exclusive creation prevents a racing backup from overwriting an existing file.
        # The manifest is published only after a complete, verified snapshot exists.
        os.link(working, destination)
        os.link(working_manifest, manifest)
    return metadata


def create_backup(database_url, destination):
    url = make_url(database_url)
    dialect = url.get_backend_name()
    if dialect == "sqlite":
        source_path = Path(url.database).resolve()
        if not source_path.is_file():
            raise ValueError("원본 DB 파일을 찾을 수 없습니다.")
        with closing(sqlite3.connect(source_path.as_uri() + "?mode=ro", uri=True)) as source:
            with closing(sqlite3.connect(destination)) as target:
                source.backup(target)
                if target.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                    raise ValueError("백업 무결성 검사에 실패했습니다.")
        engine = make_engine(f"sqlite:///{destination.as_posix()}")
        try:
            with engine.connect() as connection:
                table_counts = counts(connection)
        finally:
            engine.dispose()
    elif dialect == "postgresql":
        engine = make_engine(database_url)
        try:
            with engine.connect().execution_options(isolation_level="REPEATABLE READ") as connection:
                with connection.begin():
                    snapshot = connection.scalar(text("SELECT pg_export_snapshot()"))
                    table_counts = counts(connection)
                    subprocess.run(["pg_dump", "--format=custom", "--no-owner", "--no-privileges",
                                    f"--snapshot={snapshot}", f"--file={destination}"],
                                   env=pg_environment(url), check=True, timeout=600, capture_output=True)
        finally:
            engine.dispose()
    else:
        raise ValueError("SQLite와 PostgreSQL 백업만 지원합니다.")
    return {"created_at": utc_now(), "dialect": dialect, "sha256": checksum(destination), "table_counts": table_counts}


def restore_database(source, target_url):
    source = Path(source).resolve()
    manifest = json.loads(source.with_suffix(source.suffix + ".json").read_text(encoding="utf-8"))
    if checksum(source) != manifest["sha256"]:
        raise ValueError("백업 파일의 체크섬이 일치하지 않습니다.")
    url = make_url(target_url)
    dialect = url.get_backend_name()
    if dialect != manifest["dialect"]:
        raise ValueError("백업과 복원 대상 DB 종류가 다릅니다.")
    if dialect == "sqlite":
        destination = Path(url.database).resolve()
        if destination.exists():
            raise ValueError("기존 DB에는 덮어쓸 수 없습니다. 새 경로로 복원하세요.")
        destination.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(source.as_uri() + "?mode=ro", uri=True)) as saved:
            if saved.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise ValueError("백업 DB가 손상되었습니다.")
            # Reserve the new path atomically rather than relying on an existence check.
            descriptor = os.open(destination, os.O_CREAT | os.O_EXCL | os.O_RDWR, 0o600)
            os.close(descriptor)
            with closing(sqlite3.connect(destination)) as target:
                saved.backup(target)
    elif dialect == "postgresql":
        engine = make_engine(target_url)
        try:
            with engine.connect() as connection:
                if inspect(connection).get_table_names():
                    raise ValueError("비어 있는 별도 데이터베이스로만 복원할 수 있습니다.")
        finally:
            engine.dispose()
        subprocess.run(["pg_restore", "--single-transaction", "--no-owner", "--no-privileges",
                        f"--dbname={url.database}", str(source)],
                       env=pg_environment(url), check=True, timeout=600, capture_output=True)
    else:
        raise ValueError("지원하지 않는 DB 종류입니다.")
    engine = make_engine(target_url)
    try:
        with engine.begin() as connection:
            restored_counts = counts(connection)
            if restored_counts != manifest["table_counts"]:
                raise ValueError("복원 후 테이블별 건수가 백업과 다릅니다.")
            # Existing browser sessions must not become valid again following a restore.
            connection.execute(text("DELETE FROM login_sessions"))
    finally:
        engine.dispose()
    return {"verified": True, "table_counts": restored_counts, "sessions_revoked": True}
