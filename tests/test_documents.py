"""资料层合约：建表幂等、URL 去重、字段归一、中文检索、账号隔离、级联删除。

全部使用临时数据库与合成数据，不连接外部模型，不读写仓库里的真实 `data/`。
"""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from core import accounts  # noqa: E402
from engine.documents import dedupe, normalize, store, text  # noqa: E402

USER_A = "u-alice"
USER_B = "u-bob"

JD_BODY = """岗位职责
负责数据平台的建设与维护，支撑业务报表和指标口径。

任职要求
熟悉 SQL 与数据仓库建模，了解调度系统。
有数据治理经验优先。
"""


class DocumentLayerTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db_path = Path(self.tmp.name) / "documents.sqlite3"
        patcher = patch.object(accounts, "DATABASE_PATH", self.db_path)
        patcher.start()
        self.addCleanup(patcher.stop)
        with accounts.connection() as db:
            for user_id, name in ((USER_A, "alice"), (USER_B, "bob")):
                db.execute(
                    "INSERT INTO users(id,username,password_hash,created_at) VALUES(?,?,?,0)",
                    (user_id, name, "pbkdf2_sha256$1$00$00"),
                )

    # ---- 建表 ----

    def test_schema_is_idempotent_and_complete(self) -> None:
        with accounts.connection() as db:
            tables = {row[0] for row in db.execute(
                "SELECT name FROM sqlite_master WHERE type IN ('table','view')"
            )}
        for name in ("documents", "knowledge_chunks", "knowledge_fts", "applications",
                     "anon_identities", "public_cards", "feed_sources"):
            self.assertIn(name, tables)

        # 再开一次连接不应该报错，也不应该清空数据
        with accounts.connection() as db:
            db.execute(
                "INSERT INTO documents(id,user_id,kind,source,source_key,fetched_at,created_at,updated_at)"
                " VALUES('keep',?,'jd','manual','k1',0,0,0)", (USER_A,))
        with accounts.connection() as db:
            self.assertEqual(
                db.execute("SELECT COUNT(*) FROM documents WHERE id='keep'").fetchone()[0], 1)

    # ---- 去重 ----

    def test_normalize_url_strips_tracking_and_orders_params(self) -> None:
        left = dedupe.normalize_url(
            "https://WWW.Example.com:443/job/1/?utm_source=wx&b=2&a=1#apply")
        right = dedupe.normalize_url("https://www.example.com/job/1?a=1&b=2")
        self.assertEqual(left, right)
        self.assertNotEqual(left, dedupe.normalize_url("https://www.example.com/job/2?a=1&b=2"))

    def test_source_key_prefers_url_then_identity(self) -> None:
        from_url = dedupe.source_key(url="https://x.com/a?utm_medium=m")
        self.assertEqual(from_url, dedupe.source_key(url="https://x.com/a"))
        self.assertTrue(from_url.startswith("u:"))

        from_identity = dedupe.source_key(title="数据开发工程师", company="某某科技")
        self.assertEqual(from_identity, dedupe.source_key(
            title=" 数据开发工程师 ", company="某某科技", role=""))
        self.assertTrue(from_identity.startswith("t:"))

        self.assertEqual(dedupe.source_key(), "")

    def test_simhash_detects_reordered_near_duplicate(self) -> None:
        reordered = "\n\n".join(reversed(JD_BODY.split("\n\n")))
        other = "负责品牌视觉设计，熟练使用 Figma，输出活动海报与落地页视觉方案。"
        self.assertTrue(dedupe.near_duplicate(
            dedupe.simhash64(JD_BODY), dedupe.simhash64(reordered)))
        self.assertFalse(dedupe.near_duplicate(
            dedupe.simhash64(JD_BODY), dedupe.simhash64(other)))
        self.assertFalse(dedupe.near_duplicate(0, 0))

    # ---- 归一 ----

    def test_parse_salary_variants(self) -> None:
        cases = {
            "20-35K·14薪": (20000, 35000, 14),
            "15k-25k": (15000, 25000, None),
            "8000-12000元/月": (8000, 12000, None),
            "30-50万/年": (25000, 41667, None),
            "面议": (None, None, None),
        }
        for raw, expected in cases.items():
            with self.subTest(raw=raw):
                salary = normalize.parse_salary(raw)
                self.assertEqual((salary.min, salary.max, salary.months), expected)
                self.assertEqual(salary.text, raw)

    def test_parse_experience_and_city(self) -> None:
        self.assertEqual(normalize.parse_experience("3-5年"), (3, 5))
        self.assertEqual(normalize.parse_experience("经验不限"), (0, None))
        self.assertEqual(normalize.parse_experience("1年以内"), (1, None))
        self.assertEqual(normalize.normalize_city("北京·朝阳区"), "北京")
        self.assertEqual(normalize.normalize_city("上海市"), "上海")

    def test_tokenize_splits_chinese_into_bigrams(self) -> None:
        self.assertEqual(text.tokenize("数据分析 SQL"), ["数据", "据分", "分析", "sql"])
        self.assertIsNone(text.match_query("  "))
        self.assertEqual(text.match_query("数据"), '"数据"')

    # ---- 入库去重 ----

    def test_same_url_updates_instead_of_duplicating(self) -> None:
        with accounts.connection() as db:
            draft = store.DocumentDraft(
                kind="job", source="feed", user_id=USER_A,
                title="数据开发工程师", company="某某科技",
                url="https://jobs.example.com/1?utm_source=feed",
                content_md=JD_BODY,
            )
            first_id, created = store.upsert_document(db, draft)
            self.assertTrue(created)

        with accounts.connection() as db:
            same = store.DocumentDraft(
                kind="job", source="feed", user_id=USER_A,
                url="https://jobs.example.com/1",
                content_md=JD_BODY,
            )
            second_id, created_again = store.upsert_document(db, same)
            total = db.execute("SELECT COUNT(*) FROM documents").fetchone()[0]
            row = db.execute("SELECT title FROM documents WHERE id=?", (first_id,)).fetchone()

        self.assertFalse(created_again)
        self.assertEqual(first_id, second_id)
        self.assertEqual(total, 1)
        self.assertEqual(row["title"], "数据开发工程师", "刷新采集不应抹掉已有标题")

    def test_public_pool_is_shared_and_deduped(self) -> None:
        with accounts.connection() as db:
            draft = store.DocumentDraft(kind="job", source="feed",
                                        url="https://jobs.example.com/public", content_md=JD_BODY)
            store.upsert_document(db, draft)
            store.upsert_document(db, draft)
            rows = store.list_documents(db, user_id=USER_A, visibility="public")
        self.assertEqual(len(rows), 1)
        self.assertIsNone(rows[0]["user_id"])

    # ---- 账号隔离 ----

    def test_private_document_is_invisible_to_others(self) -> None:
        with accounts.connection() as db:
            doc_id, _ = store.upsert_document(db, store.DocumentDraft(
                kind="note", source="paste", user_id=USER_A,
                title="我的复盘", content_md="一面问了索引下推。"*3))

        with accounts.connection() as db:
            self.assertIsNotNone(store.get_document(db, doc_id, user_id=USER_A))
            self.assertIsNone(store.get_document(db, doc_id, user_id=USER_B))
            self.assertEqual(store.list_documents(db, user_id=USER_B), [])
            self.assertEqual(store.search(db, "索引下推", user_id=USER_B), [])
            self.assertTrue(store.search(db, "索引下推", user_id=USER_A))

    # ---- 检索 ----

    def test_chinese_and_english_search_hit_chunks(self) -> None:
        with accounts.connection() as db:
            doc_id, _ = store.upsert_document(db, store.DocumentDraft(
                kind="job", source="feed", title="数据开发工程师",
                url="https://jobs.example.com/search-1", content_md=JD_BODY))
            hits = store.search(db, "数据仓库", user_id=USER_A)
            sql_hits = store.search(db, "SQL", user_id=USER_A)
            self.assertTrue(hits)
            self.assertEqual(hits[0]["doc_id"], doc_id)
            self.assertEqual(hits[0]["kind"], "job")
            self.assertTrue(sql_hits and sql_hits[0]["doc_id"] == doc_id)

    def test_rejected_document_disappears_everywhere(self) -> None:
        with accounts.connection() as db:
            doc_id, _ = store.upsert_document(db, store.DocumentDraft(
                kind="jd", source="paste", user_id=USER_A,
                title="待审核岗位", content_md="任职要求\n熟悉 Flink 实时计算与离线数仓。"))
            self.assertTrue(store.set_visibility(
                db, doc_id, user_id=USER_A, visibility="rejected",
                review_note="含他人联系方式", reviewed_by="admin"))

        with accounts.connection() as db:
            self.assertIsNone(store.get_document(db, doc_id, user_id=USER_A))
            self.assertEqual(store.list_documents(db, user_id=USER_A), [])
            self.assertEqual(store.search(db, "实时计算", user_id=USER_A), [])

    def test_delete_removes_chunks_and_index(self) -> None:
        with accounts.connection() as db:
            doc_id, _ = store.upsert_document(db, store.DocumentDraft(
                kind="job", source="feed", url="https://jobs.example.com/del",
                content_md=JD_BODY))
            self.assertGreater(
                db.execute("SELECT COUNT(*) FROM knowledge_chunks WHERE doc_id=?",
                           (doc_id,)).fetchone()[0], 0)
            self.assertTrue(store.delete_document(db, doc_id, user_id=""))
            self.assertEqual(db.execute("SELECT COUNT(*) FROM knowledge_chunks").fetchone()[0], 0)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM knowledge_fts").fetchone()[0], 0)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM documents").fetchone()[0], 0)

    def test_chunking_splits_long_text_with_overlap(self) -> None:
        paragraphs = [f"第{index}段：" + "数据平台建设与指标治理。" * 12 for index in range(6)]
        chunks = store.split_chunks("\n\n".join(paragraphs))
        self.assertGreater(len(chunks), 1)
        self.assertTrue(all(len(chunk) <= store.CHUNK_MAX_CHARS for chunk in chunks))
        self.assertEqual(store.split_chunks(""), [])


if __name__ == "__main__":
    unittest.main()
