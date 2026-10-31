"""持久化接口合约：临时数据库、合成材料，不连接外部模型。"""
from __future__ import annotations

import copy
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from fastapi.testclient import TestClient
from api import interview_records, workspace
from core import accounts
from main import app

HEADER = {"X-Requested-With": "XMLHttpRequest"}
STATE = {
    "source_text": "合成经历原始文本", "source_name": "演示.docx", "jd_text": "产品岗位",
    "profile": {
        "name": "演示同学", "experiences": [{"kind": "project", "name": "校园项目", "role": "成员",
            "period": "2025", "actions": ["整理需求"], "results": ["需求文档"], "skills": ["需求分析"],
            "start": [2025, 1], "end": None, "source_text": "校园项目", "quantified": []}],
        "skills": ["需求分析"], "education": ["某大学"], "raw_text": "合成材料", "user_confirmed": True,
    },
    "jd_keywords": ["需求"], "markdown": "# 演示简历", "page": "workbench",
}


class PersistenceContract(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory(prefix="zhide-persistence-test-")
        self.addCleanup(folder.cleanup)
        db_patch = patch.object(accounts, "DATABASE_PATH", Path(folder.name) / "accounts.sqlite3")
        db_patch.start()
        self.addCleanup(db_patch.stop)
        # 使用真实服务端 Cookie 认证，避免 Mock 掩盖数据归属与请求头检查。
        self.a = TestClient(app, headers=HEADER)
        self.b = TestClient(app, headers=HEADER)
        self.addCleanup(self.a.close)
        self.addCleanup(self.b.close)
        self.uid_a = self.register(self.a, "persist_a")
        self.uid_b = self.register(self.b, "persist_b")

    def register(self, client, username):
        response = client.post("/api/auth/register", json={"username": username, "password": "demo-password-123"})
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()["user"]["id"]

    def save(self, revision=0, state=None, client=None, user_id=None):
        return (client or self.a).post("/api/workspace", json={
            "expected_user_id": user_id or self.uid_a, "revision": revision,
            "state": STATE if state is None else state,
        })

    def record(self, client=None, user_id=None, **changes):
        value = {"expected_user_id": user_id or self.uid_a, "title": "产品岗第一轮", "jd_text": "产品岗位",
                 "questions": [{"question": "如何整理需求？"}], "answers": ["先访谈再整理"],
                 "question_scores": [{"score": 75, "reason": "结构明确"}],
                 "overall_feedback": {"score": 75, "suggestion": "补充过程"}}
        value.update(changes)
        return (client or self.a).post("/api/interview-records", json=value)

    def test_first_read_and_roundtrip_with_reopened_connections(self):
        self.assertEqual(self.a.get("/api/workspace").json(), {
            "ok": True, "revision": 0, "state": None, "saved_at": None,
        })
        result = self.save()
        self.assertEqual(result.status_code, 200, result.text)
        self.assertEqual(result.json()["revision"], 1)
        restored = TestClient(app, headers=HEADER)
        self.addCleanup(restored.close)
        restored.cookies.update(self.a.cookies)
        data = restored.get("/api/workspace").json()
        self.assertEqual(data["state"], STATE)
        self.assertEqual(data["saved_at"], result.json()["saved_at"])
        self.assertEqual(data["revision"], 1)
        self.a.post("/api/auth/logout")
        self.a.post("/api/auth/login", json={"username": "persist_a", "password": "demo-password-123"})
        self.assertEqual(self.a.get("/api/workspace").json()["state"], STATE)

    def test_updates_preserve_state_and_conflict_does_not_overwrite(self):
        self.assertEqual(self.save().status_code, 200)
        newer = dict(STATE, jd_text="运营岗位", profile=None, markdown="")
        self.assertEqual(self.save(1, newer).json()["revision"], 2)
        for revision in (0, 1, 999):
            self.assertEqual(self.save(revision).status_code, 409)
        self.assertEqual(self.a.get("/api/workspace").json()["state"], newer)

    def test_parallel_first_saves_and_updates_only_one_wins(self):
        clients = [TestClient(app, headers=HEADER), TestClient(app, headers=HEADER)]
        for client in clients:
            self.addCleanup(client.close)
            client.cookies.update(self.a.cookies)
        for revision in (0, 1):
            with ThreadPoolExecutor(max_workers=2) as executor:
                responses = list(executor.map(lambda client: self.save(revision, client=client), clients))
            self.assertEqual(sorted(r.status_code for r in responses), [200, 409])
        self.assertEqual(self.a.get("/api/workspace").json()["revision"], 2)

    def test_user_isolation_and_stale_account_guard(self):
        self.assertEqual(self.save().status_code, 200)
        self.assertIsNone(self.b.get("/api/workspace").json()["state"])
        self.assertEqual(self.save(client=self.b).status_code, 409)
        other = dict(STATE, source_text="另一账户")
        self.assertEqual(self.save(client=self.b, user_id=self.uid_b, state=other).status_code, 200)
        self.assertEqual(self.a.get("/api/workspace").json()["state"], STATE)
        self.assertEqual(self.b.get("/api/workspace").json()["state"], other)

    def test_auth_and_csrf_required(self):
        guest = TestClient(app, headers=HEADER)
        self.addCleanup(guest.close)
        record_id = self.record().json()["id"]
        for path in ("/api/workspace", "/api/interview-records", f"/api/interview-records/{record_id}"):
            self.assertEqual(guest.get(path).status_code, 401)
        self.assertEqual(guest.post("/api/workspace", json={}).status_code, 401)
        self.assertEqual(guest.post("/api/interview-records", json={}).status_code, 401)
        self.assertEqual(guest.delete(f"/api/interview-records/{record_id}").status_code, 401)
        no_header = TestClient(app)
        self.addCleanup(no_header.close)
        no_header.cookies.update(self.a.cookies)
        self.assertEqual(no_header.post("/api/workspace", json={}).status_code, 403)
        self.assertEqual(no_header.post("/api/interview-records", json={}).status_code, 403)
        self.assertEqual(no_header.delete(f"/api/interview-records/{record_id}").status_code, 403)

    def test_workspace_invalid_shapes_and_types(self):
        for patch_state in ({"page": "unknown"}, {"jd_keywords": "text"}, {"source_text": 1},
                            {"profile": {"name": "bad", "experiences": "not-list"}},
                            {"unexpected": "field"}):
            with self.subTest(patch_state=patch_state):
                self.assertEqual(self.save(state=dict(STATE, **patch_state)).status_code, 422)
        invalid = copy.deepcopy(STATE)
        invalid["profile"]["experiences"][0]["actions"] = [1]
        self.assertEqual(self.save(state=invalid).status_code, 422)
        invalid = copy.deepcopy(STATE)
        invalid["profile"]["user_confirmed"] = "yes"
        self.assertEqual(self.save(state=invalid).status_code, 422)
        for revision in (-1, True, "0"):
            self.assertEqual(self.save(revision).status_code, 422)
        self.assertIsNone(self.a.get("/api/workspace").json()["state"])

    def test_limits_reject_without_mutation(self):
        with patch.object(workspace, "MAX_WORKSPACE_BYTES", 10):
            self.assertEqual(self.save().status_code, 413)
        self.assertIsNone(self.a.get("/api/workspace").json()["state"])
        with patch.object(interview_records, "MAX_INTERVIEW_BYTES", 10):
            self.assertEqual(self.record().status_code, 413)
        self.assertEqual(self.a.get("/api/interview-records").json()["records"], [])

    def test_interview_crud_order_and_ungraded_record(self):
        first = self.record()
        self.assertEqual(first.status_code, 200, first.text)
        second = self.a.post("/api/interview-records", json={"expected_user_id": self.uid_a})
        self.assertEqual(second.status_code, 200, second.text)
        records = self.a.get("/api/interview-records").json()["records"]
        self.assertEqual([item["id"] for item in records], [second.json()["id"], first.json()["id"]])
        record = self.a.get(f'/api/interview-records/{first.json()["id"]}').json()["record"]
        self.assertEqual(record["answers"], ["先访谈再整理"])
        self.assertEqual(record["overall_feedback"]["score"], 75)
        self.assertNotIn("expected_user_id", record)
        ungraded = self.a.get(f'/api/interview-records/{second.json()["id"]}').json()["record"]
        self.assertEqual(ungraded["question_scores"], [])
        self.assertEqual(ungraded["overall_feedback"], {})
        self.assertEqual(self.a.delete(f'/api/interview-records/{first.json()["id"]}').json(), {"ok": True})
        self.assertEqual(self.a.get(f'/api/interview-records/{first.json()["id"]}').status_code, 404)

    def test_interview_ownership_and_unknown_are_uniform_404(self):
        record_id = self.record().json()["id"]
        self.assertEqual(self.b.get("/api/interview-records").json()["records"], [])
        self.assertEqual(self.record(client=self.b).status_code, 409)
        for target in (record_id, "missing"):
            self.assertEqual(self.b.get(f"/api/interview-records/{target}").json(), {"detail": "面试记录不存在"})
            self.assertEqual(self.b.delete(f"/api/interview-records/{target}").status_code, 404)
        self.assertEqual(self.a.get(f"/api/interview-records/{record_id}").status_code, 200)

    def test_interview_invalid_payload(self):
        for changes in ({"questions": ["not-object"]}, {"answers": [1]}, {"question_scores": [1]},
                        {"overall_feedback": []}, {"title": "x" * 201}):
            with self.subTest(changes=changes):
                self.assertEqual(self.record(**changes).status_code, 422)
        self.assertEqual(self.a.post("/api/interview-records", json={
            "expected_user_id": self.uid_a, "user_id": self.uid_b,
        }).status_code, 422)
        self.assertEqual(self.a.get("/api/interview-records").json()["records"], [])


if __name__ == "__main__":
    unittest.main()
