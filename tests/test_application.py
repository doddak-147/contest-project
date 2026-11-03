from datetime import date, timedelta
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy import func, select, text

from backend.backup import backup_database, restore_database
from backend.config import Settings
from backend.database import make_engine
from backend.domain import today_kst, utc_now
from backend.ingestion import ingest_snapshot
from backend.main import create_app
from backend.models import (AuditLog, CollectionRun, Contest, ContestChange, DataConflict, LoginSession,
                            OperationLock, TrackerEntry, User)
from backend.operations import execute_collection, reserve_collection
from backend.security import PASSWORDS

PASSWORD = "contestly-test-password-2026"


def sample(contest_id="main", *, title="우리동네 아이디어 공모전", start=-10, end=7, source="씽굿", category="IT"):
    today = date.fromisoformat(today_kst())
    return {"id": contest_id, "title": title, "organization": "우리동네재단",
            "start_date": (today + timedelta(days=start)).isoformat(),
            "deadline": (today + timedelta(days=end)).isoformat(), "category": category,
            "category_group": "IT" if category == "IT" else "ETC", "eligibility": "대학생, 일반인",
            "award": "100만원", "award_detail": "", "apply_method": "온라인", "source": source,
            "link": "https://example.com/" + contest_id,
            "sources": [{"id": contest_id, "name": source, "url": "https://example.com/" + contest_id}],
            "aliases": [contest_id, contest_id + "-old"]}


class ApplicationTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.settings = Settings(database_url="sqlite:///" + (self.root / "application.db").as_posix(),
                                 seed_snapshot=False, data_dir=self.root / "data")
        self.app = create_app(self.settings)
        self.client = TestClient(self.app)
        self.client.__enter__()
        self.addCleanup(self.client.__exit__, None, None, None)
        self.factory = self.app.state.db_factory
        self.rows = [sample(), sample("future", title="접수 예정 공모전", start=1, end=30, category="디자인"),
                     sample("closed", title="마감된 공모전", end=-1, category="디자인"),
                     sample("conflict-a", title="마감일 충돌 공모전", end=10, category="문학"),
                     sample("conflict-b", title="마감일 충돌 공모전", end=11, source="위비티", category="문학")]
        with self.factory() as db:
            ingest_snapshot(db, self.rows)

    def register(self, username="user-one", client=None):
        client = client or self.client
        response = client.post("/api/auth/register", json={"username": username, "password": PASSWORD, "display_name": username})
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()

    def csrf(self, client=None):
        return {"X-CSRF-Token": (client or self.client).cookies.get("contestly_csrf")}

    def admin_login(self):
        with self.factory() as db:
            user = User(username="operator", display_name="운영자", password_hash=PASSWORDS.hash(PASSWORD),
                        role="admin", created_at=utc_now())
            db.add(user)
            db.commit()
        response = self.client.post("/api/auth/login", json={"username": "operator", "password": PASSWORD})
        self.assertEqual(response.status_code, 200, response.text)

    def test_migrations_health_and_private_files(self):
        self.assertEqual(self.client.get("/api/health").json()["database"], "ok")
        with self.factory() as db:
            self.assertEqual(db.scalar(text("SELECT version_num FROM alembic_version")), "0001_initial")
        for path in ("/.env", "/runtime/contestly.db", "/backend/config.py", "/data/sources/wevity.json"):
            self.assertEqual(self.client.get(path).status_code, 404)

    def test_states_counts_and_server_pagination(self):
        result = self.client.get("/api/contests?page_size=2&page=999").json()
        self.assertEqual((result["total"], result["page"], result["pages"], len(result["items"])), (4, 2, 2, 2))
        self.assertEqual(result["stats"], {"open": 3, "it": 1, "urgent": 1, "upcoming": 1})
        self.assertEqual(self.client.get("/api/contests?status=upcoming").json()["items"][0]["status_code"], "upcoming")
        self.assertEqual(self.client.get("/api/contests?status=closed").json()["total"], 1)
        self.assertEqual(self.client.get("/api/contests?mode=urgent").json()["total"], 1)
        self.assertEqual(self.client.get("/api/contests?source=위비티").json()["total"], 1)

    def test_search_validation_literal_wildcards_and_alias_lookup(self):
        self.assertEqual(self.client.get("/api/contests", params={"q": "' OR 1=1 --"}).json()["total"], 0)
        self.assertEqual(self.client.get("/api/contests", params={"q": "%"}).json()["total"], 0)
        self.assertEqual(self.client.get("/api/contests?page_size=999").status_code, 422)
        lookup = self.client.post("/api/contests/lookup", json={"ids": ["closed-old", "missing"]}).json()
        self.assertEqual([item["id"] for item in lookup["items"]], ["closed"])

    def test_registration_cookie_hash_and_no_role_escalation(self):
        session = self.register()
        self.assertEqual(session["user"]["role"], "user")
        with self.factory() as db:
            user = db.get(User, session["user"]["id"])
            self.assertNotIn(PASSWORD, user.password_hash)
            self.assertTrue(PASSWORDS.verify(PASSWORD, user.password_hash))
        self.assertEqual(self.client.post("/api/auth/register", json={"username": "user-two", "password": PASSWORD,
                         "display_name": "두번째", "role": "admin"}).status_code, 422)
        self.assertEqual(self.client.post("/api/auth/register", json={"username": "USER-ONE", "password": PASSWORD,
                         "display_name": "중복"}).status_code, 409)
        self.assertEqual(self.client.get("/api/admin/overview").status_code, 403)

    def test_csrf_cross_origin_and_unauthenticated_writes_rejected(self):
        self.assertEqual(self.client.put("/api/tracker/main", json={}).status_code, 401)
        self.register()
        self.assertEqual(self.client.put("/api/tracker/main", json={}).status_code, 403)
        self.assertEqual(self.client.put("/api/tracker/main", headers={**self.csrf(), "Origin": "https://other.example"}, json={}).status_code, 403)
        self.assertEqual(self.client.put("/api/tracker/main", headers=self.csrf(), json={}).status_code, 200)

    def test_two_accounts_cannot_read_or_overwrite_each_others_notes(self):
        first = self.register()
        self.client.put("/api/tracker/main", headers=self.csrf(), json={"note": "첫 사용자 비공개 메모"})
        with TestClient(self.app) as other:
            second = self.register("user-two", other)
            self.assertNotEqual(first["user"]["id"], second["user"]["id"])
            self.assertEqual(other.get("/api/tracker").json()["entries"], [])
            self.assertEqual(other.put("/api/tracker/main", headers=self.csrf(other), json={"note": "두번째 사용자"}).status_code, 200)
            self.assertEqual(other.put("/api/tracker/main", headers=self.csrf(other), json={"user_id": first["user"]["id"]}).status_code, 422)
        self.assertEqual(self.client.get("/api/tracker").json()["entries"][0]["note"], "첫 사용자 비공개 메모")

    def test_optimistic_version_conflicts_and_revoked_logout_session(self):
        self.register()
        created = self.client.put("/api/tracker/main", headers=self.csrf(), json={"note": "처음"}).json()
        self.assertEqual(created["version"], 1)
        self.assertEqual(self.client.put("/api/tracker/main", headers=self.csrf(), json={"note": "새 기록", "version": 1}).status_code, 200)
        self.assertEqual(self.client.put("/api/tracker/main", headers=self.csrf(), json={"note": "이전 기기의 기록", "version": 1}).status_code, 409)
        self.assertEqual(self.client.delete("/api/tracker/main?version=1", headers=self.csrf()).status_code, 409)
        self.assertEqual(self.client.get("/api/tracker").json()["entries"][0]["note"], "새 기록")
        old_token = self.client.cookies.get("contestly_session")
        self.assertEqual(self.client.post("/api/auth/logout", headers=self.csrf()).status_code, 200)
        self.assertEqual(self.client.get("/api/auth/me", headers={"Cookie": f"contestly_session={old_token}"}).status_code, 401)

    def test_closed_or_missing_contests_keep_saved_records_and_change_history(self):
        self.register()
        self.client.put("/api/tracker/main", headers=self.csrf(), json={"note": "마감 뒤에도 보존"})
        revised = [sample(end=-1), self.rows[1]]
        with self.factory() as db:
            ingest_snapshot(db, revised)
        entries = self.client.get("/api/tracker").json()["entries"]
        self.assertEqual(entries[0]["contest"]["status_code"], "closed")
        self.assertEqual(entries[0]["note"], "마감 뒤에도 보존")
        self.assertEqual(self.client.get("/api/contests?mode=saved&status=all").json()["total"], 1)
        history = self.client.get("/api/contests/main/history").json()["items"]
        self.assertIn("deadline", history[0]["changes"])
        with self.factory() as db:
            self.assertEqual(db.scalar(select(func.count()).select_from(Contest)), 5)

    def test_import_is_idempotent_and_invalid_snapshot_does_not_partially_write(self):
        with self.factory() as db:
            before = db.scalar(select(func.count()).select_from(ContestChange))
            self.assertTrue(ingest_snapshot(db, self.rows)["unchanged"])
            self.assertEqual(db.scalar(select(func.count()).select_from(ContestChange)), before)
            invalid = [sample(title="잘못 덮어쓴 제목"), {**sample("bad"), "deadline": "not-a-date"}]
            with self.assertRaises(ValueError):
                ingest_snapshot(db, invalid)
            self.assertEqual(db.get(Contest, "main").title, self.rows[0]["title"])

    def test_guest_import_merges_once_without_losing_account_notes(self):
        self.register()
        self.client.put("/api/tracker/main", headers=self.csrf(),
                        json={"note": "계정 메모", "progress": "researching"})
        body = {"entries": [{"contest_id": "main-old", "note": "기기 메모", "progress": "preparing"},
                            {"contest_id": "unknown", "note": "없는 공고"}]}
        result = self.client.post("/api/tracker/import", headers=self.csrf(), json=body)
        self.assertEqual(result.json(), {"imported": 1, "skipped": 1})
        first = self.client.get("/api/tracker").json()["entries"][0]
        self.assertEqual(first["note"], "계정 메모\n\n기기 메모")
        self.assertEqual(first["progress"], "preparing")
        self.assertEqual(first["version"], 2)
        self.assertEqual(self.client.post("/api/tracker/import", headers=self.csrf(), json=body).status_code, 200)
        again = self.client.get("/api/tracker").json()["entries"][0]
        self.assertEqual(again, first)

    def test_source_collection_time_does_not_become_import_time(self):
        collected_at = "2026-01-02T09:00:00+09:00"
        with self.factory() as db:
            ingest_snapshot(db, self.rows, metadata={"updated_at": collected_at})
        self.assertEqual(self.client.get("/api/collection-status").json()["updated_at"], collected_at)

    def test_admin_conflict_review_role_changes_and_audit(self):
        user = self.register()
        self.admin_login()
        overview = self.client.get("/api/admin/overview").json()
        self.assertEqual(overview["open_conflicts"], 1)
        conflict = self.client.get("/api/admin/conflicts").json()["items"][0]
        self.assertEqual(self.client.patch(f"/api/admin/conflicts/{conflict['id']}", headers=self.csrf(),
                         json={"status": "ignored", "note": "원문을 확인했고 별도 공고로 판단"}).status_code, 200)
        self.assertEqual(self.client.patch(f"/api/admin/users/{user['user']['id']}/role", headers=self.csrf(), json={"role": "admin"}).status_code, 200)
        audit = self.client.get("/api/admin/audit").json()["items"]
        self.assertEqual({row["action"] for row in audit}, {"conflict.review", "user.role"})

    def test_collection_is_authorized_and_concurrent_runs_are_rejected(self):
        self.register()
        self.assertEqual(self.client.post("/api/admin/collect", headers=self.csrf(), json={}).status_code, 403)
        self.admin_login()
        with patch("backend.operations.execute_collection") as worker:
            response = self.client.post("/api/admin/collect", headers=self.csrf(), json={"sources": ["wevity"], "max_pages": 1})
            self.assertEqual(response.status_code, 202, response.text)
            worker.assert_called_once()
            self.assertEqual(self.client.post("/api/admin/collect", headers=self.csrf(), json={}).status_code, 409)

    def test_failed_collection_records_failure_and_releases_lock(self):
        run = reserve_collection(self.factory, ["wevity"], 1)
        with patch("backend.operations.subprocess.run", return_value=subprocess.CompletedProcess([], 1, "", "upstream failed")):
            self.assertFalse(execute_collection(self.factory, self.settings.data_dir, run, ["wevity"], 1))
        with self.factory() as db:
            self.assertEqual(db.get(CollectionRun, run).status, "failed")
            self.assertIsNone(db.get(OperationLock, "collection"))
            self.assertEqual(db.scalar(select(func.count()).select_from(Contest)), 5)

    def test_backup_restore_verifies_counts_and_revokes_sessions(self):
        self.register()
        target = self.root / "backup.sqlite"
        manifest = backup_database(self.settings.database_url, target)
        self.assertEqual(manifest["table_counts"]["contests"], 5)
        original = target.read_bytes()
        with self.assertRaises(ValueError):
            backup_database(self.settings.database_url, target)
        self.assertEqual(target.read_bytes(), original)
        recovered_url = "sqlite:///" + (self.root / "recovered.sqlite").as_posix()
        result = restore_database(target, recovered_url)
        self.assertTrue(result["verified"])
        engine = make_engine(recovered_url)
        with engine.connect() as connection:
            self.assertEqual(connection.scalar(text("SELECT COUNT(*) FROM login_sessions")), 0)
            self.assertEqual(connection.scalar(text("SELECT COUNT(*) FROM contests")), 5)
        engine.dispose()
        with self.assertRaises(ValueError):
            restore_database(target, recovered_url)
        with target.open("ab") as file:
            file.write(b"tampered")
        with self.assertRaises(ValueError):
            restore_database(target, "sqlite:///" + (self.root / "tampered.sqlite").as_posix())

    def test_failed_backup_does_not_publish_partial_files(self):
        target = self.root / "partial.sqlite"

        def failed_backup(database_url, destination):
            destination.write_bytes(b"partial")
            raise RuntimeError("simulated disk failure")

        with patch("backend.backup.create_backup", side_effect=failed_backup):
            with self.assertRaises(RuntimeError):
                backup_database(self.settings.database_url, target)
        self.assertFalse(target.exists())
        self.assertFalse(target.with_suffix(".sqlite.json").exists())
        self.assertFalse(list(self.root.glob(".contestly-backup-*")))


if __name__ == "__main__":
    unittest.main()
