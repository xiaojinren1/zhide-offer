import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from fastapi.testclient import TestClient

from core import accounts
from main import app


class ResumeRevisionContract(unittest.TestCase):
    def setUp(self):
        previous = dict(app.dependency_overrides)
        app.dependency_overrides[accounts.require_user] = lambda: {
            "id": "revision-user",
            "username": "revision_user",
        }
        self.addCleanup(lambda: (app.dependency_overrides.clear(), app.dependency_overrides.update(previous)))
        self.client = TestClient(app, headers={"X-Requested-With": "XMLHttpRequest"})
        self.payload = {
            "jd_text": "Python 后端开发",
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
            "suggestions": [{
                "id": "ats-0",
                "type": "ats",
                "location": "简历格式",
                "detail": "缺少清晰的项目标题",
                "suggestion": "补充已有项目名称作为标题",
                "severity": "medium",
            }],
        }

    def test_requires_confirmed_facts(self):
        response = self.client.post("/api/resume/revise", json={
            **self.payload,
            "resume_profile": {**self.payload["resume_profile"], "user_confirmed": False},
        })
        self.assertEqual(response.status_code, 422)

    def test_rejects_empty_inputs(self):
        for key in ("resume_markdown", "suggestions"):
            response = self.client.post("/api/resume/revise", json={**self.payload, key: "" if key == "resume_markdown" else []})
            self.assertEqual(response.status_code, 422, key)

    @patch("api.resume.is_configured", return_value=True)
    @patch("api.resume.chat", return_value="# 演示同学\n\n## 项目经历\n- 使用 Python 完成接口设计")
    def test_returns_revised_markdown(self, _chat, _configured):
        response = self.client.post("/api/resume/revise", json=self.payload)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["ok"])
        self.assertIn("# 演示同学", response.json()["markdown"])


if __name__ == "__main__":
    unittest.main()
