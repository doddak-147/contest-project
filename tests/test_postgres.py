import os
import unittest
from uuid import uuid4

from fastapi.testclient import TestClient

from backend.config import Settings
from backend.main import create_app
from backend.ingestion import ingest_snapshot
from test_application import sample


@unittest.skipUnless(os.getenv("TEST_DATABASE_URL"), "별도 PostgreSQL 테스트 DB가 지정되지 않았습니다.")
class PostgreSQLTests(unittest.TestCase):
    def test_migrations_import_search_and_authenticated_tracker_on_postgres(self):
        app = create_app(Settings(database_url=os.environ["TEST_DATABASE_URL"], seed_snapshot=False))
        contest_id = "pg-" + uuid4().hex
        with TestClient(app) as client:
            with app.state.db_factory() as db:
                ingest_snapshot(db, [sample(contest_id, title=contest_id)])
            self.assertEqual(client.get("/api/contests", params={"q": contest_id}).json()["total"], 1)
            session = client.post("/api/auth/register", json={"username": "pg-" + uuid4().hex[:20],
                                  "display_name": "PG 검증", "password": "postgres-test-password-2026"})
            self.assertEqual(session.status_code, 201, session.text)
            result = client.put(f"/api/tracker/{contest_id}", headers={"X-CSRF-Token": session.json()["csrf_token"]},
                                json={"note": "PostgreSQL 사용자별 기록 검증"})
            self.assertEqual(result.status_code, 200, result.text)
            self.assertEqual(client.get("/api/tracker").json()["entries"][0]["contest"]["id"], contest_id)
