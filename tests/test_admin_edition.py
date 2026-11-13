"""管理端与用户端分离：管理员只能由运维创建，公开注册永远不会产生管理员。"""
from __future__ import annotations

import io
import re
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from fastapi.testclient import TestClient  # noqa: E402

from core import accounts  # noqa: E402
import manage  # noqa: E402
from main import app  # noqa: E402

HEADER = {"X-Requested-With": "XMLHttpRequest"}


class AdminEdition(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        patcher = patch.object(accounts, "DATABASE_PATH", Path(self.tmp.name) / "edition.sqlite3")
        patcher.start()
        self.addCleanup(patcher.stop)
        self.client = TestClient(app)

    # ---- 公开注册不能产生管理员 ----

    def test_public_registration_never_grants_admin(self) -> None:
        created = self.client.post("/api/auth/register",
                                   json={"username": "normal_user", "password": "normal_pwd_1"},
                                   headers=HEADER)
        self.assertEqual(created.status_code, 200, created.text)
        self.assertIsNone(self.client.get("/api/user-stats").json(),
                          "普通注册账号看不到管理数据")
        for path in ("/api/user-stats/errors", "/api/jobs/sources", "/api/community/review"):
            with self.subTest(path=path):
                self.assertEqual(self.client.get(path).status_code, 403, "管理接口对普通用户一律 403")

    def test_self_service_bootstrap_endpoint_is_gone(self) -> None:
        self.client.post("/api/auth/register",
                         json={"username": "normal_user", "password": "normal_pwd_1"}, headers=HEADER)
        self.assertEqual(self.client.get("/api/user-stats/bootstrap").status_code, 404,
                         "自助领取入口已移除：谁先注册谁是管理员不合理")
        # POST 落到 /api/user-stats 的既有路由上返回 405；重点是它不再能领角色
        self.assertIn(self.client.post("/api/user-stats/bootstrap", headers=HEADER).status_code, (404, 405))
        with accounts.connection() as db:
            self.assertIsNone(db.execute("SELECT 1 FROM user_roles").fetchone())

    # ---- 运维创建管理员 ----

    def run_cli(self, *argv: str) -> tuple[int, str, str]:
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = manage.main(list(argv))
        return code, out.getvalue(), err.getvalue()

    def test_create_admin_prints_password_once_and_can_use_admin_api(self) -> None:
        code, out, _ = self.run_cli("admin", "create", "boss")
        self.assertEqual(code, 0, out)
        match = re.search(r"初始密码（只显示这一次，请立即保存）：(\S+)", out)
        self.assertIsNotNone(match, out)
        password = match.group(1)
        self.assertNotIn(password, out.split("初始密码", 1)[0], "密码只应出现在初始化那一行")

        login = self.client.post("/api/auth/login", json={"username": "boss", "password": password},
                                 headers=HEADER)
        self.assertEqual(login.status_code, 200, login.text)
        self.assertIsNotNone(self.client.get("/api/user-stats").json(), "管理员应能看到管理数据")

    def test_create_rejects_existing_account_and_bad_names(self) -> None:
        self.client.post("/api/auth/register",
                         json={"username": "normal_user", "password": "normal_pwd_1"}, headers=HEADER)
        code, _, err = self.run_cli("admin", "create", "normal_user")
        self.assertEqual(code, 1)
        self.assertIn("已存在", err)
        self.assertIn("admin grant", err, "应提示改用 grant，而不是覆盖已有密码")

        code, _, err = self.run_cli("admin", "create", "坏名字")
        self.assertEqual(code, 1)
        self.assertIn("3–32", err)

        code, _, err = self.run_cli("admin", "create", "boss2", "--password", "short")
        self.assertEqual(code, 1)
        self.assertIn("8–128", err)

    def test_create_with_explicit_password(self) -> None:
        code, out, _ = self.run_cli("admin", "create", "boss3", "--password", "explicit_pwd_1")
        self.assertEqual(code, 0, out)
        self.assertNotIn("初始密码", out, "显式传密码时不要再打印密码")
        self.assertEqual(self.client.post(
            "/api/auth/login", json={"username": "boss3", "password": "explicit_pwd_1"},
            headers=HEADER).status_code, 200)


if __name__ == "__main__":
    unittest.main()
