"""模型 Base URL 策略：别处能用的端点这里也要能用，同时挡住内网跳板。"""
from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from fastapi import HTTPException  # noqa: E402

from core import model_preferences as mp  # noqa: E402


class ApprovedUrl(unittest.TestCase):
    def test_provider_presets_pass(self) -> None:
        self.assertEqual(mp.approved_url("deepseek", ""), "https://api.deepseek.com")
        self.assertEqual(mp.approved_url("glm", ""), "https://open.bigmodel.cn/api/paas/v4")

    def test_deepseek_v1_is_normalized(self) -> None:
        self.assertEqual(mp.approved_url("deepseek", "https://api.deepseek.com/v1"),
                         "https://api.deepseek.com")
        self.assertEqual(mp.approved_url("custom", "https://api.deepseek.com/v1"),
                         "https://api.deepseek.com")

    def test_third_party_public_https_is_allowed_without_allowlist(self) -> None:
        # 用户自己的 Key + 自己的服务商：不应因为管理员没配白名单而被拒
        for url in ("https://api.openai-next.com/v1", "https://api.moonshot.cn/v1",
                    "https://openrouter.ai/api/v1", "https://dashscope.aliyuncs.com/compatible-mode/v1"):
            with self.subTest(url=url):
                self.assertEqual(mp.approved_url("custom", url), url)

    def test_trailing_slash_and_preset_urls_are_normalized(self) -> None:
        self.assertEqual(mp.approved_url("custom", "https://api.moonshot.cn/v1/"),
                         "https://api.moonshot.cn/v1")

    def test_http_and_malformed_urls_are_rejected(self) -> None:
        for url in ("http://api.example.com/v1",
                    "https://user:pw@api.example.com/v1",
                    "https://api.example.com/v1?x=1",
                    "https://api.example.com/v1#frag",
                    "https://api.example.com/v1/chat/completions",
                    ""):
            with self.subTest(url=url), self.assertRaises(HTTPException) as caught:
                mp.approved_url("custom", url)
            self.assertEqual(caught.exception.status_code, 422)

    def test_internal_addresses_are_blocked(self) -> None:
        for url in ("https://127.0.0.1:8000/v1", "https://10.0.0.5/v1", "https://192.168.1.10/v1",
                    "https://172.16.3.4/v1", "https://169.254.169.254/latest", "https://[::1]/v1",
                    "https://localhost/v1", "https://metadata.google.internal/v1",
                    "https://printer.local/v1", "https://db.internal/v1"):
            with self.subTest(url=url), self.assertRaises(HTTPException) as caught:
                mp.approved_url("custom", url)
            self.assertEqual(caught.exception.status_code, 422)
            self.assertIn("内网", caught.exception.detail)

    def test_public_ip_literal_is_allowed(self) -> None:
        self.assertEqual(mp.approved_url("custom", "https://8.8.8.8/v1"), "https://8.8.8.8/v1")

    def test_strict_mode_still_enforces_allowlist(self) -> None:
        with patch.dict(os.environ, {"JOBAGENT_CUSTOM_MODEL_BASE_URLS_STRICT": "1",
                                     "JOBAGENT_CUSTOM_MODEL_BASE_URLS": "https://api.trusted.example/v1"}):
            self.assertEqual(mp.approved_url("custom", "https://api.trusted.example/v1"),
                             "https://api.trusted.example/v1")
            with self.assertRaises(HTTPException) as caught:
                mp.approved_url("custom", "https://api.other.example/v1")
            self.assertEqual(caught.exception.status_code, 422)
            self.assertIn("JOBAGENT_CUSTOM_MODEL_BASE_URLS", caught.exception.detail)

    def test_default_mode_ignores_allowlist(self) -> None:
        with patch.dict(os.environ, {"JOBAGENT_CUSTOM_MODEL_BASE_URLS": "https://api.trusted.example/v1"}):
            self.assertEqual(mp.approved_url("custom", "https://api.other.example/v1"),
                             "https://api.other.example/v1",
                             "默认模式下白名单只是提示，不拦截")


if __name__ == "__main__":
    unittest.main()
