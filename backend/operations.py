from datetime import datetime, timedelta, timezone
import os
import subprocess
import sys
from uuid import uuid4

from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError

from .config import ROOT
from .domain import utc_now
from .ingestion import ingest_snapshot, read_snapshot
from .models import CollectionRun, OperationLock


def reserve_collection(factory, sources, max_pages, trigger="manual"):
    run_id, now = str(uuid4()), utc_now()
    with factory() as db:
        expired = db.get(OperationLock, "collection")
        if expired and expired.expires_at > now:
            return None
        if expired and expired.expires_at <= now:
            old = db.get(CollectionRun, expired.owner)
            if old and old.status == "running":
                old.status, old.error, old.finished_at = "failed", "수집 작업의 실행 제한 시간이 만료되었습니다.", now
        db.execute(delete(OperationLock).where(OperationLock.name == "collection", OperationLock.expires_at <= now))
        db.add(OperationLock(name="collection", owner=run_id,
                            expires_at=(datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(timespec="seconds")))
        db.add(CollectionRun(id=run_id, trigger=trigger, status="running", requested_sources=sources,
                            started_at=now, summary={"max_pages": max_pages}))
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            return None
    return run_id


def execute_collection(factory, data_dir, run_id, sources, max_pages):
    try:
        completed = subprocess.run(
            [sys.executable, "-u", str(ROOT / "scripts" / "scrape.py"), "--data-dir", str(data_dir),
             "--max-pages", str(max_pages), "--sources", *sources],
            cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=1200,
            env={**os.environ, "PYTHONIOENCODING": "utf-8"},
        )
        if completed.returncode:
            raise RuntimeError((completed.stderr or completed.stdout)[-1800:])
        contests, raw, metadata = read_snapshot(data_dir)
        with factory() as db:
            ingest_snapshot(db, contests, raw, metadata, run_id=run_id)
        return True
    except Exception as error:
        with factory() as db:
            run = db.get(CollectionRun, run_id)
            if run:
                run.status, run.error, run.finished_at = "failed", str(error)[-1800:], utc_now()
                db.commit()
        return False
    finally:
        with factory() as db:
            db.execute(delete(OperationLock).where(OperationLock.name == "collection", OperationLock.owner == run_id))
            db.commit()
