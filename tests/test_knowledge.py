"""知识层合约：术语归一、范例从资料层检索、同岗位面经只读参考不进模型。"""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from fastapi.testclient import TestClient  # noqa: E402

from core import accounts  # noqa: E402
from engine.knowledge import examples, terms  # noqa: E402
from engine.matcher import _keyword_coverage  # noqa: E402
from engine.models import ParsedJD, ResumeProfile  # noqa: E402
from main import app  # noqa: E402

HEADER = {"X-Requested-With": "XMLHttpRequest"}


class TermNormalization(unittest.TestCase):
    def test_alias_is_matched_and_reported(self) -> None:
        self.assertEqual(terms.find_match("数据仓库建模", "负责数仓建模与指标口径"), "数仓建模")

    def test_original_spelling_wins_over_alias(self) -> None:
        self.assertEqual(terms.find_match("数仓", "做过数仓与数据仓库"), "数仓")

    def test_latin_terms_respect_word_boundaries(self) -> None:
        self.assertEqual(terms.find_match("ml", "我写过 html 页面"), "", "ml 不能命中 html")
        self.assertEqual(terms.find_match("ml", "做过 ML 模型"), "ml")

    def test_unknown_term_falls_back_to_literal(self) -> None:
        self.assertEqual(terms.find_match("量子计算", "量子计算实验"), "量子计算")
        self.assertEqual(terms.find_match("量子计算", "没有相关内容"), "")

    def test_present_terms_batch(self) -> None:
        hits = terms.present_terms(["数据仓库", "k8s", "量子计算"], "负责数仓建设，容器编排用 kubernetes")
        self.assertEqual(hits["数据仓库"], "数仓")
        # 同义组里两种写法都出现了，命中哪个都算对；只要说明是人能看懂的写法
        self.assertIn(hits["k8s"], set(terms.variants("k8s")))
        self.assertNotIn("量子计算", hits)

    def test_corpus_pairs_only_suggests(self) -> None:
        docs = ["要求数仓建模与指标口径治理"] * 3
        pairs = {frozenset(pair) for pair in terms.corpus_pairs(docs, min_docs=3)}
        self.assertIn(frozenset({"数仓建模", "指标口径"}), pairs, "同现的候选要能提出来")
        self.assertEqual(terms.find_match("数仓建模", "数仓建模"), "数仓建模", "候选不会自动生效")


class KeywordCoverageUsesAliases(unittest.TestCase):
    def resume(self) -> ResumeProfile:
        return ResumeProfile(
            name="演示",
            experiences=[],
            skills=["数仓建模", "指标口径治理"],
            education=[],
            raw_text="",
        )

    def test_alias_counts_as_covered_with_explanation(self) -> None:
        jd = ParsedJD(job_title="数据开发", keywords=["数据仓库建模"])
        items = _keyword_coverage(jd, self.resume())
        self.assertEqual(items[0].status, "covered")
        self.assertIn("命中同义写法：数仓建模", items[0].note)

    def test_missing_still_missing(self) -> None:
        jd = ParsedJD(job_title="数据开发", keywords=["量子计算"])
        items = _keyword_coverage(jd, self.resume())
        self.assertEqual(items[0].status, "missing")
        self.assertIn("同义写法", items[0].note)


class ExamplesFromDocuments(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db_path = Path(self.tmp.name) / "kb.sqlite3"
        patcher = patch.object(accounts, "DATABASE_PATH", self.db_path)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_seed_is_idempotent_and_retrievable(self) -> None:
        with accounts.connection() as db:
            first = examples.seed(db)
            self.assertGreaterEqual(first, 25)
            self.assertEqual(examples.seed(db), 0)
            hits = examples.retrieve(db, "数据开发工程师，数仓建设与指标治理", ["数据开发", "数仓"])
        self.assertTrue(hits)
        self.assertEqual(set(hits[0]), {"id", "weak", "strong", "technique"})

    def test_private_examples_are_not_used(self) -> None:
        with accounts.connection() as db:
            examples.seed(db)
            db.execute("UPDATE documents SET visibility = 'private' WHERE kind = 'example'")
            hits = examples.retrieve(db, "数据开发工程师，数仓建设", ["数据开发"], top_k=2)
        self.assertTrue(hits, "资料层没可用范例时要回退种子，不能静默返回空")


class RelatedCards(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        patcher = patch.object(accounts, "DATABASE_PATH", Path(self.tmp.name) / "cards.sqlite3")
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

    def test_only_public_cards_are_returned(self) -> None:
        from engine.community import cards as community_cards

        with accounts.connection() as db:
            pending = community_cards.submit(db, "u-alice", kind="interview", title="未审核的面经",
                                             body_md="数仓分层怎么做？" * 6)
        self.current_user = {"id": "u-bob", "username": "bob"}
        body = self.client.get("/api/interview/related-cards",
                               params={"jd_text": "数据开发工程师，负责数仓分层与指标口径"}).json()
        self.assertEqual(body["items"], [], "未审核内容不能出现在面试参考里")
        self.assertIn("不是标准答案", body["note"])

        with accounts.connection() as db:
            community_cards.review(db, pending["id"], reviewer_id="u-alice", action="approve")
        body = self.client.get("/api/interview/related-cards",
                               params={"jd_text": "数据开发工程师，负责数仓分层与指标口径"}).json()
        self.assertEqual(len(body["items"]), 1)
        self.assertEqual(body["items"][0]["title"], "未审核的面经")
        self.assertNotIn("user_id", body["items"][0], "只给匿名信息")

    def test_empty_jd_returns_empty(self) -> None:
        body = self.client.get("/api/interview/related-cards").json()
        self.assertEqual(body["items"], [])

    def test_unrelated_card_is_filtered_out(self) -> None:
        """只有一个通用词命中（"开发"）的卡片不能当同岗位参考。"""
        from engine.community import cards as community_cards

        with accounts.connection() as db:
            mine = community_cards.submit(db, "u-alice", kind="interview", title="数据开发一面：数仓分层",
                                          body_md="数仓分层与指标口径的追问细节。" * 4,
                                          role="数据开发", company="某数据科技")
            unrelated = community_cards.submit(db, "u-alice", kind="interview",
                                               title="移动端开发聊了聊",
                                               body_md="聊了聊移动端开发的日常，没有具体题目。" * 4,
                                               role="移动端开发", company="某出行")
            community_cards.review(db, mine["id"], reviewer_id="u-alice", action="approve")
            community_cards.review(db, unrelated["id"], reviewer_id="u-alice", action="approve")

        self.current_user = {"id": "u-bob", "username": "bob"}
        body = self.client.get("/api/interview/related-cards", params={
            "jd_text": "数据开发工程师，负责数仓分层与指标口径治理", "role": "数据开发",
        }).json()
        titles = [item["title"] for item in body["items"]]
        self.assertIn("数据开发一面：数仓分层", titles)
        self.assertNotIn("移动端开发聊了聊", titles)


if __name__ == "__main__":
    unittest.main()
