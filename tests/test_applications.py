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
