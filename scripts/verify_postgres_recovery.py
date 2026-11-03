"""PostgreSQL recovery drill for two explicitly supplied, empty test databases.

Run inside the application image so pg_dump/pg_restore match the production tools.
Never use an existing service database: both databases must initially be empty.
"""
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import secrets
import sys
import tempfile
import time

from sqlalchemy import inspect, select, text
from sqlalchemy.engine import make_url

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.backup import backup_database, restore_database
from backend.database import make_engine, session_factory
from backend.domain import utc_now
from backend.ingestion import import_directory
from backend.migrations import upgrade_schema
from backend.models import Contest, LoginSession, TrackerEntry, User
from backend.security import PASSWORDS, digest


def test_urls(environment):
    source, target = (make_url(environment[name]) for name in ('TEST_DATABASE_URL', 'TEST_RESTORE_DATABASE_URL'))
    if source.get_backend_name() != 'postgresql' or target.get_backend_name() != 'postgresql':
        raise ValueError('PostgreSQL 테스트 DB 두 개가 필요합니다.')
    if (source.host, source.port or 5432, source.database) == (target.host, target.port or 5432, target.database):
        raise ValueError('원본과 복원 대상 DB는 달라야 합니다.')
    return source, target


def require_empty_database(engine):
    with engine.connect() as connection:
        # Reject every user schema, not just the default search path.
        for schema in inspect(connection).get_schema_names():
            if schema != 'information_schema' and not schema.startswith('pg_'):
                if inspect(connection).get_table_names(schema=schema) or inspect(connection).get_view_names(schema=schema):
                    raise ValueError('실증에는 테이블과 뷰가 없는 별도 테스트 DB만 사용할 수 있습니다.')


def main():
    source_url, target_url = test_urls(os.environ)
    source_engine, target_engine = make_engine(source_url), make_engine(target_url)
    try:
        require_empty_database(source_engine)
        require_empty_database(target_engine)
        upgrade_schema(source_engine)
        source_factory = session_factory(source_engine)
        summary = import_directory(source_factory, ROOT / 'data')
        now, note = utc_now(), 'PostgreSQL recovery verification note'
        password_hash = PASSWORDS.hash(secrets.token_urlsafe(24))
        with source_factory() as db:
            contest_id = db.scalar(select(Contest.id).order_by(Contest.id).limit(1))
            user = User(username='recovery-verification', display_name='복원 검증 계정',
                        password_hash=password_hash, role='user', created_at=now)
            db.add(user)
            db.flush()
            user_id = user.id
            db.add(TrackerEntry(user_id=user_id, contest_id=contest_id, progress='preparing', note=note,
                                checklist=['eligibility'], version=3, saved_at=now, updated_at=now))
            db.add(LoginSession(user_id=user_id, token_hash=digest(secrets.token_urlsafe(32)),
                                csrf_hash=digest(secrets.token_urlsafe(32)),
                                expires_at=(datetime.now(timezone.utc) + timedelta(days=1)).isoformat()))
            db.commit()
        with tempfile.TemporaryDirectory(prefix='contestly-pg-recovery-') as temporary:
            snapshot = Path(temporary) / 'snapshot.dump'
            started = time.perf_counter()
            manifest = backup_database(source_url, snapshot)
            backup_seconds = time.perf_counter() - started
            started = time.perf_counter()
            result = restore_database(snapshot, target_url)
            restore_seconds = time.perf_counter() - started
            with session_factory(target_engine)() as db:
                entry = db.get(TrackerEntry, (user_id, contest_id))
                user = db.get(User, user_id)
                tracker_preserved = bool(entry and entry.note == note and entry.progress == 'preparing'
                                         and entry.checklist == ['eligibility'] and entry.version == 3)
                account_preserved = bool(user and user.password_hash == password_hash and user.role == 'user')
                session_count = db.scalar(text('SELECT COUNT(*) FROM login_sessions'))
            with source_engine.connect() as connection:
                source_sessions = connection.scalar(text('SELECT COUNT(*) FROM login_sessions'))
            if not (result['verified'] and tracker_preserved and account_preserved and session_count == 0 and source_sessions == 1):
                raise AssertionError('복원 데이터·계정·세션 폐기 검증에 실패했습니다.')
            report = {'verified_at': utc_now(), 'dialect': 'postgresql', 'verified': True,
                      'catalogue_count': summary['count'], 'backup_bytes': snapshot.stat().st_size,
                      'backup_seconds': round(backup_seconds, 4), 'restore_seconds': round(restore_seconds, 4),
                      'sha256': manifest['sha256'], 'table_counts_before_session_revocation': result['table_counts'],
                      'account_preserved': account_preserved, 'tracker_preserved': tracker_preserved,
                      'restored_session_count': session_count, 'source_session_count': source_sessions}
            print(json.dumps(report, ensure_ascii=False, indent=2))
    finally:
        source_engine.dispose()
        target_engine.dispose()


if __name__ == '__main__':
    main()
