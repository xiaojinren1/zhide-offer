"""经历库更新：真实接口、临时数据库，不调用模型。"""
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from fastapi.testclient import TestClient
from core import accounts
from main import app

HEADERS = {"X-Requested-With": "XMLHttpRequest"}

class ProfileUpdates(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        override = patch.object(accounts, "DATABASE_PATH", Path(folder.name) / "accounts.sqlite3")
        override.start(); self.addCleanup(override.stop)
        emitter = patch("api.profiles.events.emit")
        emitter.start(); self.addCleanup(emitter.stop)
        self.client = TestClient(app, headers=HEADERS)
        self.addCleanup(self.client.close)
        self.client.post("/api/auth/register", json={"username": "profile_a", "password": "demo-only-12345"})
        self.profile = {"name": "虚构同学", "experiences": [{"name": "项目", "kind": "project", "role": "成员", "period": "", "actions": ["整理需求"], "results": [], "skills": [], "source_text": "原文"}], "skills": [], "education": [], "user_confirmed": True}
        saved = self.client.post("/api/profiles/save", json={"name": "样例", "profile": self.profile}).json()
        self.url = "/api/profiles/" + saved["id"]
        self.meta = self.client.get(self.url).json()["meta"]

    def update(self, **changes):
        return self.client.patch(self.url, json={"name": "新名称", "expected_revision": self.meta["revision"], **changes})

    def test_rename_keeps_content_and_id(self):
        result = self.update()
        self.assertEqual(result.status_code, 200, result.text)
        self.assertEqual(result.json()["profile"], self.profile)
        self.assertEqual(result.json()["meta"]["id"], self.meta["id"])
        self.assertEqual(len(self.client.get("/api/profiles/list").json()["profiles"]), 1)
        self.assertNotEqual(result.json()["meta"]["revision"], self.meta["revision"])

    def test_update_keeps_traceability_and_prevents_stale_overwrite(self):
        self.profile["experiences"][0]["actions"] = ["更新事实"]
        result = self.update(profile=self.profile)
        self.assertEqual(result.status_code, 200, result.text)
        self.assertEqual(result.json()["profile"]["experiences"][0]["source_text"], "原文")
        self.assertEqual(self.update().status_code, 409)
        self.assertEqual(self.client.get(self.url).json()["profile"]["experiences"][0]["actions"], ["更新事实"])

    def test_account_isolation_and_csrf(self):
        other = TestClient(app, headers=HEADERS)
        self.addCleanup(other.close)
        other.post("/api/auth/register", json={"username": "profile_b", "password": "demo-only-12345"})
        payload = {"name": "越权", "expected_revision": self.meta["revision"]}
        self.assertEqual(other.patch(self.url, json=payload).status_code, 404)
        self.client.headers.pop("X-Requested-With")
        self.assertEqual(self.update().status_code, 403)
        anonymous = TestClient(app, headers=HEADERS)
        self.addCleanup(anonymous.close)
        self.assertEqual(anonymous.patch(self.url, json=payload).status_code, 401)

    def test_rejects_invalid_updates_without_changing_record(self):
        for payload in ({"name": "  "}, {"profile": {}}, {"profile": {**self.profile, "experiences": []}}, {"expected_revision": "x"}):
            self.assertEqual(self.update(**payload).status_code, 422)
        self.assertEqual(self.client.get(self.url).json()["meta"], self.meta)

if __name__ == "__main__":
    unittest.main()
