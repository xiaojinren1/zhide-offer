"""账户与隔离合约：只使用临时 SQLite，不读取真实资料或调用模型。"""
import sys
import tempfile
import time
import unittest
import httpx
from io import BytesIO
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from fastapi.testclient import TestClient
from PIL import Image
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
        key_patch = patch.dict("os.environ", {
            "JOBAGENT_MODEL_ENCRYPTION_KEY": "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=",
        })
        key_patch.start()
        self.addCleanup(key_patch.stop)
        events_patch = patch("api.profiles.events.emit")
        events_patch.start()
        self.addCleanup(events_patch.stop)
        self.client = TestClient(app, headers=HEADER)
        self.addCleanup(self.client.close)

    def register(self, client=None, username="demo_a", password=PASSWORD):
        client = client or self.client
        response = client.post("/api/auth/register", json={"username": username, "password": password})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(set(response.json()), {"ok", "user", "recovery_code"})
        self.assertEqual(set(response.json()["user"]), {"id", "username"})
        self.assertTrue(response.json()["recovery_code"])
        return response

    def test_trial_uses_workbench_without_binding_to_registered_account(self):
        self.client.base_url = "http://localhost"
        trial = self.client.post("/api/auth/trial")
        self.assertEqual(trial.status_code, 200)
        self.assertIn("Max-Age=7200", trial.headers["set-cookie"])
        guest = self.client.get("/api/auth/profile").json()["user"]
        self.assertTrue(guest["guest"])
        self.assertEqual(self.client.get("/api/workspace").status_code, 200)
        self.assertIsNone(self.client.get("/api/model-preferences").json())
        self.assertEqual(self.client.post("/api/auth/trial").status_code, 200)
        self.assertEqual(self.client.get("/api/auth/me").json()["user"]["id"], guest["id"])

        with patch.dict("os.environ", {"JOBAGENT_MODEL_ENCRYPTION_KEY": ""}), patch(
            "api.model_preferences.chat_json", return_value={"ok": True}
        ):
            activated = self.client.post("/api/model-preferences", json={
                "provider": "deepseek", "model": "guest-demo", "api_key": "temporary-test-key",
            })
        self.assertEqual(activated.status_code, 200, activated.text)
        self.assertNotIn("temporary-test-key", activated.text)
        with accounts.connection() as db:
            self.assertIsNone(db.execute("SELECT 1 FROM user_model_preferences").fetchone())

        account = TestClient(app, headers=HEADER)
        self.addCleanup(account.close)
        user = self.register(account).json()["user"]
        self.assertEqual(account.post("/api/auth/trial").status_code, 409)
        self.assertNotEqual(guest["id"], user["id"])
        self.assertIsNone(account.get("/api/model-preferences").json())
        with patch.dict("os.environ", {"JOBAGENT_ADMIN_USERNAMES": user["username"]}):
            self.assertEqual(account.get("/api/user-stats").json()["registered"], 1)

        self.assertEqual(self.client.post("/api/auth/logout").status_code, 200)
        self.assertEqual(self.client.get("/api/workspace").status_code, 401)

    def test_model_usage_records_provider_counts_and_isolates_accounts(self):
        self.client.base_url = "http://localhost"
        user = self.register().json()["user"]
        response = httpx.Response(200, request=httpx.Request("POST", "https://api.deepseek.com"),
                                  json={
            "model": "actual-model",
            "usage": {"prompt_tokens": 11, "completion_tokens": 3, "total_tokens": 14},
            "choices": [{"message": {"content": '{"ok":true}'}}],
        })
        with patch("core.llm.httpx.Client") as provider:
            provider.return_value.__enter__.return_value.post.return_value = response
            activated = self.client.post("/api/model-preferences", json={
                "provider": "deepseek", "model": "configured-model", "api_key": "test-key",
            })
        self.assertEqual(activated.status_code, 200, activated.text)

        usage = self.client.get("/api/auth/model-usage")
        self.assertEqual(usage.headers["cache-control"], "no-store")
        report = usage.json()
        self.assertEqual(report["models"][0]["total_tokens"], 14)
        self.assertEqual(report["records"][0]["model"], "actual-model")
        self.assertEqual(report["records"][0]["input_tokens"], 11)
        self.assertIn("+00:00", report["records"][0]["used_at"])
        self.assertNotIn("test-key", usage.text)

        with TestClient(app, headers=HEADER) as other:
            self.assertEqual(other.get("/api/auth/model-usage").status_code, 401)
            self.register(other, username="demo_b")
            isolated = other.get("/api/auth/model-usage", params={"user_id": user["id"]})
            self.assertEqual(isolated.json(), {"models": [], "records": [], "next_before": None})

    def test_trial_uses_separate_models_without_platform_fallback(self):
        self.client.base_url = "http://localhost"
        self.assertEqual(self.client.post("/api/auth/trial").status_code, 200)
        self.addCleanup(self.client.post, "/api/auth/logout")
        image = BytesIO()
        Image.new("RGB", (64, 64)).save(image, format="PNG")
        files = {"file": ("sample.png", image.getvalue(), "image/png")}
        text_path = "/api/resume/parse-text"
        image_path = "/api/resume/parse-image"
        preference = "/api/model-preferences"
        with patch(
            "core.llm.settings", return_value={
                "base_url": "https://example.com", "model": "platform", "api_key": "platform-key",
            }
        ):
            self.assertEqual(self.client.post(text_path, json={"text": "sample"}).status_code, 428)
            self.assertEqual(self.client.post(image_path, files=files).status_code, 428)
        with patch("core.llm._post_messages", return_value={"content": '{"color":"blue"}'}) as probe:
            result = self.client.post(preference + "?kind=vision", json={
                "provider": "glm", "model": "vision-test", "api_key": "vision-key",
            })
        self.assertEqual(result.status_code, 200, result.text)
        self.assertTrue(probe.call_args.args[1][1]["content"][1]["image_url"]["url"].startswith("data:image/png;base64,"))
        self.assertIsNone(self.client.get(preference).json())

        from core.llm import provider_chain
        from engine.resume_parser import profile_from_dict
        def parse_image(*args):
            self.assertEqual(provider_chain()[0]["api_key"], "vision-key")
            self.assertEqual(provider_chain()[0]["model"], "vision-test")
            return profile_from_dict({})
        with patch("api.resume.parse_resume_image", side_effect=parse_image):
            self.assertEqual(self.client.post(image_path, files=files).status_code, 200)
        self.assertEqual(self.client.post(text_path, json={"text": "sample"}).status_code, 428)
        self.assertEqual(self.client.delete(preference + "?kind=vision").status_code, 200)
        self.assertEqual(self.client.post(image_path, files=files).status_code, 428)

    def test_model_preference_is_private_and_reaches_text_requests(self):
        self.client.base_url = "http://localhost"
        self.register()
        other = TestClient(app, headers=HEADER)
        self.addCleanup(other.close)
        self.register(other, username="demo_b")
        path = "/api/model-preferences"
        payload = {"provider": "deepseek", "model": "model-a", "api_key": "test-key"}
        with patch("api.model_preferences.chat_json", return_value={"ok": True}) as probe:
            activated = self.client.post(path, json=payload)
        self.assertEqual(activated.json(), {"provider": "deepseek", "model": "model-a", "base_url": "https://api.deepseek.com", "has_api_key": True})
        self.assertEqual(probe.call_args.kwargs["api_key"], "test-key")
        self.assertEqual(self.client.get(path).json(), activated.json())
        self.assertIsNone(other.get(path).json())
        shown = self.client.post(path + "/reveal")
        self.assertEqual(shown.json(), {"api_key": "test-key"})
        self.assertEqual(shown.headers["Cache-Control"], "no-store")
        other.base_url = "http://localhost"
        other.cookies.set(accounts.COOKIE_NAME, other.cookies.get(accounts.COOKIE_NAME), domain="localhost.local")
        self.assertEqual(other.post(path + "/reveal").status_code, 404)

        admin = TestClient(app, base_url="http://localhost", headers=HEADER)
        self.addCleanup(admin.close)
        owner_id = self.client.get("/api/auth/me").json()["user"]["id"]
        self.register(admin, username="admin_demo")
        with patch.dict("os.environ", {"JOBAGENT_ADMIN_USERNAMES": "admin_demo"}):
            self.assertEqual(admin.get("/api/user-stats").status_code, 200)
            for client in (other, admin):
                self.assertIsNone(client.get(path, params={"user_id": owner_id}).json())
                self.assertEqual(client.post(path + "/reveal", json={"user_id": owner_id}).status_code, 404)
                self.assertEqual(client.delete(path, params={"user_id": owner_id}).status_code, 200)
                self.assertEqual(client.post(path, json={**payload, "migration_user_id": owner_id}).status_code, 409)
                with patch("api.model_preferences.chat_json", return_value={"ok": True}):
                    self.assertEqual(client.post(path, json={**payload, "user_id": owner_id,
                                                            "api_key": "other-key"}).status_code, 200)
            self.assertEqual(self.client.post(path + "/reveal").json(), {"api_key": "test-key"})

        with accounts.connection() as db:
            blob = db.execute("SELECT key_ciphertext FROM user_model_preferences WHERE user_id = ?",
                              (owner_id,)).fetchone()[0]
        self.assertEqual(blob[0], 1)
        self.assertNotIn(b"test-key", accounts.DATABASE_PATH.read_bytes())
        self.assertEqual(self.client.post("/api/auth/logout").status_code, 200)
        self.assertEqual(self.client.post("/api/auth/login", json={"username": "demo_a", "password": PASSWORD}).status_code, 200)
        self.assertEqual(self.client.get(path).json(), activated.json())
        self.assertEqual(self.client.post(path + "/reveal", headers={"X-Requested-With": ""}).status_code, 403)
        with patch.dict("os.environ", {"JOBAGENT_MODEL_ENCRYPTION_KEY": ""}):
            self.assertEqual(self.client.post(path + "/reveal").status_code, 503)
            with patch("api.model_preferences.chat_json") as probe:
                self.assertEqual(self.client.post(path, json=payload).status_code, 503)
                probe.assert_not_called()

        from core.llm import provider_chain
        seen = []
        def inspect_provider(*_args, **_kwargs):
            seen.append(provider_chain()[0]["api_key"])
            raise RuntimeError("stop before real model call")
        with patch("api.resume.parse_resume", side_effect=inspect_provider) as parse:
            self.client.post("/api/resume/parse-text", json={"text": "sample resume"})
        parse.assert_called_once()
        self.assertEqual(seen, ["test-key"])
        bad = self.client.post(path, json={**payload, "provider": "test-key"})
        self.assertEqual(bad.status_code, 422)
        self.assertNotIn("test-key", bad.text)
        self.assertEqual(self.client.delete(path).status_code, 200)
        self.assertIsNone(self.client.get(path).json())

    def test_custom_deepseek_v1_lists_models_without_admin_configuration(self):
        self.client.base_url = "http://localhost"
        self.register()
        with patch.dict("os.environ", {"JOBAGENT_CUSTOM_MODEL_BASE_URLS": ""}), patch(
            "api.model_preferences.httpx.get"
        ) as get:
            get.return_value.json.return_value = {"data": [{"id": "deepseek-chat"}]}
            response = self.client.post("/api/model-preferences/models", json={
                "provider": "custom", "base_url": "https://api.deepseek.com/v1", "api_key": "test-key",
            })
            self.assertEqual(response.json(), {"models": ["deepseek-chat"]})
            self.assertEqual(get.call_args.args, ("https://api.deepseek.com/models",))

    def test_custom_model_listing_uses_approved_url_without_activating(self):
        self.client.base_url = "http://localhost"
        self.register()
        url = "https://gateway.example/v1"
        path = "/api/model-preferences"
        payload = {"provider": "custom", "base_url": url + "/", "api_key": "test-key"}
        with patch.dict("os.environ", {"JOBAGENT_CUSTOM_MODEL_BASE_URLS": url}), patch(
            "api.model_preferences.httpx.get"
        ) as get:
            rejected = self.client.post(path + "/models", json={**payload, "base_url": "http://127.0.0.1"})
            self.assertEqual(rejected.status_code, 422)
            get.assert_not_called()
            get.return_value.json.return_value = {"data": [{"id": "demo"}, {"id": "demo"}]}
            self.assertEqual(self.client.post(path + "/models", json=payload).json(), {"models": ["demo"]})
            self.assertEqual(get.call_args.args, (url + "/models",))
            self.assertEqual(get.call_args.kwargs["headers"], {"Authorization": "Bearer test-key"})
            self.assertFalse(get.call_args.kwargs["follow_redirects"])
            self.assertIsNone(self.client.get(path).json())
            with patch("api.model_preferences.chat_json", return_value={"ok": True}) as probe:
                active = self.client.post(path, json={**payload, "model": "demo"})
            self.assertEqual(probe.call_args.kwargs["base_url"], url)
            self.assertEqual(active.json(), {"provider": "custom", "model": "demo", "base_url": url, "has_api_key": True})
            self.assertEqual(self.client.get(path).json(), active.json())
            with patch("api.model_preferences.chat_json", return_value={"ok": True}) as probe:
                reused = self.client.post(path, json={"provider": "custom", "base_url": url, "model": "another"})
                self.assertEqual(reused.status_code, 200)
                self.assertEqual(probe.call_args.kwargs["api_key"], "test-key")
                rejected = self.client.post(path, json={
                    "provider": "custom", "base_url": "https://api.deepseek.com", "model": "another",
                })
                self.assertEqual(rejected.status_code, 422)
                different_provider = self.client.post(path, json={
                    "provider": "deepseek", "model": "another",
                })
                self.assertEqual(different_provider.status_code, 422)
                probe.assert_called_once()
            self.client.delete(path)

    def test_stats_count_distinct_active_users_and_current_week_registrations(self):
        self.register()
        other = TestClient(app, headers=HEADER)
        self.addCleanup(other.close)
        self.register(other, username="demo_b")
        other.post("/api/auth/login", json={"username": "demo_a", "password": PASSWORD})
        path = "/api/user-stats"
        with patch.dict("os.environ", {"JOBAGENT_ADMIN_USERNAMES": "demo_a"}):
            for client in (self.client, other):
                self.assertEqual(client.post(path + "/heartbeat").status_code, 200)
            overview = self.client.get(path).json()
            self.assertEqual(
                {key: overview[key] for key in ("online", "registered", "new_this_week")},
                {"online": 1, "registered": 2, "new_this_week": 2},
            )
            # 趋势是后加的可视化数据，允许存在，但不应该带出个人数据
            self.assertIn("trend", overview)

    def test_recovery_code_is_hashed_and_resets_once(self):
        registered = self.register()
        recovery = registered.json()["recovery_code"]
        with accounts.connection() as db:
            row = db.execute("SELECT recovery_code_hash FROM users WHERE username = ?", ("demo_a",)).fetchone()
            self.assertTrue(row["recovery_code_hash"])
            self.assertNotEqual(row["recovery_code_hash"], recovery)
        other_session = TestClient(app, headers=HEADER)
        self.addCleanup(other_session.close)
        other_session.post("/api/auth/login", json={"username": "demo_a", "password": PASSWORD})
        reset = self.client.post("/api/auth/reset-password", json={
            "username": "demo_a", "recovery_code": recovery, "new_password": "recovered-password-123",
        })
        self.assertEqual(reset.status_code, 200, reset.text)
        self.assertEqual(self.client.get("/api/auth/me").status_code, 200)
        self.assertEqual(other_session.get("/api/auth/me").status_code, 401)
        self.client.post("/api/auth/logout")
        self.assertEqual(self.client.post("/api/auth/login", json={"username": "demo_a", "password": PASSWORD}).status_code, 401)
        self.assertEqual(self.client.post("/api/auth/login", json={"username": "demo_a", "password": "recovered-password-123"}).status_code, 200)
        self.client.post("/api/auth/logout")
        reused = self.client.post("/api/auth/reset-password", json={
            "username": "demo_a", "recovery_code": recovery, "new_password": "another-password-123",
        })
        self.assertEqual(reused.status_code, 401)
        self.assertEqual(reused.json(), {"detail": "用户名或恢复码不正确"})

    def test_recovery_errors_are_uniform_and_csrf_is_required(self):
        self.register()
        for username, recovery in (("missing", "bad-recovery"), ("demo_a", "bad-recovery")):
            response = self.client.post("/api/auth/reset-password", json={
                "username": username, "recovery_code": recovery, "new_password": "new-password-123",
            })
            self.assertEqual(response.status_code, 401)
            self.assertEqual(response.json(), {"detail": "用户名或恢复码不正确"})
        response = self.client.post("/api/auth/reset-password", headers={"X-Requested-With": ""}, json={
            "username": "demo_a", "recovery_code": "bad-recovery", "new_password": "new-password-123",
        })
        self.assertEqual(response.status_code, 403)

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

    def test_account_profile_and_password_change_revoke_other_sessions(self):
        registered = self.register()
        self.assertEqual(self.client.get("/api/auth/profile").json(), {
            "ok": True,
            "user": {**registered.json()["user"], "avatar_url": None},
        })
        other_session = TestClient(app, headers=HEADER)
        self.addCleanup(other_session.close)
        self.assertEqual(other_session.post("/api/auth/login", json={
            "username": "demo_a", "password": PASSWORD,
        }).status_code, 200)
        previous_token = self.client.cookies.get(accounts.COOKIE_NAME)
        changed = self.client.post("/api/auth/change-password", json={
            "current_password": PASSWORD, "new_password": "new-password-123",
        })
        self.assertEqual(changed.status_code, 200, changed.text)
        self.assertNotEqual(self.client.cookies.get(accounts.COOKIE_NAME), previous_token)
        self.assertEqual(self.client.get("/api/auth/profile").status_code, 200)
        self.assertEqual(other_session.get("/api/auth/profile").status_code, 401)
        self.assertEqual(self.client.post("/api/auth/logout").status_code, 200)
        self.assertEqual(self.client.post("/api/auth/login", json={
            "username": "demo_a", "password": PASSWORD,
        }).status_code, 401)
        self.assertEqual(self.client.post("/api/auth/login", json={
            "username": "demo_a", "password": "new-password-123",
        }).status_code, 200)

    def test_change_password_requires_current_password_and_valid_new_length(self):
        self.register()
        response = self.client.post("/api/auth/change-password", json={
            "current_password": "wrong-password", "new_password": "new-password-123",
        })
        self.assertEqual(response.status_code, 401)
        for new_password in ("short", "x" * 129):
            response = self.client.post("/api/auth/change-password", json={
                "current_password": PASSWORD, "new_password": new_password,
            })
            self.assertEqual(response.status_code, 422)
            self.assertNotIn(new_password, response.text)

    @staticmethod
    def png_bytes(size=(2, 2)):
        buffer = BytesIO()
        Image.new("RGB", size, (30, 90, 160)).save(buffer, format="PNG")
        return buffer.getvalue()

    def test_avatar_upload_validates_bytes_stores_and_is_user_scoped(self):
        self.register()
        self.assertEqual(self.client.get("/api/auth/avatar").status_code, 404)
        image = self.png_bytes()
        uploaded = self.client.post("/api/auth/avatar", files={
            "file": ("photo.jpg", image, "image/jpeg"),
        })
        self.assertEqual(uploaded.status_code, 200, uploaded.text)
        self.assertEqual(uploaded.json(), {"ok": True, "avatar_url": "/api/auth/avatar"})
        fetched = self.client.get("/api/auth/avatar")
        self.assertEqual(fetched.status_code, 200)
        self.assertEqual(fetched.headers["content-type"], "image/png")
        self.assertEqual(fetched.content, image)
        self.assertEqual(self.client.get("/api/auth/profile").json()["user"]["avatar_url"], "/api/auth/avatar")

        second = TestClient(app, headers=HEADER)
        self.addCleanup(second.close)
        self.register(second, "demo_b")
        self.assertEqual(second.get("/api/auth/avatar").status_code, 404)
        self.assertIsNone(second.get("/api/auth/profile").json()["user"]["avatar_url"])
        self.assertEqual(second.delete("/api/auth/avatar").status_code, 200)
        self.assertEqual(self.client.get("/api/auth/avatar").content, image)
        self.assertEqual(self.client.delete("/api/auth/avatar").status_code, 200)
        self.assertEqual(self.client.get("/api/auth/avatar").status_code, 404)

    def test_avatar_rejects_invalid_oversized_and_oversized_dimensions(self):
        self.register()
        invalid = self.client.post("/api/auth/avatar", files={
            "file": ("fake.png", b"not an image", "image/png"),
        })
        self.assertEqual(invalid.status_code, 422)
        gif = BytesIO()
        Image.new("RGB", (2, 2), (30, 90, 160)).save(gif, format="GIF")
        unsupported = self.client.post("/api/auth/avatar", files={
            "file": ("photo.gif", gif.getvalue(), "image/gif"),
        })
        self.assertEqual(unsupported.status_code, 422)
        large = self.client.post("/api/auth/avatar", files={
            "file": ("large.png", b"x" * (2 * 1024 * 1024 + 1), "image/png"),
        })
        self.assertEqual(large.status_code, 413)
        dimensions = self.client.post("/api/auth/avatar", files={
            "file": ("large-dimensions.png", self.png_bytes((4097, 1)), "image/png"),
        })
        self.assertEqual(dimensions.status_code, 422)
        self.assertEqual(self.client.get("/api/auth/profile").json()["user"]["avatar_url"], None)


if __name__ == "__main__":
    unittest.main()
