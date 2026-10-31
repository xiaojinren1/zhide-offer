import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from fastapi.testclient import TestClient

from core.accounts import require_user
from main import app


class InterviewContract(unittest.TestCase):
    def setUp(self):
        previous = dict(app.dependency_overrides)
        app.dependency_overrides[require_user] = lambda: {"id": "interview-user", "username": "interview_user"}
        self.addCleanup(lambda: (app.dependency_overrides.clear(), app.dependency_overrides.update(previous)))
        self.client = TestClient(app, headers={"X-Requested-With": "XMLHttpRequest"})
        self.profile = {
            "name": "演示同学",
            "skills": ["Python"],
            "education": [],
            "user_confirmed": True,
            "experiences": [{
                "kind": "project",
                "name": "报名系统",
                "role": "产品与开发",
                "period": "2025.01-2025.06",
                "actions": ["使用 Python 整理需求并完成接口开发"],
                "results": ["服务覆盖 3 个流程"],
                "skills": ["Python"],
            }],
        }

    def test_start_always_returns_three_categories(self):
        response = self.client.post("/api/interview", json={
            "resume_markdown": "# 演示同学",
            "resume_profile": self.profile,
            "jd_text": "产品经理，要求 Python 和项目管理",
        })
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data["ok"])
        self.assertEqual(len(data["questions"]), 3)
        self.assertEqual(
            [item["category"] for item in data["questions"]],
            ["timeline", "skill_authenticity", "project_match"],
        )
        self.assertTrue(all(item["evidence"] for item in data["questions"]))

    def test_empty_answer_rejected(self):
        start = self.client.post("/api/interview", json={"resume_profile": self.profile}).json()
        response = self.client.post("/api/interview/score", json={
            "resume_profile": self.profile,
            "question": start["questions"][0],
            "answer": " ",
        })
        self.assertEqual(response.status_code, 422)

    def test_empty_facts_rejected(self):
        response = self.client.post("/api/interview", json={
            "resume_profile": {"name": "空资料", "experiences": [], "skills": []},
        })
        self.assertEqual(response.status_code, 422)

    def test_score_contains_four_dimensions_and_evidence(self):
        start = self.client.post("/api/interview", json={
            "resume_profile": self.profile,
            "jd_text": "产品经理 Python",
        }).json()
        question = start["questions"][2]
        response = self.client.post("/api/interview/score", json={
            "resume_profile": self.profile,
            "jd_text": "产品经理 Python",
            "question": question,
            "answer": "背景是报名系统。目标是产品经理岗位。我的行动是使用 Python 完成接口开发。结果服务覆盖 3 个流程，并进行了复盘。",
        })
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(set(data["dimensions"]), {"evidence", "job_match", "clarity", "structure"})
        self.assertIn("question_basis", data["evidence"])
        self.assertEqual(data["scored_by"], "deterministic_rules")

    def test_client_cannot_replace_question_evidence(self):
        start = self.client.post("/api/interview", json={"resume_profile": self.profile}).json()
        question = dict(start["questions"][0], evidence="伪造的依据")
        response = self.client.post("/api/interview/score", json={
            "resume_profile": self.profile,
            "question": question,
            "answer": "时间线是 2025.01-2025.06，负责报名系统项目。",
        })
        self.assertEqual(response.status_code, 200)
        self.assertNotEqual(response.json()["evidence"]["question_basis"], "伪造的依据")


if __name__ == "__main__":
    unittest.main()
