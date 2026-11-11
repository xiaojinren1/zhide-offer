"""卡片下的匿名评论。

取舍：评论**即时公开**（不再走一遍审核队列），因为"看面经问一句"如果还要等审核就没人用了。
代价用三条兜底控制：

- 入库前脱敏，和卡片同一套规则；
- 只能评论已公开的卡片，试用账号不能评论；
- 被举报累计到阈值先撤下（`status = 'rejected'`）进管理员队列，管理员可恢复或删除，作者也可自删。

只有 `public` 评论出现在列表里；自己的评论即使被撤下，本人仍能看到状态。
"""
from __future__ import annotations

import time
from typing import Any
from uuid import uuid4

from .cards import MAX_COMMENT, _clip, _now, ensure_anon_id
from .redact import redact

COMMENT_HIDE_THRESHOLD = 2


def _comment_dict(row: Any, anon_name: str, *, viewer_id: str | None, admin: bool,
                  current_revision: int | None = None) -> dict[str, Any]:
    """对外形态：不含 user_id / anon_id，只给马甲名、是否为本人、属于哪一版内容。"""
    return {
        "id": row["id"],
        "card_id": row["card_id"],
        "body": row["body"],
        "author": anon_name,
        "status": row["status"],
        "report_count": row["report_count"],
        "revision": row["revision"],
        "outdated": current_revision is not None and row["revision"] != current_revision,
        "created_at": row["created_at"],
        "mine": bool(viewer_id) and row["user_id"] == viewer_id,
        "can_manage": admin,
    }


def _names(db, rows: list[Any]) -> dict[str, str]:
    anon_ids = {row["anon_id"] for row in rows}
    marks = ",".join("?" for _ in anon_ids)
    return {
        item["id"]: item["display_name"]
        for item in db.execute(
            f"SELECT id, display_name FROM anon_identities WHERE id IN ({marks})", tuple(anon_ids)
        ).fetchall()
    }


def list_comments(db, card_id: str, *, viewer_id: str | None = None,
                  admin: bool = False) -> list[dict[str, Any]]:
    """公开的评论都给；被撤下的只给本人和管理员。

    卡片被作者改过内容时，旧版本的评论仍返回，但标 `outdated=True`，
    由前端折叠成“上一版内容下的评论”，不能当成对新内容的反馈。
    """
    card = db.execute("SELECT revision FROM public_cards WHERE id = ?", (card_id,)).fetchone()
    revision = int(card["revision"]) if card is not None else None
    rows = db.execute(
        "SELECT * FROM card_comments WHERE card_id = ?"
        " AND (status = 'public' OR user_id = ? OR ?)"
        " ORDER BY created_at ASC LIMIT 200",
        (card_id, viewer_id or "", 1 if admin else 0),
    ).fetchall()
    if not rows:
        return []
    names = _names(db, rows)
    return [
        _comment_dict(row, names.get(row["anon_id"], "匿名"), viewer_id=viewer_id, admin=admin,
                      current_revision=revision)
        for row in rows
    ]


def add_comment(db, card_id: str, user_id: str, body: object) -> dict[str, Any]:
    """评论入库：卡片必须是已公开的，正文脱敏后即时公开。"""
    card = db.execute("SELECT status, revision FROM public_cards WHERE id = ?", (card_id,)).fetchone()
    if card is None or card["status"] != "public":
        raise LookupError("卡片不存在或尚未通过审核")
    clean = _clip(redact(body), MAX_COMMENT)
    if not clean:
        raise ValueError("请填写评论内容")
    anon_id = ensure_anon_id(db, user_id)
    comment_id = uuid4().hex
    now = _now()
    db.execute(
        "INSERT INTO card_comments(id, card_id, user_id, anon_id, body, status, revision, created_at)"
        " VALUES (?,?,?,?,?,'public',?,?)",
        (comment_id, card_id, user_id, anon_id, clean, int(card["revision"]), now),
    )
    return {"id": comment_id, "status": "public", "body": clean, "created_at": now}


def report_comment(db, comment_id: str, user_id: str, reason: object) -> dict[str, Any]:
    """评论举报：一人一次；累计到阈值先撤下，进管理员队列等人工处理。"""
    clean_reason = _clip(redact(reason), 200)
    if not clean_reason:
        raise ValueError("请填写举报原因")
    row = db.execute("SELECT status FROM card_comments WHERE id = ?", (comment_id,)).fetchone()
    if row is None:
        raise LookupError("评论不存在")
    inserted = db.execute(
        "INSERT OR IGNORE INTO comment_reports(comment_id, user_id, reason, created_at)"
        " VALUES (?,?,?,?)",
        (comment_id, user_id, clean_reason, _now()),
    ).rowcount
    if not inserted:
        count = db.execute(
            "SELECT report_count FROM card_comments WHERE id = ?", (comment_id,)
        ).fetchone()[0]
        return {"report_count": count, "hidden": False, "already": True}
    db.execute("UPDATE card_comments SET report_count = report_count + 1 WHERE id = ?", (comment_id,))
    count = db.execute(
        "SELECT report_count FROM card_comments WHERE id = ?", (comment_id,)
    ).fetchone()[0]
    hidden = False
    if count >= COMMENT_HIDE_THRESHOLD and row["status"] == "public":
        db.execute("UPDATE card_comments SET status = 'rejected' WHERE id = ?", (comment_id,))
        hidden = True
    return {"report_count": count, "hidden": hidden, "already": False}


def delete_comment(db, comment_id: str, *, user_id: str, admin: bool = False) -> bool:
    row = db.execute("SELECT user_id FROM card_comments WHERE id = ?", (comment_id,)).fetchone()
    if row is None:
        return False
    if not admin and row["user_id"] != user_id:
        return False
    db.execute("DELETE FROM card_comments WHERE id = ?", (comment_id,))
    return True


def restore_comment(db, comment_id: str) -> bool:
    """管理员复核后恢复评论（清掉举报计数）。"""
    changed = db.execute(
        "UPDATE card_comments SET status = 'public', report_count = 0 WHERE id = ?", (comment_id,)
    ).rowcount
    return bool(changed)


def comment_queue(db, *, limit: int = 30) -> list[dict[str, Any]]:
    """管理员：被撤下的评论（含举报次数）。"""
    rows = db.execute(
        "SELECT * FROM card_comments WHERE status != 'public' ORDER BY id DESC LIMIT ?",
        (max(1, min(limit, 100)),),
    ).fetchall()
    if not rows:
        return []
    names = _names(db, rows)
    revisions = {
        item["id"]: int(item["revision"])
        for item in db.execute("SELECT id, revision FROM public_cards").fetchall()
    }
    return [
        _comment_dict(row, names.get(row["anon_id"], "匿名"), viewer_id=None, admin=True,
                      current_revision=revisions.get(row["card_id"]))
        for row in rows
    ]
