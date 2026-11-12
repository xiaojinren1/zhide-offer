"""错误统计合约：只给管理员、只返回脱敏明细、按状态码分类、重试不算失败。"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from fastapi.testclient import TestClient  # noqa: E402

from core import accounts, event_log  # noqa: E402
from main import app  # noqa: E402

HEADER = {"X-Requested-With": "XMLHttpRequest"}


def write_events(path: Path, events: list[dict]) -> None:
    path.write_text("\n".join(json.dumps(item, ensure_ascii=False) for item in events) + "\n",
                    encoding="utf-8")


class ErrorTrendContract(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        db_patch = patch.object(accounts, "DATABASE_PATH", root / "errors.sqlite3")
        db_patch.start()
        self.addCleanup(db_patch.stop)
        self.events_path = root / "events.jsonl"
        env_patch = patch.dict("os.environ", {"JOBAGENT_EVENTS_PATH": str(self.events_path)})
        env_patch.start()
        self.addCleanup(env_patch.stop)

        with accounts.connection() as db:
            for user_id, name in (("u-admin", "admin"), ("u-alice", "alice")):
                db.execute(
                    "INSERT INTO users(id,username,password_hash,created_at) VALUES(?,?,?,0)",
                    (user_id, name, "pbkdf2_sha256$1$00$00"),
                )
            db.execute("INSERT INTO user_roles(user_id, role) VALUES('u-admin','admin')")
        self.current_user = {"id": "u-alice", "username": "alice"}
        previous = dict(app.dependency_overrides)
        app.dependency_overrides[accounts.require_user] = lambda: self.current_user
        self.addCleanup(lambda: (app.dependency_overrides.clear(), app.dependency_overrides.update(previous)))
        self.client = TestClient(app)

    def now_stamp(self) -> str:
        from datetime import datetime, timedelta, timezone

        return (datetime.now(timezone.utc) - timedelta(minutes=5)).strftime("%Y-%m-%d %H:%M:%S")

    def as_admin(self) -> None:
        self.current_user = {"id": "u-admin", "username": "admin"}

    def test_non_admin_is_rejected(self) -> None:
        self.assertEqual(self.client.get("/api/user-stats/errors").status_code, 403)

    def test_classifies_by_status_code_and_feature(self) -> None:
        write_events(self.events_path, [
            {"type": "model_request_failed", "status_code": 429, "path": "/api/resume/generate",
             "timestamp": self.now_stamp()},
            {"type": "model_request_failed", "status_code": 428, "path": "/api/quality",
             "timestamp": self.now_stamp()},
            {"type": "llm_flow_deadline", "rounds_done": 2, "timestamp": self.now_stamp()},
            {"type": "error", "stage": "jobs_import_parse", "error": "secret detail",
             "timestamp": self.now_stamp()},
        ])
        self.as_admin()
        body = self.client.get("/api/user-stats/errors").json()
        categories = {item["id"] for item in body["by_category"]}
        self.assertEqual(categories, {"model_rate_limited", "config_missing", "model_timeout",
                                      "model_unavailable"})
        features = {item["feature"] for item in body["by_feature"]}
        self.assertIn("简历生成", features, "路径要能归类到具体功能")
        self.assertIn("简历质检", features)
        self.assertEqual(body["totals"]["24h"], 4)

    def test_retry_attempts_are_not_counted_as_failures(self) -> None:
        write_events(self.events_path, [
            {"type": "llm_provider_failed", "provider": "primary", "status_code": 503,
             "timestamp": self.now_stamp()},
            {"type": "llm_failover_ok", "provider": "fallback-1", "timestamp": self.now_stamp()},
        ])
        self.as_admin()
        body = self.client.get("/api/user-stats/errors").json()
        self.assertEqual(body["totals"]["24h"], 0, "单次尝试失败但已切换成功，不算故障")
        self.assertEqual(body["retries"]["24h"], 1)

    def test_payload_never_contains_raw_error_text_or_material(self) -> None:
        write_events(self.events_path, [{
            "type": "error", "stage": "resume_generate",
            "error": "sk-live-abcdef123 张三的手机号 13800001111 简历正文片段",
            "path": "/api/resume/generate", "timestamp": self.now_stamp(),
        }])
        self.as_admin()
        response = self.client.get("/api/user-stats/errors")
        text = response.text
        for forbidden in ("sk-live-abcdef123", "13800001111", "简历正文片段"):
            self.assertNotIn(forbidden, text, "错误明细不得回传原始错误文本或个人材料")
        self.assertIn("trace_id", text)

    def test_old_events_outside_window_are_ignored(self) -> None:
        write_events(self.events_path, [
            {"type": "model_request_failed", "status_code": 504, "timestamp": "2020-01-01 00:00:00"},
            {"type": "model_request_failed", "status_code": 504, "timestamp": self.now_stamp()},
        ])
        self.as_admin()
        body = self.client.get("/api/user-stats/errors", params={"days": 7}).json()
        self.assertEqual(body["totals"]["window"], 1)

    def test_window_bounds_are_validated(self) -> None:
        self.as_admin()
        self.assertEqual(self.client.get("/api/user-stats/errors", params={"days": 0}).status_code, 422)
        self.assertEqual(self.client.get("/api/user-stats/errors", params={"days": 99}).status_code, 422)

    def test_missing_and_corrupt_event_file_does_not_break(self) -> None:
        self.as_admin()
        self.assertEqual(self.client.get("/api/user-stats/errors").json()["totals"]["24h"], 0)
        self.events_path.write_text('{"type": "error", "stage": "x"\nnot-json\n', encoding="utf-8")
        response = self.client.get("/api/user-stats/errors")
        self.assertEqual(response.status_code, 200, "损坏行只跳过，不能整页报错")

    def test_recent_errors_group_repeats(self) -> None:
        """同一排查编号刷屏要合并成一行带次数，否则管理员只看到重复。"""
        write_events(self.events_path, [
            {"type": "error", "stage": "jobs_import_parse", "timestamp": self.now_stamp()},
            {"type": "error", "stage": "jobs_import_parse", "timestamp": self.now_stamp()},
            {"type": "error", "stage": "jobs_import_parse", "timestamp": self.now_stamp()},
            {"type": "error", "stage": "resume_generate", "timestamp": self.now_stamp()},
        ])
        self.as_admin()
        recent = self.client.get("/api/user-stats/errors").json()["recent"]
        self.assertEqual(len(recent), 2, "两条不同排查编号各一行")
        counts = sorted(item["count"] for item in recent)
        self.assertEqual(counts, [1, 3])

    def test_row_cap_keeps_memory_bounded(self) -> None:
        self.assertEqual(event_log.MAX_RECORDS, 20000)
        self.assertEqual(event_log.MAX_TAIL_BYTES, 4 * 1024 * 1024)


if __name__ == "__main__":
    unittest.main()
