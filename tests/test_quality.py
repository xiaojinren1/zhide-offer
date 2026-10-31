import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from fastapi.testclient import TestClient

from core import accounts
from core.llm import LLMError
from main import app


class QualityContract(unittest.TestCase):
    def setUp(self):
        previous = dict(app.dependency_overrides)
        app.dependency_overrides[accounts.require_user] = lambda: {
            "id": "quality-user",
            "username": "quality_user",
        }
        self.addCleanup(lambda: (app.dependency_overrides.clear(), app.dependency_overrides.update(previous)))
        self.client = TestClient(app, headers={"X-Requested-With": "XMLHttpRequest"})
        self.payload = {
            "jd_text": "Python 后端开发，负责接口设计",
            "jd_keywords": ["Python"],
            "resume_profile": {
                "name": "演示同学",
                "skills": ["Python"],
                "education": [],
                "user_confirmed": True,
                "experiences": [{
                    "kind": "project",
                    "name": "报名系统",
                    "role": "后端开发",
                    "period": "2025.01-2025.06",
                    "actions": ["使用 Python 完成接口设计"],
                    "results": ["服务覆盖 3 个流程"],
                    "skills": ["Python"],
                }],
            },
            "resume_markdown": "# 演示同学\nPython 后端开发",
        }

    def test_blank_jd_runs_basic_check_without_parsing_or_stale_keywords(self):
        with patch("api.quality.parse_jd") as parser, patch("api.quality.run_all", return_value=[]) as scan:
            response = self.client.post("/api/quality", json={**self.payload, "jd_text": "   "})
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["ok"])
        self.assertFalse(response.json()["keyword_applicable"])
        self.assertEqual(response.json()["keyword_coverage"], 0)
        self.assertEqual(scan.call_args.args[1], [])
        parser.assert_not_called()

    def test_blank_jd_keyword_gate_does_not_fail_an_otherwise_clean_report(self):
        payload = {**self.payload, "jd_text": "", "resume_markdown": "# 演示同学\nPython 完成3个流程\na@sample.invalid\n13800138000"}
        with patch("api.quality._consistency_issues", return_value=[]), patch("api.quality.run_all", return_value=[]):
            response = self.client.post("/api/quality", json=payload)
        self.assertTrue(response.json()["passed"])

    def test_jd_parse_failure_is_propagated(self):
        payload = {key: value for key, value in self.payload.items() if key != "jd_keywords"}
        with patch("api.quality.parse_jd", side_effect=LLMError("provider failed", status_code=503)):
            response = self.client.post("/api/quality", json=payload)
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["detail"], "模型服务暂不可用，请检查模型配置或服务状态后重试")

    def test_supplied_keywords_avoid_model_parse(self):
        with patch("api.quality.parse_jd", side_effect=AssertionError("should not parse")):
            response = self.client.post("/api/quality", json=self.payload)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["ok"])


if __name__ == "__main__":
    unittest.main()
