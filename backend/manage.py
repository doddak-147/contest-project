import argparse
from datetime import datetime
import getpass
import json
import os
from pathlib import Path
import time

from sqlalchemy import select

from .backup import backup_database, restore_database
from .config import Settings
from .database import make_engine, session_factory
from .domain import KST, utc_now
from .ingestion import import_directory
from .migrations import upgrade_schema
from .models import CollectionRun, User
from .operations import execute_collection, reserve_collection
from .security import PASSWORDS


def main():
    parser = argparse.ArgumentParser(description="Contestly 운영 명령")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("init-db")
    commands.add_parser("import-data")
    admin = commands.add_parser("create-admin")
    admin.add_argument("--username", required=True)
    admin.add_argument("--display-name", default="운영자")
    collect = commands.add_parser("collect")
    collect.add_argument("--sources", nargs="+", choices=["thinkcontest", "wevity", "contestkorea"], default=["thinkcontest", "wevity", "contestkorea"])
    collect.add_argument("--max-pages", type=int, choices=range(1, 21), default=5)
    commands.add_parser("schedule")
    scheduled_backup = commands.add_parser("backup-schedule")
    scheduled_backup.add_argument("--directory", type=Path, default=Path("backups"))
    backup = commands.add_parser("backup")
    backup.add_argument("--output", type=Path, required=True)
    restore = commands.add_parser("restore")
    restore.add_argument("--input", type=Path, required=True)
    restore.add_argument("--target", required=True, help="비어 있는 별도 DB의 URL")
    args = parser.parse_args()
    settings = Settings.from_env()
    if args.command == "backup":
        print(json.dumps(backup_database(settings.database_url, args.output), ensure_ascii=False, indent=2))
        return
    if args.command == "restore":
        print(json.dumps(restore_database(args.input, args.target), ensure_ascii=False, indent=2))
        return
    engine = make_engine(settings.database_url)
    factory = session_factory(engine)
    if args.command == "init-db":
        upgrade_schema(engine)
        print("DB 스키마 마이그레이션 완료")
    elif args.command == "import-data":
        print(json.dumps(import_directory(factory, settings.data_dir), ensure_ascii=False, indent=2))
    elif args.command == "create-admin":
        from .schemas import Register
        password = os.getenv("CONTESTLY_ADMIN_PASSWORD") or getpass.getpass("관리자 비밀번호 (12자 이상): ")
        validated = Register(username=args.username, password=password, display_name=args.display_name)
        with factory() as db:
            if db.scalar(select(User).where(User.username == validated.username.lower())):
                raise SystemExit("이미 있는 계정입니다. 관리자 권한 변경은 기존 관리자에게 요청하세요.")
            db.add(User(username=validated.username.lower(), display_name=validated.display_name,
                        password_hash=PASSWORDS.hash(password), role="admin", created_at=utc_now()))
            db.commit()
        print("관리자 계정 생성 완료")
    elif args.command == "collect":
        run_id = reserve_collection(factory, args.sources, args.max_pages, "cli")
        if not run_id:
            raise SystemExit("다른 수집 작업이 실행 중입니다.")
        if not execute_collection(factory, settings.data_dir, run_id, args.sources, args.max_pages):
            raise SystemExit("수집 실패. 관리자 화면에서 실행 기록을 확인하세요.")
        print(f"수집 및 DB 반영 완료: {run_id}")
    elif args.command == "schedule":
        while True:
            now = datetime.now(KST)
            day = now.date().isoformat()
            with factory() as db:
                runs = db.scalars(select(CollectionRun).where(CollectionRun.trigger == "scheduled").order_by(CollectionRun.started_at.desc()).limit(10)).all()
                attempted_today = any(datetime.fromisoformat(run.started_at).astimezone(KST).date().isoformat() == day for run in runs)
            if now.hour >= 9 and not attempted_today:
                sources = ["thinkcontest", "wevity", "contestkorea"]
                run_id = reserve_collection(factory, sources, 5, "scheduled")
                if run_id:
                    execute_collection(factory, settings.data_dir, run_id, sources, 5)
            time.sleep(30)
    elif args.command == "backup-schedule":
        while True:
            day = datetime.now(KST).strftime("%Y%m%d")
            suffix = ".sqlite" if settings.database_url.startswith("sqlite") else ".dump"
            completed = args.directory.exists() and any(args.directory.glob(f"contestly-{day}*{suffix}.json"))
            destination = args.directory / f"contestly-{day}-{datetime.now(KST).strftime('%H%M%S')}{suffix}"
            if not completed:
                try:
                    backup_database(settings.database_url, destination)
                    print(f"일일 백업 완료: {destination}", flush=True)
                except Exception as error:
                    print(f"일일 백업 실패: {type(error).__name__}", flush=True)
            time.sleep(30)
    engine.dispose()


if __name__ == "__main__":
    main()
