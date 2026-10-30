"""账户与隔离合约：只使用临时 SQLite，不读取真实资料或调用模型。"""
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from fastapi.testclient import TestClient
from core import accounts
from main import app

HEADER = {"X-Requested-With": "XMLHttpRequest"}
PASSWORD = "演示密码 123"


class AccountContract(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory(prefix="zhide-account-test-")
        self.addCleanup(folder.cleanup)
        db_patch = patch.object(accounts, "DATABASE_PATH", Path(folder.name) / "accounts.sqlite3")
        db_patch.start()
        self.addCleanup(db_patch.stop)
        events_patch = patch("api.profiles.events.emit")
        events_patch.start()
        self.addCleanup(events_patch.stop)
        self.client = TestClient(app, headers=HEADER)
        self.addCleanup(self.client.close)

    def register(self, client=None, username="demo_a", password=PASSWORD):
        client = client or self.client
        response = client.post("/api/auth/register", json={"username": username, "password": password})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(set(response.json()), {"ok", "user"})
        self.assertEqual(set(response.json()["user"]), {"id", "username"})
        return response

    def test_register_cookie_and_session_recovery(self):
        response = self.register(username="Demo_A")
        self.assertEqual(response.json()["user"]["username"], "demo_a")
        cookie = response.headers["set-cookie"]
        self.assertIn("HttpOnly", cookie)
        self.assertIn("SameSite=strict", cookie)
        self.assertIn("Max-Age=604800", cookie)
        self.assertIn("Path=/", cookie)
        self.assertNotIn("Secure", cookie)
        restored = TestClient(app, headers=HEADER)
        self.addCleanup(restored.close)
        restored.cookies.update(self.client.cookies)
        self.assertEqual(restored.get("/api/auth/me").json()["user"], response.json()["user"])

    def test_https_cookie_is_secure(self):
        client = TestClient(app, base_url="https://testserver", headers=HEADER)
        self.addCleanup(client.close)
        response = self.register(client)
        self.assertIn("Secure", response.headers["set-cookie"])
        self.assertEqual(client.get("/api/auth/me").status_code, 200)

    def test_duplicate_case_insensitive_and_login_errors(self):
        self.register()
        self.assertEqual(self.client.post("/api/auth/register", json={
            "username": "DEMO_A", "password": PASSWORD,
        }).status_code, 409)
        self.client.post("/api/auth/logout")
        errors = []
        for username, password in (("demo_a", "wrongpass"), ("missing", "wrongpass")):
            response = self.client.post("/api/auth/login", json={"username": username, "password": password})
            self.assertEqual(response.status_code, 401)
            errors.append(response.json())
        self.assertEqual(errors[0], errors[1])
        response = self.client.post("/api/auth/login", json={"username": "DEMO_A", "password": PASSWORD})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.client.get("/api/auth/me").status_code, 200)

    def test_credentials_validation_never_echoes_password(self):
        for username, password in (("aa", "secret"), ("中文用户", "validpass123"),
                                   ("valid\n", "validpass123"), ("user", "x" * 129),
                                   (123, "validpass123"), ("user", {"secret": "marker-secret"})):
            with self.subTest(username=username):
                response = self.client.post("/api/auth/register", json={"username": username, "password": password})
                self.assertEqual(response.status_code, 422)
                self.assertEqual(set(response.json()), {"detail"})
                self.assertNotIn("input", response.json())
                self.assertNotIn(str(password), response.text)

    def test_password_not_trimmed_and_hashes_salted(self):
        self.register(password=" spaced-password ")
        self.client.post("/api/auth/logout")
        response = self.client.post("/api/auth/login", json={"username": "demo_a", "password": "spaced-password"})
        self.assertEqual(response.status_code, 401)
        response = self.client.post("/api/auth/login", json={"username": "demo_a", "password": " spaced-password "})
        self.assertEqual(response.status_code, 200)
        self.register(username="demo_b", password=" spaced-password ")
        with accounts.connection() as db:
            hashes = [row[0] for row in db.execute("SELECT password_hash FROM users")]
            stored_tokens = [row[0] for row in db.execute("SELECT token_hash FROM sessions")]
        self.assertNotEqual(hashes[0], hashes[1])
        self.assertTrue(all(value.startswith("pbkdf2_sha256$600000$") for value in hashes))
        self.assertTrue(all("spaced-password" not in value for value in hashes))
        self.assertNotIn(self.client.cookies.get(accounts.COOKIE_NAME), stored_tokens)

    def test_logout_revokes_token_and_expired_session_rejected(self):
        self.register()
        token = self.client.cookies.get(accounts.COOKIE_NAME)
        self.assertEqual(self.client.post("/api/auth/logout").status_code, 200)
        self.client.cookies.set(accounts.COOKIE_NAME, token)
        self.assertEqual(self.client.get("/api/auth/me").status_code, 401)
        self.client.cookies.clear()
        self.client.post("/api/auth/login", json={"username": "demo_a", "password": PASSWORD})
        with accounts.connection() as db:
            db.execute("UPDATE sessions SET expires_at = ?", (time.time() - 1,))
        self.assertEqual(self.client.get("/api/auth/me").status_code, 401)
        self.assertEqual(self.client.get("/api/profiles/list").status_code, 401)

    def test_anonymous_all_business_routes_rejected_before_models(self):
        routes = [("POST", "/api/resume/parse"), ("POST", "/api/resume/parse-text"),
                  ("POST", "/api/resume/generate"), ("POST", "/api/diagnose"),
                  ("POST", "/api/diagnose/parse-jd"), ("POST", "/api/quality"),
                  ("POST", "/api/interview"), ("POST", "/api/profiles/save"),
                  ("GET", "/api/profiles/list"), ("GET", "/api/profiles/unknown"),
                  ("DELETE", "/api/profiles/unknown")]
        with patch("api.resume.chat_with_tools") as model:
            for method, path in routes:
                with self.subTest(path=path):
                    self.assertEqual(self.client.request(method, path).status_code, 401)
            model.assert_not_called()
        self.assertEqual(self.client.get("/api/health").status_code, 200)
        self.assertEqual(self.client.get("/").status_code, 200)

    def test_csrf_header_required_for_auth_and_business(self):
        response = self.client.post("/api/auth/register", headers={"X-Requested-With": ""},
                                    json={"username": "demo_a", "password": PASSWORD})
        self.assertEqual(response.status_code, 403)
        self.register()
        for path in ("/api/auth/login", "/api/auth/logout", "/api/profiles/save", "/api/resume/parse-text"):
            self.assertEqual(self.client.post(path, headers={"X-Requested-With": ""}, json={}).status_code, 403)
        self.assertEqual(self.client.get("/api/auth/me").status_code, 200)

    def test_cors_only_explicit_development_origins(self):
        headers = {"Origin": "https://untrusted.example", "Access-Control-Request-Method": "POST",
                   "Access-Control-Request-Headers": "X-Requested-With,Content-Type"}
        denied = self.client.options("/api/auth/login", headers=headers)
        self.assertEqual(denied.status_code, 400)
        self.assertNotIn("access-control-allow-origin", denied.headers)
        headers["Origin"] = "http://127.0.0.1:5173"
        allowed = self.client.options("/api/auth/login", headers=headers)
        self.assertEqual(allowed.status_code, 200)
        self.assertEqual(allowed.headers["access-control-allow-origin"], headers["Origin"])
        self.assertEqual(allowed.headers["access-control-allow-credentials"], "true")

    def test_two_user_profile_isolation_including_guess_and_delete(self):
        self.register()
        profile = {"name": "虚构经历", "experiences": [{"name": "演示项目"}]}
        saved = self.client.post("/api/profiles/save", json={"profile": profile, "user_id": "spoofed"}).json()
        self.assertTrue(saved["ok"])
        pid = saved["id"]
        self.assertEqual(len(self.client.get("/api/profiles/list").json()["profiles"]), 1)
        second = TestClient(app, headers=HEADER)
        self.addCleanup(second.close)
        self.register(second, "demo_b")
        self.assertEqual(second.get("/api/profiles/list").json()["profiles"], [])
        for profile_id in (pid, "unknown", "' OR 1=1 --"):
            self.assertEqual(second.get(f"/api/profiles/{profile_id}").status_code, 404)
            self.assertEqual(second.delete(f"/api/profiles/{profile_id}").status_code, 404)
        self.assertEqual(self.client.get(f"/api/profiles/{pid}").json()["profile"], profile)
        self.assertEqual(self.client.delete(f"/api/profiles/{pid}").status_code, 200)
        self.assertEqual(self.client.get(f"/api/profiles/{pid}").status_code, 404)


if __name__ == "__main__":
    unittest.main()
