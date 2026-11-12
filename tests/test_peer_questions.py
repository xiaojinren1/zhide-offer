"""面经 → 面试题：程序抽问题句、只作考察角度、引用可回看。"""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from fastapi.testclient import TestClient  # noqa: E402

from core import accounts  # noqa: E402
from engine import interview_v2 as engine  # noqa: E402
from engine.community import cards as community_cards, peer_questions  # noqa: E402
from main import app  # noqa: E402

HEADER = {"X-Requested-With": "XMLHttpRequest"}
CARD_BODY = (
    "一面先问数仓怎么分层，追问指标口径怎么对齐、调度失败如何补偿。"
    "还有一道手写 SQL：取每个用户最近一次登录。"
    "建议先讲治理再讲工具。想细聊可以加我微信 [微信已隐藏]。"
)


def fake_bank(*, job_title: str = "数据开发工程师", count: int = 10) -> dict:
    """构造通过引擎校验的题库：四类各一题 + 补足数量，source 双侧都引用。"""
    base = [
        {"category": "experience", "question": "你在项目里怎么分层？", "focus": "分层",
         "source_ids": ["s1"], "sample_source_ids": ["s1"],
         "follow_ups": ["为什么"], "answer_structure": ["背景", "选择"], "missing": ["量级"]},
        {"category": "professional", "question": "SQL 窗口函数怎么写？", "focus": "SQL",
         "source_ids": ["s5"], "sample_source_ids": [],
         "follow_ups": ["场景"], "answer_structure": ["写法"], "missing": ["边界"]},
        {"category": "behavior", "question": "跨团队冲突怎么处理？", "focus": "协作",
         "source_ids": ["s1"], "sample_source_ids": ["s1"],
         "follow_ups": ["结果"], "answer_structure": ["背景", "动作"], "missing": ["结果"]},
        {"category": "motivation", "question": "为什么选这个岗位？", "focus": "动机",
         "source_ids": ["s5"], "sample_source_ids": [],
         "follow_ups": ["规划"], "answer_structure": ["动机"], "missing": ["细节"]},
    ]
    extra = [
        {"category": base[index % 4]["category"], "question": f"补充题 {index}", "focus": "补充",
         "source_ids": [base[index % 4]["source_ids"][0]], "sample_source_ids": [],
         "follow_ups": ["追问"], "answer_structure": ["背景"], "missing": ["细节"]}
        for index in range(max(0, count - len(base)))
    ]
    return {"job_title": job_title, "questions": base + extra}


class ExtractQuestions(unittest.TestCase):
    def test_extracts_question_sentences_only(self) -> None:
        questions = peer_questions.extract_questions(CARD_BODY)
        self.assertTrue(any("数仓怎么分层" in item for item in questions))
        self.assertTrue(any("手写 SQL" in item for item in questions))
        self.assertFalse(any("建议先讲治理" in item for item in questions), "建议不是问题")

    def test_skips_contact_lines(self) -> None:
        self.assertEqual(peer_questions.extract_questions("加我微信私聊，怎么联系？"), [])

    def test_dedupes_and_respects_limit(self) -> None:
        body = "怎么分层？怎么分层？如何对齐？是否用过调度？为什么选这个方案？"
        questions = peer_questions.extract_questions(body, limit=3)
        self.assertEqual(len(questions), 3)
        self.assertEqual(len(set(questions)), 3)

    def test_collect_returns_refs_without_body(self) -> None:
        cards = [{"id": "c1", "title": "数据开发一面", "company": "某科技",
                  "role": "数据开发", "round": "一面", "body_md": CARD_BODY}]
        refs, questions = peer_questions.collect(cards)
        self.assertEqual(refs[0]["title"], "数据开发一面")
        self.assertNotIn("body_md", refs[0])
        self.assertTrue(all(item["card_id"] == "c1" for item in questions))

    def test_card_without_questions_is_skipped(self) -> None:
        cards = [{"id": "c2", "title": "闲聊", "body_md": "今天天气不错，公司食堂很好吃。"}]
        self.assertEqual(peer_questions.collect(cards), ([], []))


def snapshot() -> dict:
    return {
        "resume_profile": {
            "name": "演示", "skills": ["SQL"], "education": [], "raw_text": "",
            "experiences": [{"kind": "project", "name": "数据平台", "role": "开发",
                             "period": "2024", "actions": ["搭建数仓"], "results": [],
                             "skills": ["SQL"]}],
        },
        "resume_markdown": "# 演示\n\n## 经历\n数据平台：搭建数仓",
        "jd_text": "数据开发工程师，负责数仓建设",
    }


class PeerPromptContract(unittest.TestCase):
    """卡片内容只能当考察角度，不能变成候选人的事实来源。"""

    def test_peer_questions_go_into_prompt_with_guardrails(self) -> None:
        captured = {}

        def fake_model(system, payload, schema):
            captured["system"] = system
            captured["payload"] = payload
            return fake_bank()

        with patch.object(engine, "_model", side_effect=fake_model), \
                patch.object(engine, "sample_answer", return_value="示范"):
            engine.generate_bank(snapshot(), [{"card_id": "c1", "question": "数仓怎么分层？"}])

        self.assertEqual(captured["payload"]["peer_question_references"], ["数仓怎么分层？"])
        self.assertIn("不是标准答案", captured["system"])
        self.assertIn("source_ids", captured["system"])

    def test_no_card_means_no_peer_payload(self) -> None:
        captured = {}

        def fake_model(system, payload, schema):
            captured["system"] = system
            captured["payload"] = payload
            return fake_bank()

        with patch.object(engine, "_model", side_effect=fake_model), \
                patch.object(engine, "sample_answer", return_value=""):
            engine.generate_bank(snapshot(), [])
        self.assertNotIn("peer_question_references", captured["payload"])
        self.assertNotIn("不是标准答案", captured["system"])


class BankWithCards(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        patcher = patch.object(accounts, "DATABASE_PATH", Path(self.tmp.name) / "peer.sqlite3")
        patcher.start()
        self.addCleanup(patcher.stop)
        with accounts.connection() as db:
            for user_id, name in (("u-alice", "alice"), ("u-bob", "bob")):
                db.execute(
                    "INSERT INTO users(id,username,password_hash,created_at) VALUES(?,?,?,0)",
                    (user_id, name, "pbkdf2_sha256$1$00$00"),
                )
        self.current_user = {"id": "u-alice", "username": "alice"}
        previous = dict(app.dependency_overrides)
        app.dependency_overrides[accounts.require_user] = lambda: self.current_user
        self.addCleanup(lambda: (app.dependency_overrides.clear(), app.dependency_overrides.update(previous)))
        self.client = TestClient(app)

    def make_card(self, *, owner: str = "u-alice", approve: bool = True) -> str:
        with accounts.connection() as db:
            card = community_cards.submit(db, owner, kind="interview", title="数据开发一面",
                                          body_md=CARD_BODY, company="某科技", role="数据开发",
                                          round="一面")
            if approve:
                community_cards.review(db, card["id"], reviewer_id=owner, action="approve")
        return card["id"]

    def bank(self, card_ids: list[str]) -> object:
        return self.client.post("/api/interview/bank", json={
            "expected_user_id": "u-alice",
            "request_id": "11111111-1111-4111-8111-111111111111",
            "resume_profile": {
                "name": "演示", "skills": ["SQL"], "education": [], "raw_text": "",
                "user_confirmed": True,
                "experiences": [{"kind": "project", "name": "数据平台", "role": "开发",
                                 "period": "2024", "actions": ["搭建数仓"], "results": [],
                                 "skills": ["SQL"]}],
            },
            "resume_markdown": "# 演示\n\n## 经历\n数据平台",
            "jd_text": "数据开发工程师，负责数仓建设",
            "card_ids": card_ids,
        }, headers=HEADER)

    def test_bank_records_card_refs(self) -> None:
        card_id = self.make_card()
        with patch.object(engine, "_model", return_value=fake_bank()), \
                patch.object(engine, "sample_answer", return_value="示范"):
            response = self.bank([card_id])
        self.assertEqual(response.status_code, 200, response.text)
        refs = response.json()["bank"]["card_refs"]
        self.assertEqual([item["id"] for item in refs], [card_id])
        self.assertEqual(refs[0]["title"], "数据开发一面")
        self.assertNotIn("body_md", refs[0], "引用信息不含正文")

    def test_pending_card_is_ignored(self) -> None:
        card_id = self.make_card(approve=False)
        with patch.object(engine, "_model", return_value=fake_bank()), \
                patch.object(engine, "sample_answer", return_value=""):
            response = self.bank([card_id])
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["bank"]["card_refs"], [], "未审核内容不能当出题参考")

    def test_other_users_pending_card_is_ignored(self) -> None:
        card_id = self.make_card(owner="u-bob", approve=False)
        with patch.object(engine, "_model", return_value=fake_bank()), \
                patch.object(engine, "sample_answer", return_value=""):
            response = self.bank([card_id])
        self.assertEqual(response.json()["bank"]["card_refs"], [])

    def test_unknown_card_id_does_not_break_bank(self) -> None:
        with patch.object(engine, "_model", return_value=fake_bank()), \
                patch.object(engine, "sample_answer", return_value=""):
            response = self.bank(["does-not-exist"])
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["bank"]["card_refs"], [])


if __name__ == "__main__":
    unittest.main()
