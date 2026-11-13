"""社群卡片合约：投稿只有审核后可见、对外匿名、入库脱敏、举报与有帮助幂等。"""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from fastapi.testclient import TestClient  # noqa: E402

from core import accounts  # noqa: E402
from engine.community import redact  # noqa: E402
from main import app  # noqa: E402

HEADER = {"X-Requested-With": "XMLHttpRequest"}
BODY = "一面先问项目，追问了数据口径和调度失败怎么处理，建议把指标定义写清楚再讲实现。" * 2


class CommunityContract(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        patcher = patch.object(accounts, "DATABASE_PATH", Path(self.tmp.name) / "community.sqlite3")
        patcher.start()
        self.addCleanup(patcher.stop)

        with accounts.connection() as db:
            for user_id, name, guest in (
                ("u-alice", "alice", None),
                ("u-bob", "bob", None),
                ("u-admin", "admin", None),
                ("u-guest", "trial_one", 1.0),
            ):
                db.execute(
                    "INSERT INTO users(id,username,password_hash,created_at,guest_until) VALUES(?,?,?,0,?)",
                    (user_id, name, "pbkdf2_sha256$1$00$00", guest),
                )
            db.execute("INSERT INTO user_roles(user_id, role) VALUES('u-admin', 'admin')")

        self.current_user = {"id": "u-alice", "username": "alice"}
        previous = dict(app.dependency_overrides)
        app.dependency_overrides[accounts.require_user] = lambda: self.current_user
        self.addCleanup(lambda: (app.dependency_overrides.clear(), app.dependency_overrides.update(previous)))
        self.client = TestClient(app)

    def submit(self, **overrides):
        payload = {"kind": "interview", "title": "某公司数据岗一面", "body_md": BODY,
                   "company": "某科技", "role": "数据开发", "round": "一面", "tags": ["SQL"], **overrides}
        return self.client.post("/api/community/cards", json=payload, headers=HEADER)

    def as_user(self, user_id: str) -> None:
        names = {"u-bob": "bob", "u-admin": "admin", "u-guest": "trial_one", "u-alice": "alice"}
        # 真实 require_user 会按 guest_until 标记 guest，这里同步模拟
        self.current_user = {"id": user_id, "username": names[user_id],
                             **({"guest": True} if user_id == "u-guest" else {})}

    def approve(self, card_id: str, note: str = "") -> dict:
        self.as_user("u-admin")
        response = self.client.patch(f"/api/community/cards/{card_id}",
                                     json={"action": "approve", "note": note}, headers=HEADER)
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    # ---- 投稿与可见性 ----

    def test_pending_is_invisible_to_others_and_public_after_review(self) -> None:
        created = self.submit()
        self.assertEqual(created.status_code, 201, created.text)
        card_id = created.json()["id"]
        self.assertEqual(created.json()["status"], "pending")

        self.assertEqual(self.client.get("/api/community/cards").json()["items"], [])
        self.as_user("u-bob")
        self.assertEqual(self.client.get("/api/community/cards").json()["items"], [])
        self.assertEqual(self.client.get(f"/api/community/cards/{card_id}").status_code, 404,
                         "未审核内容对其他人不可见")

        self.approve(card_id)
        self.as_user("u-bob")
        items = self.client.get("/api/community/cards").json()["items"]
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["title"], "某公司数据岗一面")

    def test_payload_never_exposes_account_identity(self) -> None:
        card_id = self.submit().json()["id"]
        self.approve(card_id)
        self.as_user("u-bob")
        card = self.client.get(f"/api/community/cards/{card_id}").json()["card"]
        self.assertNotIn("user_id", card)
        self.assertNotIn("anon_id", card)
        self.assertTrue(card["author"], "应该给出匿名马甲名")
        self.assertNotIn("alice", str(card))

    def test_same_author_reuses_one_pseudonym(self) -> None:
        first = self.submit().json()["id"]
        second = self.submit(title="同一个人的第二条", body_md=BODY).json()["id"]
        self.approve(first)
        self.approve(second)
        self.as_user("u-bob")
        items = self.client.get("/api/community/cards").json()["items"]
        self.assertEqual(len({item["author"] for item in items}), 1)

    # ---- 投稿来源与校验 ----

    def test_can_submit_from_own_document_only(self) -> None:
        created = self.client.post("/api/jobs/import", json={
            "text": "数据开发工程师\n岗位职责\n负责离线数仓建设与指标口径维护。",
            "title": "数据开发工程师", "parse": False,
        }, headers=HEADER).json()
        response = self.submit(title="", body_md="", company="", role="", doc_id=created["id"])
        self.assertEqual(response.status_code, 201, response.text)

        self.as_user("u-bob")
        doc = self.client.post("/api/jobs/import", json={
            "text": "前端工程师\n岗位职责\n负责页面开发。", "title": "前端工程师", "parse": False,
        }, headers=HEADER).json()
        self.as_user("u-alice")
        denied = self.submit(doc_id=doc["id"])
        self.assertEqual(denied.status_code, 422, "别人的资料不能当投稿来源")
        self.assertIn("重新选择", denied.json()["detail"])
        # 提示要能指导用户（普通用户看到"资料不存在或无权使用"会一头雾水）
        self.assertIn("留空直接写正文", denied.json()["detail"])

    def test_unknown_doc_id_is_a_form_error_not_a_missing_page(self) -> None:
        response = self.submit(doc_id="not-a-real-id")
        self.assertEqual(response.status_code, 422)
        self.assertIn("选中的资料不存在", response.json()["detail"])

    def test_submit_without_doc_id_never_touches_documents(self) -> None:
        payload = {"kind": "jd_review", "title": "JD 评价：要求虚高",
                   "body_md": "这个 JD 写着 3 年经验却要求全栈加算法，薪资区间也不透明。", "tags": []}
        response = self.client.post("/api/community/cards", json=payload, headers=HEADER)
        self.assertEqual(response.status_code, 201, response.text)
        self.assertEqual(response.json()["status"], "pending")

    def test_unknown_kind_filter_is_rejected(self) -> None:
        self.assertEqual(self.client.get("/api/community/cards", params={"kind": "rumor"}).status_code, 422)

    def test_mine_filter_only_lists_own_documents(self) -> None:
        own = self.client.post("/api/jobs/import", json={
            "text": chr(10).join(["数据开发工程师", "岗位职责", "负责离线数仓建设与指标口径维护。"]),
            "title": "我录入的岗位", "parse": False,
        }, headers=HEADER).json()["id"]
        self.as_user("u-bob")
        self.client.post("/api/jobs/import", json={
            "text": chr(10).join(["前端工程师", "岗位职责", "负责页面开发与组件维护。"]),
            "title": "别人录入的岗位", "parse": False,
        }, headers=HEADER).json()

        self.as_user("u-alice")
        mine = self.client.get("/api/jobs", params={"mine": True}).json()["items"]
        self.assertEqual([item["id"] for item in mine], [own])
        self.assertNotIn("别人录入的岗位", [item["title"] for item in mine])

    def test_short_body_and_bad_kind_are_rejected(self) -> None:
        self.assertEqual(self.submit(body_md="太短").status_code, 422)
        self.assertEqual(self.submit(kind="rumor").status_code, 422)

    def test_guest_cannot_submit_or_report(self) -> None:
        self.as_user("u-guest")
        self.assertEqual(self.submit().status_code, 403)
        self.assertEqual(self.client.get("/api/community/mine").status_code, 403)

    # ---- 审核 ----

    def test_reject_requires_note_and_hides_content(self) -> None:
        card_id = self.submit().json()["id"]
        self.as_user("u-admin")
        empty = self.client.patch(f"/api/community/cards/{card_id}",
                                  json={"action": "reject", "note": " "}, headers=HEADER)
        self.assertEqual(empty.status_code, 422)

        rejected = self.client.patch(f"/api/community/cards/{card_id}",
                                     json={"action": "reject", "note": "缺少岗位和轮次信息"}, headers=HEADER)
        self.assertEqual(rejected.status_code, 200, rejected.text)
        self.assertEqual(rejected.json()["status"], "rejected")

        self.as_user("u-alice")
        mine = self.client.get("/api/community/mine").json()["items"]
        self.assertEqual(mine[0]["status"], "rejected")
        self.assertEqual(mine[0]["review_note"], "缺少岗位和轮次信息")
        self.as_user("u-bob")
        self.assertEqual(self.client.get("/api/community/cards").json()["items"], [])

    def test_review_requires_admin(self) -> None:
        card_id = self.submit().json()["id"]
        self.assertEqual(self.client.get("/api/community/review").status_code, 403)
        self.assertEqual(self.client.patch(f"/api/community/cards/{card_id}",
                                           json={"action": "approve", "note": ""},
                                           headers=HEADER).status_code, 403)

    def test_review_queue_counts(self) -> None:
        card_id = self.submit().json()["id"]
        self.as_user("u-admin")
        queue = self.client.get("/api/community/review").json()
        self.assertEqual([item["id"] for item in queue["items"]], [card_id])
        self.assertEqual(queue["counts"]["pending"], 1)
        self.approve(card_id)
        queue = self.client.get("/api/community/review").json()
        self.assertEqual(queue["items"], [])
        self.assertEqual(queue["counts"]["public"], 1)

    # ---- 互动 ----

    def test_helpful_can_be_toggled_off(self) -> None:
        """点一次标记有帮助，再点一次撤回，计数跟着变回去。"""
        card_id = self.submit().json()["id"]
        self.approve(card_id)
        self.as_user("u-bob")
        first = self.client.post(f"/api/community/cards/{card_id}/helpful", headers=HEADER).json()
        self.assertTrue(first["helpful"])
        self.assertEqual(first["helpful_count"], 1)
        second = self.client.post(f"/api/community/cards/{card_id}/helpful", headers=HEADER).json()
        self.assertFalse(second["helpful"])
        self.assertEqual(second["helpful_count"], 0, "撤回后计数要减回去")
        third = self.client.post(f"/api/community/cards/{card_id}/helpful", headers=HEADER).json()
        self.assertEqual(third["helpful_count"], 1)

    def test_viewer_helpful_state_survives_reload(self) -> None:
        card_id = self.submit().json()["id"]
        self.approve(card_id)
        self.as_user("u-bob")
        self.client.post(f"/api/community/cards/{card_id}/helpful", headers=HEADER)
        card = self.client.get(f"/api/community/cards/{card_id}").json()["card"]
        self.assertTrue(card["viewer_helpful"], "刷新后按钮要显示已标记")
        self.as_user("u-admin")
        other = self.client.get(f"/api/community/cards/{card_id}").json()["card"]
        self.assertFalse(other["viewer_helpful"], "别人的标记不算我的")

    def test_reports_hide_card_after_threshold(self) -> None:
        card_id = self.submit().json()["id"]
        self.approve(card_id)
        for user_id in ("u-bob", "u-alice", "u-admin"):
            self.as_user(user_id)
            self.client.post(f"/api/community/cards/{card_id}/report",
                             json={"reason": "内容包含联系方式"}, headers=HEADER)
        self.as_user("u-bob")
        self.assertEqual(self.client.get("/api/community/cards").json()["items"], [],
                         "累计举报达到阈值要先撤下待审")
        self.as_user("u-admin")
        queue = self.client.get("/api/community/review").json()
        self.assertEqual(queue["items"][0]["id"], card_id)
        self.assertIn("举报", queue["items"][0]["review_note"])

    def test_same_user_reports_once(self) -> None:
        card_id = self.submit().json()["id"]
        self.approve(card_id)
        self.as_user("u-bob")
        first = self.client.post(f"/api/community/cards/{card_id}/report",
                                 json={"reason": "疑似广告"}, headers=HEADER).json()
        second = self.client.post(f"/api/community/cards/{card_id}/report",
                                  json={"reason": "疑似广告"}, headers=HEADER).json()
        self.assertEqual(first["report_count"], 1)
        self.assertTrue(second["already"])
        self.assertEqual(second["report_count"], 1)

    # ---- 撤回 ----

    def test_author_can_withdraw_but_others_cannot(self) -> None:
        card_id = self.submit().json()["id"]
        self.as_user("u-bob")
        self.assertEqual(self.client.delete(f"/api/community/cards/{card_id}", headers=HEADER).status_code, 404)
        self.as_user("u-alice")
        self.assertEqual(self.client.delete(f"/api/community/cards/{card_id}", headers=HEADER).status_code, 200)
        mine = self.client.get("/api/community/mine").json()["items"]
        self.assertEqual(mine, [])

    # ---- 脱敏 ----

    def test_contact_details_are_masked_before_storage(self) -> None:
        body = BODY + "想聊的加微信 abc_123456 或手机 138-1234-5678，邮箱 me@example.com"
        card_id = self.submit(title="一面复盘 13812345678", body_md=body).json()["id"]
        self.approve(card_id)
        self.as_user("u-bob")
        card = self.client.get(f"/api/community/cards/{card_id}").json()["card"]
        self.assertNotIn("138-1234-5678", card["body_md"])
        self.assertNotIn("me@example.com", card["body_md"])
        self.assertNotIn("abc_123456", card["body_md"])
        self.assertNotIn("13812345678", card["title"])
        self.assertIn(redact.PHONE, card["body_md"])
        self.assertEqual(card["company"], "某科技", "公司名是内容，不该被遮")


class CommunityGovernance(unittest.TestCase):
    """举报处理、已发布下架、评论：管理员要真的能看到并处置。"""

    setUp = CommunityContract.setUp
    submit = CommunityContract.submit
    as_user = CommunityContract.as_user
    approve = CommunityContract.approve

    def test_report_reaches_admin_queue_with_reason(self) -> None:
        card_id = self.submit().json()["id"]
        self.approve(card_id)
        self.as_user("u-bob")
        self.client.post(f"/api/community/cards/{card_id}/report",
                         json={"reason": "内容包含联系方式"}, headers=HEADER)

        self.as_user("u-alice")
        self.assertEqual(self.client.get("/api/community/reports").status_code, 403)

        self.as_user("u-admin")
        queue = self.client.get("/api/community/reports").json()["items"]
        self.assertEqual(len(queue), 1)
        self.assertEqual(queue[0]["card_id"], card_id)
        self.assertEqual(queue[0]["reasons"][0]["reason"], "内容包含联系方式")
        self.assertEqual(queue[0]["report_count"], 1)

    def test_admin_resolves_reports_without_deleting_content(self) -> None:
        card_id = self.submit().json()["id"]
        self.approve(card_id)
        self.as_user("u-bob")
        self.client.post(f"/api/community/cards/{card_id}/report",
                         json={"reason": "疑似广告"}, headers=HEADER)
        self.as_user("u-admin")
        resolved = self.client.post(f"/api/community/reports/{card_id}/resolve",
                                    json={"note": "人工核对为正常"}, headers=HEADER)
        self.assertEqual(resolved.status_code, 200, resolved.text)
        self.assertEqual(resolved.json()["resolved"], 1)
        self.assertEqual(self.client.get("/api/community/reports").json()["items"], [])
        # 内容仍在
        self.as_user("u-bob")
        self.assertEqual(len(self.client.get("/api/community/cards").json()["items"]), 1)

    def test_admin_can_unpublish_published_card(self) -> None:
        card_id = self.submit().json()["id"]
        self.approve(card_id)
        self.as_user("u-admin")
        result = self.client.patch(f"/api/community/cards/{card_id}",
                                   json={"action": "unpublish", "note": "内容与主题不符"},
                                   headers=HEADER)
        self.assertEqual(result.status_code, 200, result.text)
        self.assertEqual(result.json()["status"], "rejected")
        self.assertEqual(result.json()["review_note"], "内容与主题不符")

        self.as_user("u-bob")
        self.assertEqual(self.client.get("/api/community/cards").json()["items"], [])
        self.as_user("u-alice")
        mine = self.client.get("/api/community/mine").json()["items"]
        self.assertEqual(mine[0]["status"], "rejected")
        self.assertEqual(mine[0]["review_note"], "内容与主题不符")

    def test_author_can_withdraw_published_card(self) -> None:
        card_id = self.submit().json()["id"]
        self.approve(card_id)
        self.as_user("u-alice")
        self.assertEqual(self.client.delete(f"/api/community/cards/{card_id}", headers=HEADER).status_code, 200)
        self.as_user("u-bob")
        self.assertEqual(self.client.get("/api/community/cards").json()["items"], [])

    # ---- 评论 ----

    def test_comment_on_public_card_and_visible_to_others(self) -> None:
        card_id = self.submit().json()["id"]
        self.approve(card_id)
        self.as_user("u-bob")
        created = self.client.post(f"/api/community/cards/{card_id}/comments",
                                   json={"body": "补充一个细节：二面才问算法。"}, headers=HEADER)
        self.assertEqual(created.status_code, 201, created.text)

        self.as_user("u-alice")
        items = self.client.get(f"/api/community/cards/{card_id}/comments").json()["items"]
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["body"], "补充一个细节：二面才问算法。")
        self.assertNotIn("user_id", items[0])
        card = self.client.get(f"/api/community/cards/{card_id}").json()["card"]
        self.assertEqual(card["comment_count"], 1)

    def test_comment_requires_public_card_and_redaction(self) -> None:
        card_id = self.submit().json()["id"]          # 仍是 pending
        self.as_user("u-bob")
        denied = self.client.post(f"/api/community/cards/{card_id}/comments",
                                  json={"body": "还没审核也能评论吗"}, headers=HEADER)
        self.assertEqual(denied.status_code, 404)

        self.approve(card_id)
        self.as_user("u-bob")
        created = self.client.post(f"/api/community/cards/{card_id}/comments",
                                   json={"body": "想交流加微信 bob_2026 或手机 13900001111"},
                                   headers=HEADER).json()
        self.assertNotIn("bob_2026", created["body"])
        self.assertNotIn("13900001111", created["body"])

    def test_guest_cannot_comment(self) -> None:
        card_id = self.submit().json()["id"]
        self.approve(card_id)
        self.as_user("u-guest")
        self.assertEqual(self.client.post(f"/api/community/cards/{card_id}/comments",
                                          json={"body": "试用账号的评论"}, headers=HEADER).status_code, 403)

    def test_comment_author_and_admin_can_delete(self) -> None:
        card_id = self.submit().json()["id"]
        self.approve(card_id)
        self.as_user("u-bob")
        comment_id = self.client.post(f"/api/community/cards/{card_id}/comments",
                                      json={"body": "先占个位置"}, headers=HEADER).json()["id"]
        self.as_user("u-alice")
        self.assertEqual(self.client.delete(f"/api/community/comments/{comment_id}",
                                            headers=HEADER).status_code, 404)
        self.as_user("u-bob")
        self.assertEqual(self.client.delete(f"/api/community/comments/{comment_id}",
                                            headers=HEADER).status_code, 200)

    def test_reported_comment_is_hidden_and_queue_shows_it(self) -> None:
        card_id = self.submit().json()["id"]
        self.approve(card_id)
        self.as_user("u-bob")
        comment_id = self.client.post(f"/api/community/cards/{card_id}/comments",
                                      json={"body": "这是广告：加我私聊"}, headers=HEADER).json()["id"]
        for user_id in ("u-alice", "u-admin"):
            self.as_user(user_id)
            result = self.client.post(f"/api/community/comments/{comment_id}/report",
                                      json={"reason": "广告"}, headers=HEADER).json()
        self.assertTrue(result["hidden"], "累计举报达到阈值要撤下")
        self.as_user("u-alice")
        self.assertEqual(self.client.get(f"/api/community/cards/{card_id}/comments").json()["items"], [])

        self.as_user("u-admin")
        queue = self.client.get("/api/community/comments/queue").json()["items"]
        self.assertEqual([item["id"] for item in queue], [comment_id])
        restored = self.client.post(f"/api/community/comments/{comment_id}/restore", headers=HEADER)
        self.assertEqual(restored.status_code, 200)
        self.as_user("u-alice")
        self.assertEqual(len(self.client.get(f"/api/community/cards/{card_id}/comments").json()["items"]), 1)


if __name__ == "__main__":
    unittest.main()


class CommunityCommentReportDedupe(unittest.TestCase):
    """同一个人反复举报不能把评论顶掉。"""

    setUp = CommunityContract.setUp
    submit = CommunityContract.submit
    as_user = CommunityContract.as_user
    approve = CommunityContract.approve

    def test_same_user_reports_comment_once(self) -> None:
        card_id = self.submit().json()["id"]
        self.approve(card_id)
        self.as_user("u-bob")
        comment_id = self.client.post(f"/api/community/cards/{card_id}/comments",
                                      json={"body": "一段普通评论"}, headers=HEADER).json()["id"]
        self.as_user("u-alice")
        first = self.client.post(f"/api/community/comments/{comment_id}/report",
                                 json={"reason": "广告"}, headers=HEADER).json()
        second = self.client.post(f"/api/community/comments/{comment_id}/report",
                                  json={"reason": "广告"}, headers=HEADER).json()
        self.assertEqual(first["report_count"], 1)
        self.assertTrue(second["already"])
        self.assertEqual(second["report_count"], 1)
        self.assertFalse(second["hidden"], "一个人刷两次不能把评论撤下")
        self.assertEqual(len(self.client.get(f"/api/community/cards/{card_id}/comments").json()["items"]), 1)


class CommunityRevision(unittest.TestCase):
    """被退回后要能改、能重新提交；已发布内容一改就回到待审。"""

    setUp = CommunityContract.setUp
    submit = CommunityContract.submit
    as_user = CommunityContract.as_user
    approve = CommunityContract.approve

    def reject(self, card_id: str, note: str = "信息不足") -> None:
        self.as_user("u-admin")
        response = self.client.patch(f"/api/community/cards/{card_id}",
                                     json={"action": "reject", "note": note}, headers=HEADER)
        self.assertEqual(response.status_code, 200, response.text)

    def test_author_edits_rejected_card_and_it_returns_to_review(self) -> None:
        card_id = self.submit().json()["id"]
        self.reject(card_id)
        self.as_user("u-alice")
        revised = self.client.put(f"/api/community/cards/{card_id}", json={
            "title": "某公司数据岗一面（补充版）",
            "body_md": "补充了二面的细节：问了数仓分层和调度失败补偿，还让我手写窗口函数。",
            "company": "某科技", "role": "数据开发", "round": "一面", "tags": ["SQL", "数仓"],
        }, headers=HEADER)
        self.assertEqual(revised.status_code, 200, revised.text)
        self.assertEqual(revised.json()["status"], "pending")

        mine = self.client.get("/api/community/mine").json()["items"][0]
        self.assertEqual(mine["status"], "pending")
        self.assertEqual(mine["review_note"], "", "重新提交后清掉旧退回原因")
        self.assertIn("补充版", mine["title"])

        self.as_user("u-admin")
        queue = self.client.get("/api/community/review").json()["items"]
        self.assertEqual([item["id"] for item in queue], [card_id])

    def test_edit_is_owner_only_and_redacted(self) -> None:
        card_id = self.submit().json()["id"]
        self.as_user("u-bob")
        denied = self.client.put(f"/api/community/cards/{card_id}",
                                 json={"title": "改别人的"}, headers=HEADER)
        self.assertEqual(denied.status_code, 404)

        self.as_user("u-alice")
        self.client.put(f"/api/community/cards/{card_id}", json={
            "title": "留下联系方式 13812345678",
            "body_md": "补充说明：我的邮箱 me@example.com，正文要够长才能通过校验。",
        }, headers=HEADER)
        mine = self.client.get("/api/community/mine").json()["items"][0]
        self.assertNotIn("13812345678", mine["title"])
        self.assertNotIn("me@example.com", mine["body_md"])

    def test_editing_public_card_unpublishes_it(self) -> None:
        card_id = self.submit().json()["id"]
        self.approve(card_id)
        self.as_user("u-alice")
        revised = self.client.put(f"/api/community/cards/{card_id}", json={
            "body_md": "改了内容之后必须重新审核：补充二面问了窗口函数与调度补偿的实现细节。",
        }, headers=HEADER)
        self.assertEqual(revised.json()["status"], "pending")
        self.as_user("u-bob")
        self.assertEqual(self.client.get("/api/community/cards").json()["items"], [],
                         "改过的内容不能继续留在公开列表里")

    def test_resubmit_without_edit(self) -> None:
        card_id = self.submit().json()["id"]
        self.reject(card_id)
        self.as_user("u-alice")
        result = self.client.post(f"/api/community/cards/{card_id}/resubmit", headers=HEADER)
        self.assertEqual(result.status_code, 200, result.text)
        self.assertEqual(result.json()["status"], "pending")
        # 已发布的不能走“重新提交”，只能改
        self.approve(card_id)
        self.as_user("u-alice")
        self.assertEqual(self.client.post(f"/api/community/cards/{card_id}/resubmit",
                                          headers=HEADER).status_code, 422)

    def test_guest_and_short_body_are_rejected(self) -> None:
        card_id = self.submit().json()["id"]
        self.reject(card_id)
        self.as_user("u-guest")
        self.assertEqual(self.client.put(f"/api/community/cards/{card_id}",
                                         json={"title": "试用账号改"}, headers=HEADER).status_code, 403)
        self.as_user("u-alice")
        self.assertEqual(self.client.put(f"/api/community/cards/{card_id}",
                                         json={"body_md": "太短"}, headers=HEADER).status_code, 422)


class CommunityRevisionSemantics(unittest.TestCase):
    """内容改了就是新一版：旧帮助票作废、旧评论归到上一版、旧举报结案。"""

    setUp = CommunityContract.setUp
    submit = CommunityContract.submit
    as_user = CommunityContract.as_user
    approve = CommunityContract.approve

    def test_revision_resets_votes_and_tags_old_comments(self) -> None:
        card_id = self.submit().json()["id"]
        self.approve(card_id)

        # 一位读者点赞 + 留言
        self.as_user("u-bob")
        self.client.post(f"/api/community/cards/{card_id}/helpful", headers=HEADER)
        self.client.post(f"/api/community/cards/{card_id}/comments",
                         json={"body": "这一面的数仓分层问题很典型"}, headers=HEADER)
        old = self.client.get(f"/api/community/cards/{card_id}").json()["card"]
        self.assertEqual((old["helpful_count"], old["comment_count"], old["revision"]), (1, 1, 1))

        # 作者换内容重新提交并再次通过
        self.as_user("u-alice")
        revised = self.client.put(f"/api/community/cards/{card_id}", json={
            "body_md": "改版后换成二面内容：手写窗口函数、解释调度失败补偿，附录 SQL 思路。",
        }, headers=HEADER)
        self.assertEqual(revised.json()["revision"], 2)
        self.approve(card_id)

        self.as_user("u-bob")
        card = self.client.get(f"/api/community/cards/{card_id}").json()["card"]
        self.assertEqual(card["revision"], 2)
        self.assertEqual(card["helpful_count"], 0, "上一版的帮助票不能算到新内容头上")
        self.assertFalse(card["viewer_helpful"])
        self.assertEqual(card["comment_count"], 0, "旧评论不计入当前版本的评论数")

        comments = self.client.get(f"/api/community/cards/{card_id}/comments").json()["items"]
        self.assertEqual(len(comments), 1, "旧评论仍保留，供读者回看")
        self.assertTrue(comments[0]["outdated"], "旧评论必须标成上一版")
        self.assertEqual(comments[0]["revision"], 1)

    def test_revision_resolves_old_reports(self) -> None:
        card_id = self.submit().json()["id"]
        self.approve(card_id)
        self.as_user("u-bob")
        self.client.post(f"/api/community/cards/{card_id}/report",
                         json={"reason": "内容与标题不符"}, headers=HEADER)
        self.as_user("u-admin")
        self.assertEqual(len(self.client.get("/api/community/reports").json()["items"]), 1)

        self.as_user("u-alice")
        self.client.put(f"/api/community/cards/{card_id}", json={
            "title": "数据岗二面：窗口函数与调度补偿",
        }, headers=HEADER)
        self.approve(card_id)

        self.as_user("u-admin")
        self.assertEqual(self.client.get("/api/community/reports").json()["items"], [],
                         "内容已更新，旧举报应结案")
        self.as_user("u-bob")
        card = self.client.get(f"/api/community/cards/{card_id}").json()["card"]
        self.assertEqual(card["report_count"], 0)

    def test_resubmit_without_edit_keeps_votes_and_comments(self) -> None:
        card_id = self.submit().json()["id"]
        self.approve(card_id)
        self.as_user("u-bob")
        self.client.post(f"/api/community/cards/{card_id}/helpful", headers=HEADER)
        self.client.post(f"/api/community/cards/{card_id}/comments",
                         json={"body": "同一版内容下的讨论"}, headers=HEADER)

        self.as_user("u-admin")
        self.client.patch(f"/api/community/cards/{card_id}",
                          json={"action": "reject", "note": "补充轮次信息"}, headers=HEADER)
        self.as_user("u-alice")
        result = self.client.post(f"/api/community/cards/{card_id}/resubmit", headers=HEADER)
        self.assertEqual(result.json()["status"], "pending")
        self.approve(card_id)

        self.as_user("u-bob")
        card = self.client.get(f"/api/community/cards/{card_id}").json()["card"]
        self.assertEqual(card["revision"], 1, "内容没改，版本不变")
        self.assertEqual(card["helpful_count"], 1)
        self.assertEqual(card["comment_count"], 1)


class CommunityRevisionHistory(unittest.TestCase):
    """历史版本：作者与管理员可查，其他人不可见，内容按版本留存。"""

    setUp = CommunityContract.setUp
    submit = CommunityContract.submit
    as_user = CommunityContract.as_user
    approve = CommunityContract.approve

    def revise(self, card_id: str, body: str) -> None:
        self.as_user("u-alice")
        response = self.client.put(f"/api/community/cards/{card_id}", json={"body_md": body}, headers=HEADER)
        self.assertEqual(response.status_code, 200, response.text)

    def test_history_keeps_old_body_and_is_owner_only(self) -> None:
        card_id = self.submit().json()["id"]
        self.revise(card_id, "第二版正文：补充了二面的窗口函数题与调度补偿思路，其余保持原样。")
        self.revise(card_id, "第三版正文：再去掉一面内容，只留二面与手写 LRU 的追问细节。")

        history = self.client.get(f"/api/community/cards/{card_id}/revisions").json()
        self.assertEqual([item["revision"] for item in history["items"]], [3, 2, 1])
        self.assertNotIn("body_md", history["items"][0], "列表只给元信息，正文按版本单独取")

        first = self.client.get(f"/api/community/cards/{card_id}/revisions/1").json()["revision"]
        self.assertEqual(first["title"], "某公司数据岗一面")
        self.assertIn("一面先问项目", first["body_md"])
        third = self.client.get(f"/api/community/cards/{card_id}/revisions/3").json()["revision"]
        self.assertIn("手写 LRU", third["body_md"])

        self.as_user("u-bob")
        self.assertEqual(self.client.get(f"/api/community/cards/{card_id}/revisions").status_code, 404)
        self.assertEqual(self.client.get(f"/api/community/cards/{card_id}/revisions/1").status_code, 404)

        self.as_user("u-admin")
        items = self.client.get(f"/api/community/cards/{card_id}/revisions").json()["items"]
        self.assertEqual(len(items), 3, "管理员处理举报时需要能看历史内容")

    def test_history_survives_unpublish_and_resubmit_does_not_add_version(self) -> None:
        card_id = self.submit().json()["id"]
        self.approve(card_id)
        self.as_user("u-admin")
        self.client.patch(f"/api/community/cards/{card_id}",
                          json={"action": "unpublish", "note": "需要补充信息"}, headers=HEADER)
        self.as_user("u-alice")
        self.client.post(f"/api/community/cards/{card_id}/resubmit", headers=HEADER)
        history = self.client.get(f"/api/community/cards/{card_id}/revisions").json()["items"]
        self.assertEqual([item["revision"] for item in history], [1], "重新提交不算新版本")

    def test_legacy_card_without_snapshot_backfills_current(self) -> None:
        card_id = self.submit().json()["id"]
        with accounts.connection() as db:
            db.execute("DELETE FROM card_revisions WHERE card_id = ?", (card_id,))
        history = self.client.get(f"/api/community/cards/{card_id}/revisions").json()["items"]
        self.assertEqual(len(history), 1, "老卡片至少能看到当前这一版")


class CommunitySourceDocumentScope(unittest.TestCase):
    """投稿只能引用自己录入的资料；公共岗位池的公告不能当正文来源。"""

    setUp = CommunityContract.setUp
    submit = CommunityContract.submit

    def test_public_pool_document_is_rejected_as_source(self) -> None:
        with accounts.connection() as db:
            db.execute(
                "INSERT INTO documents(id, user_id, kind, source, source_key, title, content_md,"
                " visibility, fetched_at, created_at, updated_at)"
                " VALUES(?,NULL,'job','feed',?,'某市事业单位招聘公告',?,'public',0,0,0)",
                ("doc-public-x", "feed:doc-public-x", "某市事业单位公开招聘公告，岗位职责详见正文。" * 2),
            )
        response = self.submit(title="", body_md="", company="", role="", doc_id="doc-public-x")
        self.assertEqual(response.status_code, 422)
        self.assertIn("留空直接写正文", response.json()["detail"])


class CommunityReprotSla(unittest.TestCase):
    """举报处置时效：待处理数量与等待时长可读，且不含举报人/正文。"""

    setUp = CommunityContract.setUp
    submit = CommunityContract.submit
    as_user = CommunityContract.as_user
    approve = CommunityContract.approve

    def test_sla_reports_backlog_and_median(self) -> None:
        import time as _time

        card_id = self.submit().json()["id"]
        self.approve(card_id)
        self.as_user("u-bob")
        self.client.post(f"/api/community/cards/{card_id}/report",
                         json={"reason": "内容包含联系方式"}, headers=HEADER)

        self.as_user("u-admin")
        sla = self.client.get("/api/community/reports").json()["sla"]
        self.assertEqual(sla["open_cards"], 1)
        self.assertEqual(sla["over_24h"], 0)
        self.assertLess(sla["oldest_open_hours"], 1)

        # 把举报时间往前挪 30 小时，检查"超过 24 小时"能被统计出来
        with accounts.connection() as db:
            db.execute("UPDATE card_reports SET created_at = ?", (_time.time() - 30 * 3600,))
        sla = self.client.get("/api/community/reports").json()["sla"]
        self.assertEqual(sla["over_24h"], 1)
        self.assertGreaterEqual(sla["oldest_open_hours"], 29)

        self.client.post(f"/api/community/reports/{card_id}/resolve",
                         json={"note": "人工核对后保留"}, headers=HEADER)
        sla = self.client.get("/api/community/reports").json()["sla"]
        self.assertEqual(sla["open_cards"], 0)
        self.assertEqual(sla["handled_recent"], 1)
        self.assertGreaterEqual(sla["median_handle_hours"], 29, "处理耗时要按首次举报时间算")

    def test_sla_payload_has_no_personal_data(self) -> None:
        card_id = self.submit().json()["id"]
        self.approve(card_id)
        self.as_user("u-bob")
        self.client.post(f"/api/community/cards/{card_id}/report",
                         json={"reason": "bob 的私人理由 13800001111"}, headers=HEADER)
        self.as_user("u-admin")
        sla = self.client.get("/api/community/reports", params={"only_open": False}).text
        self.assertNotIn("13800001111", sla.split('"sla"')[-1], "时效汇总里不能夹带举报原因")
