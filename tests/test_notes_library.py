"""私有资料区（笔记/面经/技术资料）：标签、筛选、编辑、账号隔离。"""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from fastapi.testclient import TestClient  # noqa: E402

from core import accounts  # noqa: E402
from main import app  # noqa: E402

HEADER = {"X-Requested-With": "XMLHttpRequest"}
NOTE = chr(10).join([
    "面试复盘：某公司数据岗",
    "一面问了数仓分层与指标口径，二面手写窗口函数。",
    "下一步：补一下调度失败补偿的讲法。",
])


class NotesLibrary(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        patcher = patch.object(accounts, "DATABASE_PATH", Path(self.tmp.name) / "notes.sqlite3")
        patcher.start()
        self.addCleanup(patcher.stop)
        with accounts.connection() as db:
            for user_id, name in (("u-a", "alice"), ("u-b", "bob")):
                db.execute("INSERT INTO users(id,username,password_hash,created_at) VALUES(?,?,?,0)",
                           (user_id, name, "pbkdf2_sha256$1$00$00"))
        self.current_user = {"id": "u-a", "username": "alice"}
        previous = dict(app.dependency_overrides)
        app.dependency_overrides[accounts.require_user] = lambda: self.current_user
        self.addCleanup(lambda: (app.dependency_overrides.clear(), app.dependency_overrides.update(previous)))
        self.client = TestClient(app)

    def create(self, **overrides):
        payload = {"text": NOTE, "kind": "note", "parse": False,
                   "title": "面试复盘-某公司数据岗", "tags": ["面经", "数据岗"], **overrides}
        return self.client.post("/api/jobs/import", json=payload, headers=HEADER)

    def test_create_note_with_tags(self) -> None:
        body = self.create().json()
        self.assertTrue(body["ok"], body)
        document = body["document"]
        self.assertEqual(document["kind"], "note")
        self.assertEqual(document["tags"], ["面经", "数据岗"])

    def test_filter_by_kind_and_tag(self) -> None:
        self.create()
        self.create(text=NOTE + chr(10) + "另一份技术笔记。", title="技术笔记-调度",
                    kind="tech", tags=["技术"])

        notes = self.client.get("/api/jobs", params={"kind": "note"}).json()["items"]
        self.assertEqual([item["kind"] for item in notes], ["note"])

        tagged = self.client.get("/api/jobs", params={"tag": "面经"}).json()["items"]
        self.assertEqual(len(tagged), 1)
        self.assertEqual(tagged[0]["title"], "面试复盘-某公司数据岗")

        empty = self.client.get("/api/jobs", params={"tag": "不存在的标签"}).json()["items"]
        self.assertEqual(empty, [])

    def test_tag_filter_does_not_match_substring(self) -> None:
        self.create(tags=["SQL"])
        self.create(text=NOTE + chr(10) + "补充。", title="SQL 优化笔记", tags=["SQL优化"])
        exact = self.client.get("/api/jobs", params={"tag": "SQL"}).json()["items"]
        self.assertEqual(len(exact), 1, "标签按整词匹配，SQL 不能命中 SQL优化")

    def test_edit_note_rebuilds_search_index(self) -> None:
        doc_id = self.create().json()["id"]
        patched = self.client.patch(f"/api/jobs/{doc_id}", json={
            "title": "面试复盘-改",
            "content_md": NOTE + chr(10) + "补充：还问了实时数仓的分层。",
            "tags": ["面经", "实时数仓"],
        }, headers=HEADER)
        self.assertEqual(patched.status_code, 200, patched.text)
        document = patched.json()["document"]
        self.assertEqual(document["title"], "面试复盘-改")
        self.assertEqual(document["tags"], ["面经", "实时数仓"])
        hit = self.client.get("/api/jobs", params={"q": "实时数仓"}).json()
        self.assertEqual(hit["total"], 1, "改完正文要能搜到新内容")
        detail = self.client.get(f"/api/jobs/{doc_id}").json()
        self.assertTrue(detail["chunks"])

    def test_edit_rejects_blank_content_and_empty_patch(self) -> None:
        doc_id = self.create().json()["id"]
        self.assertEqual(self.client.patch(f"/api/jobs/{doc_id}", json={"content_md": "   "},
                                           headers=HEADER).status_code, 422)
        self.assertEqual(self.client.patch(f"/api/jobs/{doc_id}", json={},
                                           headers=HEADER).status_code, 422)

    def test_other_account_cannot_edit(self) -> None:
        doc_id = self.create().json()["id"]
        self.current_user = {"id": "u-b", "username": "bob"}
        self.assertEqual(self.client.patch(f"/api/jobs/{doc_id}", json={"title": "改别人的"},
                                           headers=HEADER).status_code, 404)

    def test_public_pool_document_cannot_be_edited(self) -> None:
        with accounts.connection() as db:
            db.execute(
                "INSERT INTO documents(id,user_id,kind,source,source_key,title,content_md,"
                "visibility,fetched_at,created_at,updated_at)"
                " VALUES('pub-1',NULL,'job','feed','feed:pub-1','某公告','正文','public',0,0,0)")
        self.assertEqual(self.client.patch("/api/jobs/pub-1", json={"title": "改采集内容"},
                                           headers=HEADER).status_code, 404)

    def test_tags_are_cleaned_and_capped(self) -> None:
        body = self.create(tags=["  SQL  ", "SQL", "数仓", "", "x" * 40]).json()
        self.assertEqual(body["document"]["tags"], ["SQL", "数仓", "x" * 16])

    def test_examples_are_listable_for_reference(self) -> None:
        from engine.knowledge import examples

        with accounts.connection() as db:
            examples.seed(db)
        listed = self.client.get("/api/jobs", params={"kind": "example", "limit": 100}).json()
        self.assertGreaterEqual(listed["total"], 25, "范例应能在资料层列出，供示例库页面使用")
        self.assertTrue(all(item["kind"] == "example" for item in listed["items"]))


if __name__ == "__main__":
    unittest.main()
