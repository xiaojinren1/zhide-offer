"""投递记录关联简历快照与面试记录 + 三个新 Agent 工具。"""
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
JD_TEXT = "数据开发工程师" + chr(10) + "某科技公司 · 上海" + chr(10) + "岗位职责" + chr(10) + "负责数仓建设与指标口径。"
MARKDOWN = "# 演示同学" + chr(10) + chr(10) + "## 项目经历" + chr(10) + "- 搭建离线数仓，报表按时产出。"


class ApplicationSnapshot(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        patcher = patch.object(accounts, "DATABASE_PATH", Path(self.tmp.name) / "snap.sqlite3")
        patcher.start()
        self.addCleanup(patcher.stop)
        with accounts.connection() as db:
            db.execute("INSERT INTO users(id,username,password_hash,created_at) VALUES('u-a','alice','x',0)")
        self.current_user = {"id": "u-a", "username": "alice"}
        previous = dict(app.dependency_overrides)
        app.dependency_overrides[accounts.require_user] = lambda: self.current_user
        self.addCleanup(lambda: (app.dependency_overrides.clear(), app.dependency_overrides.update(previous)))
        self.client = TestClient(app)
        self.doc_id = self.client.post("/api/jobs/import", json={
            "text": JD_TEXT, "parse": False, "url": "https://jobs.example.com/snap",
        }, headers=HEADER).json()["id"]

    def advance(self, stage: str, **extra):
        return self.client.post(f"/api/jobs/applications/{self.doc_id}",
                                json={"stage": stage, **extra}, headers=HEADER)

    def test_resume_snapshot_recorded_when_moving_forward(self) -> None:
        self.advance("saved")
        first = self.advance("tailored", resume_markdown=MARKDOWN).json()["application"]
        self.assertIn("搭建离线数仓", first["resume_excerpt"])
        self.assertTrue(first["resume_hash"])
        self.assertIsNotNone(first["resume_saved_at"])

        # 不带正文推进时保留上一版摘要，不能把它清空
        second = self.advance("applied").json()["application"]
        self.assertEqual(second["resume_hash"], first["resume_hash"])
        self.assertEqual(second["resume_excerpt"], first["resume_excerpt"])

    def test_new_resume_version_replaces_snapshot(self) -> None:
        self.advance("saved")
        self.advance("tailored", resume_markdown=MARKDOWN)
        updated = MARKDOWN + chr(10) + "- 补充：指标口径治理。"
        body = self.advance("applied", resume_markdown=updated).json()["application"]
        self.assertIn("指标口径治理", body["resume_excerpt"])
        self.assertNotEqual(body["resume_hash"], "")

    def test_interviews_are_listed_for_the_job(self) -> None:
        self.advance("saved")
        with accounts.connection() as db:
            db.execute(
                "INSERT INTO interview_records(id,user_id,title,saved_at,record_json,job_doc_id)"
                " VALUES('rec-1','u-a','数据开发 · 模拟面试','2026-11-13T10:00:00+08:00',?,?)",
                ('{"overall_feedback": {"schema_version": 3, "report": {"overall_score": 82}}}', self.doc_id),
            )
            db.execute(
                "INSERT INTO interview_records(id,user_id,title,saved_at,record_json,job_doc_id)"
                " VALUES('rec-2','u-a','别的岗位','2026-11-13T11:00:00+08:00','{}','other-doc')",
            )
        detail = self.client.get(f"/api/jobs/applications/{self.doc_id}").json()
        self.assertEqual([item["id"] for item in detail["interviews"]], ["rec-1"])


class DocumentTools(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        patcher = patch.object(accounts, "DATABASE_PATH", Path(self.tmp.name) / "tools.sqlite3")
        patcher.start()
        self.addCleanup(patcher.stop)
        with accounts.connection() as db:
            db.execute("INSERT INTO users(id,username,password_hash,created_at) VALUES('u-a','alice','x',0)")
        self.executor, self.names = document_tools.build_executor(user_id="u-a")

    def test_three_new_tools_are_registered(self) -> None:
        for name in ("save_application", "search_knowledge", "get_interview_experience"):
            self.assertIn(name, self.names)

    def test_save_application_advances_and_reports_next_stage(self) -> None:
        imported = self.executor("import_document", {"text": JD_TEXT, "title": "数据开发工程师"})
        job_id = imported["job_id"]
        joined = self.executor("save_application", {"job_id": job_id, "stage": "saved"})
        self.assertEqual(joined["stage"], "saved")
        self.assertIn("tailored", joined["next_stage"])

        advanced = self.executor("save_application",
                                 {"job_id": job_id, "stage": "tailored", "next_action": "2026-12-01"})
        self.assertEqual(advanced["stage_label"], "已定制简历")
        self.assertEqual(advanced["next_action_date"], "2026-12-01")

    def test_tools_fail_softly(self) -> None:
        self.assertIn("error", self.executor("save_application", {"job_id": "nope", "stage": "saved"}))
        self.assertIn("error", self.executor("save_application", {"job_id": "x", "stage": "ghost"}))
        self.assertIn("error", self.executor("search_knowledge", {"query": "  "}))
        self.assertIn("error", self.executor("get_interview_experience", {"job_id": ""}))

    def test_search_knowledge_finds_own_notes(self) -> None:
        self.executor("import_document", {"text": JD_TEXT, "title": "数据开发工程师"})
        found = self.executor("search_knowledge", {"query": "指标口径"})
        self.assertGreaterEqual(found["total"], 1)
        self.assertIn("指标口径", found["items"][0]["excerpt"])
        self.assertNotIn("content_md", found["items"][0], "检索结果只给摘录，不整篇倒给模型")

    def test_get_interview_experience_returns_scores(self) -> None:
        with accounts.connection() as db:
            db.execute(
                "INSERT INTO interview_records(id,user_id,title,saved_at,record_json,job_doc_id)"
                " VALUES('rec-1','u-a','数据开发 · 模拟面试','2026-11-13T10:00:00+08:00',?,'doc-1')",
                ('{"overall_feedback": {"report": {"overall_score": 76}}}',),
            )
        result = self.executor("get_interview_experience", {"job_id": "doc-1"})
        self.assertEqual(result["total"], 1)
        self.assertEqual(result["items"][0]["overall_score"], 76)
        self.assertEqual(self.executor("get_interview_experience", {"job_id": "doc-2"})["total"], 0)


if __name__ == "__main__":
    unittest.main()
