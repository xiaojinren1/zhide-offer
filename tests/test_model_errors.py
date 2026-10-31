"""共享模型错误的稳定 Mock 回归，不访问真实模型或用户数据库。"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from fastapi.testclient import TestClient
from core import llm
from core.accounts import require_user
from engine.models import ParsedJD
from main import app


PROVIDER = {"name": "primary", "model": "mock", "base_url": "https://model.invalid/v1", "api_key": "mock-key"}
TOOL_CALL = {"id": "call_1", "type": "function", "function": {"name": "check", "arguments": "{}"}}
SENSITIVE = "upstream-body-must-stay-private"


def status_error(status: int) -> httpx.HTTPStatusError:
    request = httpx.Request("POST", "https://model.invalid/private-path")
    response = httpx.Response(status, text=SENSITIVE, request=request)
    return httpx.HTTPStatusError(SENSITIVE, request=request, response=response)


class ModelErrors(unittest.TestCase):
    def setUp(self):
        for target, value in (
            ("core.llm.provider_chain", [PROVIDER]),
            ("core.llm._time.monotonic", 0.0),
        ):
            patcher = patch(target, return_value=value)
            patcher.start()
            self.addCleanup(patcher.stop)
        for target in ("core.llm._time.sleep", "core.llm.events.emit", "core.llm.budget.record"):
            patcher = patch(target)
            setattr(self, target.rsplit(".", 1)[1], patcher.start())
            self.addCleanup(patcher.stop)

    def test_http_status_and_network_classification_preserves_cause(self):
        cases = [
            (status_error(401), 503, 1), (status_error(403), 503, 1),
            (status_error(429), 429, 8), (status_error(503), 503, 8),
            (status_error(504), 504, 8),
            (httpx.ReadTimeout(SENSITIVE), 504, 8),
            (httpx.ConnectError(SENSITIVE), 503, 8),
        ]
        for cause, expected, calls in cases:
            with self.subTest(cause=type(cause).__name__, status=expected):
                once = Mock(side_effect=cause)
                with self.assertRaises(llm.LLMError) as caught:
                    llm._run_with_providers(once)
                self.assertEqual(caught.exception.status_code, expected)
                self.assertIs(caught.exception.__cause__, cause)
                self.assertEqual(caught.exception.providers_tried, ["primary"])
                self.assertEqual(once.call_count, calls)
                self.assertNotIn(SENSITIVE, str(caught.exception))
        self.assertNotIn(SENSITIVE, str(self.emit.call_args_list))

    def test_auth_failure_still_uses_configured_fallback(self):
        fallback = dict(PROVIDER, name="fallback-1")
        with patch("core.llm.provider_chain", return_value=[PROVIDER, fallback]):
            once = Mock(side_effect=[status_error(401), {"content": "完整结果"}])
            self.assertEqual(llm._run_with_providers(once), {"content": "完整结果"})
        self.assertEqual([call.args[0]["name"] for call in once.call_args_list], ["primary", "fallback-1"])

    def test_deadline_is_504_and_keeps_last_cause(self):
        cause = httpx.ReadTimeout(SENSITIVE)
        with patch("core.llm._time.monotonic", side_effect=[0.0, 0.0, 2.0]):
            with self.assertRaises(llm.LLMError) as caught:
                llm._run_with_providers(Mock(side_effect=cause), deadline=1.0)
        self.assertEqual(caught.exception.status_code, 504)
        self.assertIs(caught.exception.__cause__, cause)

    def post_response(self, *, payload=None, status=200, text=None, json_mode=False):
        response = httpx.Response(status, request=httpx.Request("POST", "https://model.invalid/v1/chat/completions"),
                                  **({"text": text} if text is not None else {"json": payload}))
        with patch("core.llm.httpx.Client") as client:
            client.return_value.__enter__.return_value.post.return_value = response
            return llm._post_messages(PROVIDER, [{"role": "user", "content": "虚构材料"}], json_mode=json_mode)

    def test_post_preserves_http_status_error(self):
        with self.assertRaises(httpx.HTTPStatusError) as caught:
            self.post_response(status=429, text=SENSITIVE)
        self.assertEqual(caught.exception.response.status_code, 429)

    def test_malformed_and_empty_responses_are_502(self):
        cases = [[], {}, {"choices": []}, {"choices": [None]}, {"choices": [{}]},
                 {"choices": [{"message": {"content": "  "}}]},
                 {"choices": [{"message": {"content": ["bad"]}}]},
                 {"choices": [{"message": {"content": None, "tool_calls": [{"id": "bad"}]}}]}]
        for payload in cases:
            with self.subTest(payload=payload):
                with self.assertRaises(llm.LLMError) as caught:
                    self.post_response(payload=payload)
                self.assertEqual(caught.exception.status_code, 502)
        with self.assertRaises(llm.LLMError) as caught:
            self.post_response(text="invalid JSON " + SENSITIVE)
        self.assertEqual(caught.exception.status_code, 502)
        self.assertNotIn(SENSITIVE, str(caught.exception))

    def test_text_and_tool_only_success(self):
        normal = {"content": "完整结果"}
        self.assertEqual(self.post_response(payload={"choices": [{"message": normal}]}), normal)
        tool_only = {"content": None, "tool_calls": [TOOL_CALL]}
        self.assertEqual(self.post_response(payload={"choices": [{"message": tool_only}]}), tool_only)

    def test_json_repair_once_for_invalid_empty_and_non_object(self):
        for content in ("", "bad JSON", "[]", "null"):
            with self.subTest(content=content):
                with patch("core.llm._post_messages", return_value={"content": content}) as post:
                    with self.assertRaises(llm.LLMError) as caught:
                        llm.chat_json("sys", "usr")
                    self.assertEqual(caught.exception.status_code, 502)
                    self.assertEqual(post.call_count, 2)
        with patch("core.llm._post_messages", side_effect=[{"content": "bad"}, {"content": '{"name":"虚构同学"}'}]) as post:
            self.assertEqual(llm.chat_json("sys", "usr"), {"name": "虚构同学"})
            self.assertEqual(post.call_count, 2)

    def test_text_api_rejects_empty_even_if_tool_call_present(self):
        with patch("core.llm._post_messages", return_value={"content": None, "tool_calls": [TOOL_CALL]}):
            with self.assertRaises(llm.LLMError) as caught:
                llm.chat("sys", "usr")
        self.assertEqual(caught.exception.status_code, 502)

    def test_tool_loop_propagates_failures_at_any_round(self):
        for status in (429, 502, 503, 504):
            failure = llm.LLMError("safe classification", status_code=status)
            for prior in ([], [{"content": "草稿", "tool_calls": [TOOL_CALL]}]):
                with self.subTest(status=status, prior=bool(prior)):
                    with patch("core.llm._run_with_providers", side_effect=prior + [failure]):
                        with self.assertRaises(llm.LLMError) as caught:
                            llm.chat_with_tools("sys", "usr", tools=[], executor=lambda *_: {"ok": True})
                        self.assertIs(caught.exception, failure)

    def test_tool_final_failure_is_not_swallowed(self):
        failure = llm.LLMError("safe classification", status_code=503)
        with patch("core.llm._run_with_providers", side_effect=[{"content": "草稿", "tool_calls": [TOOL_CALL]}, failure]):
            with self.assertRaises(llm.LLMError) as caught:
                llm.chat_with_tools("sys", "usr", tools=[], executor=lambda *_: {"ok": True}, max_rounds=1)
        self.assertIs(caught.exception, failure)

    def test_normal_tool_feedback_reaches_next_round(self):
        snapshots = []

        def post(_provider, messages, **_kwargs):
            snapshots.append([dict(message) for message in messages])
            if len(snapshots) == 1:
                return {"content": "", "tool_calls": [TOOL_CALL]}
            return {"content": "最终完整简历"}

        executor = Mock(return_value={"ok": True, "issues": []})
        with patch("core.llm._post_messages", side_effect=post):
            result = llm.chat_with_tools("sys", "usr", tools=[], executor=executor)
        self.assertEqual(result["content"], "最终完整简历")
        self.assertFalse(result["deadline_hit"])
        self.assertEqual(result["tool_calls"], ["check"])
        executor.assert_called_once_with("check", {})
        self.assertEqual(snapshots[1][-1]["role"], "tool")
        self.assertEqual(snapshots[1][-1]["tool_call_id"], "call_1")
        self.assertIn('"ok": true', snapshots[1][-1]["content"])


class ModelApiErrors(unittest.TestCase):
    def setUp(self):
        # 本组只检验下游既有模型错误的 HTTP 映射；新增规划在专门测试中覆盖。
        planner = patch('api.resume.plan_tailoring', return_value=({'requirements': []}, [], []))
        planner.start()
        self.addCleanup(planner.stop)
        previous = dict(app.dependency_overrides)
        app.dependency_overrides[require_user] = lambda: {"id": "mock-user", "username": "mock_user"}
        self.addCleanup(lambda: (app.dependency_overrides.clear(), app.dependency_overrides.update(previous)))
        self.client = TestClient(app, headers={"X-Requested-With": "XMLHttpRequest"})
        self.profile = {"name": "虚构同学", "user_confirmed": True, "experiences": [{"name": "报名系统", "actions": ["收集需求"]}]}
        for target in ("api.resume.is_configured", "core.llm.events.emit"):
            patcher = patch(target, return_value=True)
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_model_errors_reach_all_owned_routes_without_leaking(self):
        routes = [
            ("/api/resume/parse-text", {"text": "虚构材料"}, "api.resume.parse_resume"),
            ("/api/resume/generate", {"jd_text": "产品经理", "resume_profile": self.profile}, "api.resume.chat_with_tools"),
            ("/api/diagnose/parse-jd", {"jd_text": "产品经理"}, "api.diagnose.parse_jd"),
            ("/api/diagnose", {"jd_text": "产品经理", "resume_profile": self.profile}, "api.diagnose.parse_jd"),
        ]
        for status in (429, 502, 503, 504):
            for route, payload, target in routes:
                with self.subTest(route=route, status=status):
                    with patch(target, side_effect=llm.LLMError(SENSITIVE, status_code=status)):
                        response = self.client.post(route, json=payload)
                    self.assertEqual(response.status_code, status)
                    self.assertIsInstance(response.json()["detail"], str)
                    self.assertNotIn(SENSITIVE, response.text)
                    self.assertNotIn("markdown", response.json())

    def test_file_parse_model_error_and_empty_extracted_text(self):
        with patch("api.resume.parse_resume", side_effect=llm.LLMError(SENSITIVE, status_code=429)):
            response = self.client.post("/api/resume/parse", files={"file": ("mock.txt", b"synthetic text", "text/plain")})
            self.assertEqual(response.status_code, 429)
        with patch("api.resume.parse_resume") as model:
            response = self.client.post("/api/resume/parse", files={"file": ("empty.txt", b"  ", "text/plain")})
            self.assertEqual(response.status_code, 422)
            model.assert_not_called()

    def test_empty_inputs_do_not_call_model(self):
        for route, payload, target in [
            ("/api/resume/parse-text", {"text": "  "}, "api.resume.parse_resume"),
            ("/api/diagnose/parse-jd", {"jd_text": " "}, "api.diagnose.parse_jd"),
            ("/api/diagnose", {"jd_text": " ", "resume_profile": self.profile}, "api.diagnose.parse_jd"),
        ]:
            with patch(target) as model:
                self.assertEqual(self.client.post(route, json=payload).status_code, 422)
                model.assert_not_called()

    def test_semantic_match_failure_is_not_partial_success(self):
        jd = ParsedJD(job_title="产品经理", hard_requirements=["需求分析"], keywords=["需求分析"], evidence={"需求分析": "需求分析"})
        with patch("api.diagnose.parse_jd", return_value=jd), patch("engine.matcher.chat_json", side_effect=llm.LLMError(SENSITIVE, status_code=429)):
            response = self.client.post("/api/diagnose", json={"jd_text": "产品经理", "resume_profile": self.profile})
        self.assertEqual(response.status_code, 429)
        self.assertNotIn("coverage", response.json())


if __name__ == "__main__":
    unittest.main()
