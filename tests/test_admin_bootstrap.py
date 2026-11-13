"""首个管理员自助领取：只在没有管理员时可领取，且只成功一次。"""
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


class AdminBootstrap(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        patcher = patch.object(accounts, "DATABASE_PATH", Path(self.tmp.name) / "boot.sqlite3")
        patcher.start()
        self.addCleanup(patcher.stop)
        with accounts.connection() as db:
            for user_id, name, guest in (("u-a", "alice", None), ("u-b", "bob", None),
                                         ("u-g", "trial", 1.0)):
                db.execute(
                    "INSERT INTO users(id,username,password_hash,created_at,guest_until) VALUES(?,?,?,0,?)",
                    (user_id, name, "pbkdf2_sha256$1$00$00", guest),
                )
        self.current_user = {"id": "u-a", "username": "alice"}
        previous = dict(app.dependency_overrides)
        app.dependency_overrides[accounts.require_user] = lambda: self.current_user
        self.addCleanup(lambda: (app.dependency_overrides.clear(), app.dependency_overrides.update(previous)))
        self.client = TestClient(app)

    def as_user(self, user_id: str) -> None:
        names = {"u-a": "alice", "u-b": "bob", "u-g": "trial"}
        self.current_user = {"id": user_id, "username": names[user_id],
                             **({"guest": True} if user_id == "u-g" else {})}

    def admins(self) -> list[str]:
        with accounts.connection() as db:
            return [row[0] for row in db.execute(
                "SELECT u.username FROM user_roles r JOIN users u ON u.id = r.user_id")]

    def test_claim_closes_after_first_success(self) -> None:
        self.assertTrue(self.client.get("/api/user-stats/bootstrap").json()["claimable"])

        claimed = self.client.post("/api/user-stats/bootstrap", headers=HEADER)
        self.assertEqual(claimed.status_code, 200, claimed.text)
        self.assertEqual(self.admins(), ["alice"])

        # 入口关闭：另一个账号再试也不行
        self.as_user("u-b")
        self.assertFalse(self.client.get("/api/user-stats/bootstrap").json()["claimable"])
        self.assertEqual(self.client.post("/api/user-stats/bootstrap", headers=HEADER).status_code, 409)
        self.assertEqual(self.admins(), ["alice"], "只能有一个首个管理员，不能被覆盖")

    def test_existing_admin_blocks_claim(self) -> None:
        with accounts.connection() as db:
            db.execute("INSERT INTO user_roles(user_id, role) VALUES('u-b','admin')")
        body = self.client.get("/api/user-stats/bootstrap").json()
        self.assertFalse(body["claimable"])
        self.assertIn("已有管理员", body["reason"])
        self.assertEqual(self.client.post("/api/user-stats/bootstrap", headers=HEADER).status_code, 409)

    def test_guest_cannot_claim(self) -> None:
        self.as_user("u-g")
        self.assertFalse(self.client.get("/api/user-stats/bootstrap").json()["claimable"])
        self.assertEqual(self.client.post("/api/user-stats/bootstrap", headers=HEADER).status_code, 403)
        self.assertEqual(self.admins(), [])

    def test_claimed_admin_can_open_admin_pages(self) -> None:
        self.client.post("/api/user-stats/bootstrap", headers=HEADER)
        overview = self.client.get("/api/user-stats")
        self.assertEqual(overview.status_code, 200, overview.text)
        self.assertIsNotNone(overview.json(), "领取后应能看到管理后台数据")

    def test_claim_is_audited_in_event_log(self) -> None:
        events_file = Path(self.tmp.name) / "events.jsonl"
        with patch.dict("os.environ", {"JOBAGENT_EVENTS_PATH": str(events_file)}):
            from core import events
            original = events._path
            events.configure(str(events_file))
            try:
                self.client.post("/api/user-stats/bootstrap", headers=HEADER)
            finally:
                events.configure(original)
        self.assertTrue(events_file.is_file())
        self.assertIn("admin_bootstrap_claimed", events_file.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
