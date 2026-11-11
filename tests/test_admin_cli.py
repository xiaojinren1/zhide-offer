"""管理员开通 CLI：部署时忘了配名单也能在服务器终端补上角色。"""
from __future__ import annotations

import io
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from core import accounts  # noqa: E402
import manage  # noqa: E402
from main import admin_bootstrap_hint  # noqa: E402


class AdminCliContract(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        patcher = patch.object(accounts, "DATABASE_PATH", Path(self.tmp.name) / "cli.sqlite3")
        patcher.start()
        self.addCleanup(patcher.stop)
        with accounts.connection() as db:
            for user_id, name, guest in (
                ("u-a", "alice", None),
                ("u-b", "bob", None),
                ("u-guest", "trial_user", 1.0),
            ):
                db.execute(
                    "INSERT INTO users(id,username,password_hash,created_at,guest_until) VALUES(?,?,?,0,?)",
                    (user_id, name, "pbkdf2_sha256$1$00$00", guest),
                )

    def run_cli(self, *argv: str) -> tuple[int, str, str]:
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = manage.main(list(argv))
        return code, out.getvalue(), err.getvalue()

    def admins(self) -> list[str]:
        with accounts.connection() as db:
            return [row["username"] for row in db.execute(
                "SELECT u.username FROM user_roles r JOIN users u ON u.id = r.user_id"
                " WHERE r.role = 'admin' ORDER BY u.username")]

    def test_grant_then_list_then_revoke(self) -> None:
        code, out, _ = self.run_cli("admin", "grant", "Alice")  # 用户名大小写不敏感
        self.assertEqual(code, 0, out)
        self.assertIn("已把 alice 设为管理员", out)
        self.assertEqual(self.admins(), ["alice"])

        code, out, _ = self.run_cli("admin", "list")
        self.assertEqual(code, 0)
        self.assertIn("alice", out)

        # 再开一个，否则 alice 是最后一个管理员，不允许撤销
        self.run_cli("admin", "grant", "bob")
        code, out, _ = self.run_cli("admin", "revoke", "alice")
        self.assertEqual(code, 0, out)
        self.assertEqual(self.admins(), ["bob"])

    def test_grant_is_idempotent(self) -> None:
        self.run_cli("admin", "grant", "alice")
        code, out, _ = self.run_cli("admin", "grant", "alice")
        self.assertEqual(code, 0)
        self.assertIn("已经是管理员", out)
        self.assertEqual(self.admins(), ["alice"])

    def test_unknown_and_trial_accounts_are_rejected(self) -> None:
        code, _, err = self.run_cli("admin", "grant", "nobody")
        self.assertEqual(code, 1)
        self.assertIn("请先在网站上注册", err)

        code, _, err = self.run_cli("admin", "grant", "trial_user")
        self.assertEqual(code, 1)
        self.assertIn("试用账号不能设为管理员", err)
        self.assertEqual(self.admins(), [])

    def test_last_admin_cannot_be_revoked(self) -> None:
        self.run_cli("admin", "grant", "alice")
        code, _, err = self.run_cli("admin", "revoke", "alice")
        self.assertEqual(code, 1)
        self.assertIn("最后一个管理员", err)
        self.assertEqual(self.admins(), ["alice"])

        self.run_cli("admin", "grant", "bob")
        code, _, _ = self.run_cli("admin", "revoke", "alice")
        self.assertEqual(code, 0)
        self.assertEqual(self.admins(), ["bob"])

    def test_empty_state_prints_help_and_startup_hint(self) -> None:
        code, out, _ = self.run_cli("admin", "list")
        self.assertEqual(code, 0)
        self.assertIn("没有任何管理员账号", out)
        self.assertIn("manage.py admin grant", admin_bootstrap_hint())

    def test_startup_hint_disappears_after_grant(self) -> None:
        self.run_cli("admin", "grant", "alice")
        self.assertEqual(admin_bootstrap_hint(), "")


if __name__ == "__main__":
    unittest.main()
