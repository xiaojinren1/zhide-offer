"""投递看板合约：状态机、留痕、唯一记录与账号隔离。"""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from fastapi.testclient import TestClient  # noqa: E402

from core import accounts  # noqa: E402
from main import app  # noqa: E402

HEADER = {"X-Requested-With": "XMLHttpRequest"}
JD_TEXT = "数据开发工程师\n某科技公司 · 上海\n岗位职责\n负责数据平台建设。"


class ApplicationContract(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        patcher = patch.object(accounts, "DATABASE_PATH", Path(self.tmp.name) / "apps.sqlite3")
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
        self.doc_id = self.client.post("/api/jobs/import", json={
            "text": JD_TEXT, "parse": False, "url": "https://jobs.example.com/1",
        }, headers=HEADER).json()["id"]

    def advance(self, stage: str, **extra):
        payload = {"stage": stage, "note": "", "next_action": "", **extra}
        return self.client.post(f"/api/jobs/applications/{self.doc_id}", json=payload, headers=HEADER)

    def test_join_board_then_walk_to_interview(self) -> None:
        joined = self.advance("saved", next_action="2026-12-01")
        self.assertEqual(joined.status_code, 200, joined.text)
        record = joined.json()["application"]
        self.assertEqual(record["stage"], "saved")
        self.assertEqual(record["stage_label"], "已收藏")
        self.assertEqual(record["next_action_date"], "2026-12-01")
        self.assertEqual(record["job"]["title"], "数据开发工程师")

        for stage in ("tailored", "applied", "interview"):
            response = self.advance(stage, note=f"进入{stage}")
            self.assertEqual(response.status_code, 200, response.text)

        detail = self.client.get(f"/api/jobs/applications/{self.doc_id}").json()["application"]
        self.assertEqual(detail["stage"], "interview")
        stages = [event["to_stage"] for event in detail["history"]]
        self.assertEqual(stages, ["interview", "applied", "tailored", "saved"],
                         "留痕按时间倒序，能回看走过哪些步")
        self.assertEqual(detail["history"][-1]["from_stage"], "", "第一次加入记为从空状态开始")

    def test_same_job_only_one_record(self) -> None:
        self.advance("saved")
        self.advance("applied")
        listing = self.client.get("/api/jobs/applications").json()
        self.assertEqual(len(listing["items"]), 1, "推进状态是更新而不是新增记录")
        self.assertEqual(listing["items"][0]["stage"], "applied")
        self.assertEqual(listing["counts"]["applied"], 1)

    def test_illegal_transition_is_rejected(self) -> None:
        self.advance("saved")
        skipped = self.advance("offer")
        self.assertEqual(skipped.status_code, 422)
        self.assertIn("不能从", skipped.json()["detail"])
        self.assertEqual(self.client.get(f"/api/jobs/applications/{self.doc_id}")
                         .json()["application"]["stage"], "saved")

    def test_cannot_advance_without_joining_first(self) -> None:
        response = self.advance("applied")
        self.assertEqual(response.status_code, 422)
        self.assertIn("加入投递看板", response.json()["detail"])

    def test_other_account_cannot_see_or_advance(self) -> None:
        self.advance("saved")
        self.current_user = {"id": "u-bob", "username": "bob"}
        self.assertEqual(self.client.get("/api/jobs/applications").json()["items"], [])
        self.assertEqual(self.client.get(f"/api/jobs/applications/{self.doc_id}").status_code, 404)
        self.assertEqual(self.advance("tailored").status_code, 404)
        self.assertEqual(self.client.delete(f"/api/jobs/applications/{self.doc_id}",
                                            headers=HEADER).status_code, 404)

    def test_unknown_job_or_stage_is_rejected(self) -> None:
        bad_stage = self.client.post("/api/jobs/applications/whatever",
                                     json={"stage": "ghost"}, headers=HEADER)
        self.assertEqual(bad_stage.status_code, 422)
        missing = self.client.post("/api/jobs/applications/does-not-exist",
                                   json={"stage": "saved"}, headers=HEADER)
        self.assertEqual(missing.status_code, 404)
        bad_date = self.advance("saved", next_action="下周一")
        self.assertEqual(bad_date.status_code, 422)
        self.assertIn("YYYY-MM-DD", bad_date.json()["detail"])

    def test_archive_hides_from_default_list_and_can_restart(self) -> None:
        self.advance("saved")
        self.advance("archived")
        self.assertEqual(self.client.get("/api/jobs/applications").json()["items"], [])
        archived = self.client.get("/api/jobs/applications",
                                   params={"stage": "archived"}).json()["items"]
        self.assertEqual(len(archived), 1)
        restarted = self.advance("saved")
        self.assertEqual(restarted.status_code, 200, restarted.text)

    def test_delete_removes_record_and_history(self) -> None:
        self.advance("saved")
        self.assertEqual(self.client.delete(f"/api/jobs/applications/{self.doc_id}",
                                            headers=HEADER).status_code, 200)
        self.assertEqual(self.client.get(f"/api/jobs/applications/{self.doc_id}").status_code, 404)
        with accounts.connection() as db:
            self.assertEqual(
                db.execute("SELECT COUNT(*) FROM application_events").fetchone()[0], 0,
                "删记录要连带删留痕",
            )

    def test_deleting_job_removes_application(self) -> None:
        self.advance("saved")
        self.assertEqual(self.client.delete(f"/api/jobs/{self.doc_id}", headers=HEADER).status_code, 200)
        self.assertEqual(self.client.get("/api/jobs/applications").json()["items"], [])


if __name__ == "__main__":
    unittest.main()


class JobPipelineContract(unittest.TestCase):
    """一键「匹配 → 定制 → 质检」：串起来但不越过事实确认与账号隔离。"""

    setUp = ApplicationContract.setUp

    def profile(self, confirmed: bool = True) -> dict:
        return {
            "name": "演示同学",
            "experiences": [{
                "kind": "project", "name": "数据平台", "role": "开发",
                "period": "2024.03-2024.09", "actions": ["搭建离线数仓"], "results": ["报表按时产出"],
                "skills": ["SQL"], "start": [2024, 3], "end": [2024, 9],
                "source_text": "数据平台", "quantified": [],
            }],
            "skills": ["SQL"], "education": [], "raw_text": "合成材料",
            "user_confirmed": confirmed,
        }

    def test_pipeline_runs_three_stages_in_order(self) -> None:
        # 链路把三个接口按顺序串起来；这里在它们各自的源模块上打桩
        with patch("api.diagnose.diagnose", return_value={
                "ok": True, "coverage": 0.6, "missing_hard_count": 1,
                "items": [], "jd": {"keywords": ["SQL"]}}), \
                patch("api.resume.generate", return_value={"markdown": "# 演示同学\n\n## 经历\n数据平台"}), \
                patch("api.quality.quality", return_value={
                    "ok": True, "passed": False, "keyword_coverage": 0.5,
                    "failure_reasons": ["JD 关键词覆盖率低于 60%。"], "issues": [{"type": "cliche"}]}):
            response = self.client.post(f"/api/jobs/{self.doc_id}/pipeline", json={
                "resume_profile": self.profile(), "resume_markdown": "",
            }, headers=HEADER)
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertTrue(body["ok"])
        self.assertEqual(body["match"]["coverage"], 0.6)
        self.assertEqual(body["match"]["missing_hard_count"], 1)
        self.assertIn("数据平台", body["markdown"])
        self.assertEqual(body["quality"]["passed"], False)
        self.assertEqual(body["keyword_coverage"], 0.5)
        self.assertEqual(body["doc_id"], self.doc_id)

    def test_pipeline_requires_confirmed_facts(self) -> None:
        response = self.client.post(f"/api/jobs/{self.doc_id}/pipeline", json={
            "resume_profile": self.profile(confirmed=False),
        }, headers=HEADER)
        self.assertEqual(response.status_code, 422)
        self.assertIn("确认经历事实", response.json()["detail"])

    def test_pipeline_is_account_scoped(self) -> None:
        with patch("api.diagnose.diagnose", return_value={"ok": True, "jd": {"keywords": []},
                                                         "coverage": 0, "items": []}), \
                patch("api.resume.generate", return_value={"markdown": "# x"}), \
                patch("api.quality.quality", return_value={"ok": True, "issues": []}):
            self.current_user = {"id": "u-bob", "username": "bob"}
            response = self.client.post(f"/api/jobs/{self.doc_id}/pipeline", json={
                "resume_profile": self.profile(),
            }, headers=HEADER)
        self.assertEqual(response.status_code, 404)
        self.assertIn("无权使用", response.json()["detail"])

    def test_pipeline_surfaces_stage_failure(self) -> None:
        from core.llm import LLMError
        with patch("api.diagnose.diagnose", side_effect=LLMError("boom", status_code=504)):
            response = self.client.post(f"/api/jobs/{self.doc_id}/pipeline", json={
                "resume_profile": self.profile(),
            }, headers=HEADER)
        self.assertEqual(response.status_code, 504)


class ApplicationOnPublicPool(unittest.TestCase):
    """公共岗位池（采集来的公告，user_id 为 NULL）也要能加入投递看板。

    早先按"文档 owner == 当前用户"判断权限，导致点「加入投递看板」直接报
    “岗位不存在或无权操作”——采集来的岗位 owner 本来就是 NULL。
    """

    setUp = ApplicationContract.setUp

    def make_public_doc(self) -> str:
        with accounts.connection() as db:
            db.execute(
                "INSERT INTO documents(id, user_id, kind, source, source_key, title, company,"
                " content_md, visibility, fetched_at, created_at, updated_at)"
                " VALUES(?,NULL,'job','feed',?,'某市事业单位招聘公告','某单位',?,'public',0,0,0)",
                ("doc-public-1", "feed:doc-public-1", "某市事业单位招聘公告\n岗位职责\n负责数据统计。"),
            )
        return "doc-public-1"

    def test_public_pool_job_can_join_board(self) -> None:
        doc_id = self.make_public_doc()
        response = self.client.post(f"/api/jobs/applications/{doc_id}",
                                    json={"stage": "saved"}, headers=HEADER)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["application"]["job"]["title"], "某市事业单位招聘公告")
        self.assertEqual(response.json()["application"]["job"]["company"], "某单位")
        # 推进也正常
        advanced = self.client.post(f"/api/jobs/applications/{doc_id}",
                                    json={"stage": "applied"}, headers=HEADER)
        self.assertEqual(advanced.status_code, 200, advanced.text)

    def test_public_doc_is_shared_but_records_are_isolated(self) -> None:
        doc_id = self.make_public_doc()
        self.client.post(f"/api/jobs/applications/{doc_id}", json={"stage": "saved"}, headers=HEADER)
        self.current_user = {"id": "u-bob", "username": "bob"}
        self.assertEqual(self.client.get("/api/jobs/applications").json()["items"], [],
                         "别人在同一个公共岗位上的记录不能互相可见")
        self.assertEqual(self.client.get(f"/api/jobs/applications/{doc_id}").status_code, 404)
        joined = self.client.post(f"/api/jobs/applications/{doc_id}",
                                  json={"stage": "saved"}, headers=HEADER)
        self.assertEqual(joined.status_code, 200, joined.text)

    def test_other_private_document_still_rejected(self) -> None:
        # self.doc_id 属于 u-alice（setUp 里导入）
        self.current_user = {"id": "u-bob", "username": "bob"}
        response = self.client.post(f"/api/jobs/applications/{self.doc_id}",
                                    json={"stage": "saved"}, headers=HEADER)
        self.assertEqual(response.status_code, 404)

    def test_pipeline_accepts_public_pool_job(self) -> None:
        doc_id = self.make_public_doc()
        with patch("api.diagnose.diagnose", return_value={
                "ok": True, "coverage": 0.4, "missing_hard_count": 0, "items": [],
                "jd": {"keywords": ["SQL"]}}), \
                patch("api.resume.generate", return_value={"markdown": "# 演示同学"}), \
                patch("api.quality.quality", return_value={"ok": True, "issues": []}):
            response = self.client.post(f"/api/jobs/{doc_id}/pipeline", json={
                "resume_profile": {
                    "name": "演示同学",
                    "experiences": [{"kind": "project", "name": "数据平台", "role": "开发",
                                     "period": "2024", "actions": ["搭建数仓"], "results": [],
                                     "skills": ["SQL"]}],
                    "skills": ["SQL"], "education": [], "raw_text": "材料",
                    "user_confirmed": True,
                },
            }, headers=HEADER)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertTrue(response.json()["ok"])

    def test_pipeline_propagates_model_not_configured(self) -> None:
        """没配模型时要原样返回 428，让前端弹"去配置模型"，而不是 200 + 一句失败文案。"""
        from fastapi import HTTPException

        with patch("api.diagnose.diagnose",
                   side_effect=HTTPException(status_code=428, detail="请先在模型设置中配置并启用文本模型")):
            response = self.client.post(f"/api/jobs/{self.doc_id}/pipeline", json={
                "resume_profile": {
                    "name": "演示同学",
                    "experiences": [{"kind": "project", "name": "数据平台", "role": "开发",
                                     "period": "2024", "actions": ["搭建数仓"], "results": [],
                                     "skills": ["SQL"]}],
                    "skills": ["SQL"], "education": [], "raw_text": "材料",
                    "user_confirmed": True,
                },
            }, headers=HEADER)
        self.assertEqual(response.status_code, 428)
        self.assertIn("文本模型", response.json()["detail"])
