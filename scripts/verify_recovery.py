"""Verify SQLite recovery into a new database without changing the source DB."""
import argparse
import json
from pathlib import Path
import sys
import tempfile
import time

from sqlalchemy import text
from sqlalchemy.engine import make_url

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.backup import backup_database, restore_database
from backend.config import Settings
from backend.database import make_engine
from backend.domain import utc_now


def main():
    parser = argparse.ArgumentParser(description="SQLite 백업·복원 실증 (원본 DB는 변경하지 않음)")
    parser.add_argument("--directory", type=Path, default=ROOT / "runtime" / "recovery-qa")
    args = parser.parse_args()
    settings = Settings.from_env()
    if make_url(settings.database_url).get_backend_name() != "sqlite":
        raise SystemExit("이 자동 실증은 SQLite 전용입니다. PostgreSQL 복원 절차는 docs/operations.md를 확인하세요.")
    args.directory.mkdir(parents=True, exist_ok=True)
    evidence = Path(tempfile.mkdtemp(prefix="run-", dir=args.directory)).resolve()
    snapshot, recovered = evidence / "snapshot.sqlite", evidence / "recovered.sqlite"
    started = time.perf_counter()
    manifest = backup_database(settings.database_url, snapshot)
    backup_seconds = time.perf_counter() - started
    started = time.perf_counter()
    result = restore_database(snapshot, "sqlite:///" + recovered.as_posix())
    restore_seconds = time.perf_counter() - started
    engine = make_engine("sqlite:///" + recovered.as_posix())
    try:
        with engine.connect() as connection:
            sessions = connection.scalar(text("SELECT COUNT(*) FROM login_sessions"))
            integrity = connection.scalar(text("PRAGMA integrity_check"))
    finally:
        engine.dispose()
    assert result["verified"] and sessions == 0 and integrity == "ok"
    report = {"verified_at": utc_now(), "dialect": "sqlite", "verified": True,
              "backup_bytes": snapshot.stat().st_size, "backup_seconds": round(backup_seconds, 4),
              "restore_seconds": round(restore_seconds, 4), "sha256": manifest["sha256"],
              "table_counts_before_session_revocation": result["table_counts"],
              "restored_session_count": sessions, "integrity_check": integrity,
              "source_database_modified": False}
    (evidence / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({**report, "evidence_directory": str(evidence)}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
