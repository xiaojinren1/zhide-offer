"""岗位收件箱接口与 Agent 工具合约：临时数据库、Mock 模型，不联网。

覆盖四条边界：
- 模型解析失败仍然入库，并把原因放进 warnings
- 导入去重（同一 URL 两次只留一条）
- 账号隔离（A 的私有资料对 B 不可见）
- 工具失败以 `{"error": ...}` 返回，不把异常抛给模型
"""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from fastapi.testclient import TestClient  # noqa: E402

from core import accounts, document_tools  # noqa: E402
from main import app  # noqa: E402

HEADER = {"X-Requested-With": "XMLHttpRequest"}
JD_TEXT = """数据开发工程师
某科技公司 · 上海
薪资：25-40K·14薪

岗位职责
负责数据平台建设，支撑业务报表与指标口径。

任职要求
熟悉 SQL 与数据仓库建模，了解调度系统。
"""


class JobsApiContract(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        patcher = patch.object(accounts, "DATABASE_PATH", Path(self.tmp.name) / "jobs.sqlite3")
        patcher.start()
        self.addCleanup(patcher.stop)

        with accounts.connection() as db:
            for user_id, name in (("u-alice", "alice"), ("u-bob", "bob")):
                db.execute(
                    "INSERT INTO users(id,username,password_hash,created_at) VALUES(?,?,?,0)",
                    (user_id, name, "pbkdf2_sha256$1$00$00"),
                )

        self.current_user = {"id": "u-alice", "username": "alice"}
        previous = dict(app.dependency_overrides)
        app.dependency_overrides[accounts.require_user] = lambda: self.current_user
        self.addCleanup(lambda: (app.dependency_overrides.clear(), app.dependency_overrides.update(previous)))
        self.client = TestClient(app)

    def _import(self, **overrides):
        payload = {"text": JD_TEXT, "parse": False, **overrides}
        return self.client.post("/api/jobs/import", json=payload, headers=HEADER)

    # ---- 导入 ----

    def test_import_without_model_parses_salary_from_text(self) -> None:
        response = self._import()
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertTrue(body["ok"])
        self.assertTrue(body["created"])
        document = body["document"]
        self.assertEqual((document["salary_min"], document["salary_max"]), (25000, 40000))
        self.assertEqual(document["kind"], "job")
        self.assertEqual(document["visibility"], "private")

    def test_model_failure_still_stores_document(self) -> None:
        with patch("api.jobs.parse_jd", side_effect=RuntimeError("模型超时")):
            response = self._import(parse=True, title="数据开发工程师")
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertTrue(body["warnings"], "解析失败必须给出提示")
        self.assertEqual(body["document"]["title"], "数据开发工程师")
        self.assertTrue(body["document"]["content_md"].startswith("数据开发工程师"))

    def test_same_url_updates_instead_of_duplicating(self) -> None:
        first = self._import(url="https://jobs.example.com/1?utm_source=x").json()
        second = self._import(url="https://jobs.example.com/1").json()
        self.assertEqual(first["id"], second["id"])
        self.assertFalse(second["created"])
        listing = self.client.get("/api/jobs").json()
        self.assertEqual(listing["total"], 1)

    def test_blank_text_is_rejected(self) -> None:
        response = self.client.post("/api/jobs/import", json={"text": "   "}, headers=HEADER)
        self.assertEqual(response.status_code, 422)

    # ---- 读取与删除 ----

    def test_list_search_and_detail(self) -> None:
        doc_id = self._import().json()["id"]
        listing = self.client.get("/api/jobs").json()
        self.assertEqual(len(listing["items"]), 1)
        self.assertEqual(listing["items"][0]["id"], doc_id)

        found = self.client.get("/api/jobs", params={"q": "数据仓库"}).json()
        self.assertEqual(found["total"], 1)
        self.assertIn("数据仓库", found["items"][0]["matched_excerpt"])

        none = self.client.get("/api/jobs", params={"q": "核电焊工"}).json()
        self.assertEqual(none["total"], 0)

        detail = self.client.get(f"/api/jobs/{doc_id}").json()
        self.assertTrue(detail["ok"])
        self.assertTrue(detail["chunks"])
        self.assertEqual(detail["chunks"][0]["index"], 0)

    def test_delete_then_detail_is_404(self) -> None:
        doc_id = self._import().json()["id"]
        self.assertEqual(self.client.delete(f"/api/jobs/{doc_id}", headers=HEADER).status_code, 200)
        self.assertEqual(self.client.get(f"/api/jobs/{doc_id}").status_code, 404)

    # ---- 账号隔离 ----

    def test_other_account_cannot_see_private_document(self) -> None:
        doc_id = self._import().json()["id"]
        self.current_user = {"id": "u-bob", "username": "bob"}
        self.assertEqual(self.client.get(f"/api/jobs/{doc_id}").status_code, 404)
        self.assertEqual(self.client.get("/api/jobs").json()["total"], 0)
        self.assertEqual(self.client.delete(f"/api/jobs/{doc_id}", headers=HEADER).status_code, 404)

    # ---- Agent 工具 ----

    def test_tools_search_get_and_import(self) -> None:
        executor, names = document_tools.build_executor(user_id="u-alice")
        self.assertEqual(names, ["search_jobs", "get_job", "import_document"])

        imported = executor("import_document", {"text": JD_TEXT, "title": "数据开发工程师"})
        self.assertTrue(imported["created"], imported)
        job_id = imported["job_id"]

        found = executor("search_jobs", {"query": "数据仓库"})
        self.assertEqual(found["total"], 1)
        self.assertEqual(found["items"][0]["job_id"], job_id)

        detail = executor("get_job", {"job_id": job_id})
        self.assertIn("SQL", detail["content_md"])
        self.assertEqual(detail["title"], "数据开发工程师")

    def test_tools_fail_softly(self) -> None:
        executor, _ = document_tools.build_executor(user_id="u-alice")
        self.assertIn("error", executor("search_jobs", {"query": "  "}))
        self.assertIn("error", executor("get_job", {"job_id": "不存在"}))
        self.assertIn("error", executor("unknown_tool", {}))


if __name__ == "__main__":
    unittest.main()
