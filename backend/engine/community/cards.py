"""面经 / 内推 / JD 评价卡片的存储与状态机。

三条硬约束（对应 AGENTS.md 的社群边界）：

- **只有 `status = 'public'` 才会出现在任何公开列表里**，过滤写在 SQL 条件里，不靠前端隐藏。
- **匿名是默认且唯一对外形态**：卡片只带 `anon_identities.display_name`，账号 ID 与马甲映射
  只在服务端可查，接口与返回体都不暴露 `user_id` / `anon_id`。
- **入库前必须脱敏**：手机号、邮箱、证件号、QQ、微信在写库前替换成占位符。
"""
from __future__ import annotations

import json
import secrets
import time
from typing import Any
from uuid import uuid4

from .redact import redact

KINDS = ("interview", "referral", "jd_review")
STATUSES = ("pending", "public", "rejected")
MAX_TITLE = 80
MAX_BODY = 8000
MAX_COMPANY = 60
MAX_ROLE = 60
MAX_TAG = 20
MAX_TAGS = 8
MAX_COMMENT = 600
# 累计这么多条举报就先从公开列表撤下、回到待审
REPORT_HIDE_THRESHOLD = 3

_ADJECTIVES = ("安静的", "认真准备的", "刚下班的", "在路上的", "话不多的", "有点紧张的")
_NOUNS = ("青柠", "白桦", "海盐", "磐石", "乌龙", "苔藓", "南风", "磁石", "棉线", "月台")


def _now() -> float:
    return time.time()


def _clip(value: object, limit: int) -> str:
    return str(value or "").strip()[:limit]


def anon_display_name() -> str:
    """生成一个不带账号信息的马甲名，例如「安静的青柠 42」。"""
    return f"{secrets.choice(_ADJECTIVES)}{secrets.choice(_NOUNS)} {secrets.randbelow(90) + 10}"


def ensure_anon_id(db, user_id: str) -> str:
    """同一账号复用同一个马甲，多次投稿看起来像同一个人，但不暴露是谁。"""
    row = db.execute(
        "SELECT id FROM anon_identities WHERE user_id = ? ORDER BY created_at LIMIT 1", (user_id,)
    ).fetchone()
    if row is not None:
        return row["id"]
    anon_id = uuid4().hex
    db.execute(
        "INSERT INTO anon_identities(id, user_id, display_name, created_at) VALUES (?,?,?,?)",
        (anon_id, user_id, anon_display_name(), _now()),
    )
    return anon_id


def snapshot_revision(db, card_id: str, revision: int | None = None) -> None:
    """把卡片当前内容存成一份版本快照（同版本重复写只保留一次）。"""
    row = db.execute("SELECT * FROM public_cards WHERE id = ?", (card_id,)).fetchone()
    if row is None:
        return
    version = int(revision if revision is not None else row["revision"])
    db.execute(
        "INSERT OR IGNORE INTO card_revisions(card_id, revision, title, body_md, company, role,"
        " round, tags_json, created_at) VALUES (?,?,?,?,?,?,?,?,?)",
        (card_id, version, row["title"], row["body_md"], row["company"], row["role"],
         row["round"], row["tags_json"], _now()),
    )


def _revision_dict(row: Any) -> dict[str, Any]:
    try:
        tags = json.loads(row["tags_json"] or "[]")
    except (TypeError, ValueError):
        tags = []
    return {
        "revision": row["revision"],
        "title": row["title"],
        "body_md": row["body_md"],
        "company": row["company"],
        "role": row["role"],
        "round": row["round"],
        "tags": tags if isinstance(tags, list) else [],
        "created_at": row["created_at"],
    }


def list_revisions(db, card_id: str, *, viewer_id: str, admin: bool) -> list[dict[str, Any]]:
    """作者与管理员可看全部版本；其他人一律看不到（历史内容可能已因合规撤下）。

    没有快照的老卡片（本功能上线前创建）会把当前内容补一份，保证至少能看到现状。
    """
    card = db.execute("SELECT user_id FROM public_cards WHERE id = ?", (card_id,)).fetchone()
    if card is None or (card["user_id"] != viewer_id and not admin):
        raise LookupError("投稿不存在或无权查看历史")
    rows = db.execute(
        "SELECT * FROM card_revisions WHERE card_id = ? ORDER BY revision DESC", (card_id,)
    ).fetchall()
    if not rows:
        snapshot_revision(db, card_id)
        rows = db.execute(
            "SELECT * FROM card_revisions WHERE card_id = ? ORDER BY revision DESC", (card_id,)
        ).fetchall()
    return [_revision_dict(row) for row in rows]


def get_revision(db, card_id: str, revision: int, *, viewer_id: str, admin: bool) -> dict[str, Any]:
    card = db.execute("SELECT user_id FROM public_cards WHERE id = ?", (card_id,)).fetchone()
    if card is None or (card["user_id"] != viewer_id and not admin):
        raise LookupError("投稿不存在或无权查看历史")
    row = db.execute(
        "SELECT * FROM card_revisions WHERE card_id = ? AND revision = ?", (card_id, revision)
    ).fetchone()
    if row is None:
        raise LookupError("这个版本不存在")
    return _revision_dict(row)


def _card_dict(row: Any, anon_name: str, *, viewer_helpful: bool = False,
               comment_count: int = 0) -> dict[str, Any]:
    """对外形态：不含 user_id / anon_id / 审核人。"""
    try:
        tags = json.loads(row["tags_json"] or "[]")
    except (TypeError, ValueError):
        tags = []
    return {
        "id": row["id"],
        "kind": row["kind"],
        "company": row["company"],
        "role": row["role"],
        "round": row["round"],
        "title": row["title"],
        "body_md": row["body_md"],
        "tags": tags if isinstance(tags, list) else [],
        "status": row["status"],
        "author": anon_name,
        "revision": row["revision"],
        "helpful_count": row["helpful_count"],
        "viewer_helpful": viewer_helpful,
        "comment_count": comment_count,
        "report_count": row["report_count"],
        "review_note": row["review_note"],
        "created_at": row["created_at"],
        "published_at": row["published_at"],
    }


def _attach(db, rows: list[Any], *, viewer_id: str | None = None) -> list[dict[str, Any]]:
    """批量补匿名马甲名、当前用户是否点过有帮助、评论数。"""
    if not rows:
        return []
    anon_ids = {row["anon_id"] for row in rows}
    marks = ",".join("?" for _ in anon_ids)
    names = {
        item["id"]: item["display_name"]
        for item in db.execute(
            f"SELECT id, display_name FROM anon_identities WHERE id IN ({marks})", tuple(anon_ids)
        ).fetchall()
    }
    card_ids = [row["id"] for row in rows]
    id_marks = ",".join("?" for _ in card_ids)
    voted: set[str] = set()
    if viewer_id:
        voted = {
            item["card_id"]
            for item in db.execute(
                f"SELECT card_id FROM card_votes WHERE user_id = ? AND card_id IN ({id_marks})",
                (viewer_id, *card_ids),
            ).fetchall()
        }
    comment_counts = {
        item["card_id"]: item["total"]
        for item in db.execute(
            f"SELECT c.card_id AS card_id, COUNT(*) AS total FROM card_comments c"
            f" JOIN public_cards p ON p.id = c.card_id"
            f" WHERE c.status = 'public' AND c.card_id IN ({id_marks})"
            f" AND c.revision = p.revision GROUP BY c.card_id",
            tuple(card_ids),
        ).fetchall()
    }
    return [
        _card_dict(
            row, names.get(row["anon_id"], "匿名"),
            viewer_helpful=row["id"] in voted,
            comment_count=comment_counts.get(row["id"], 0),
        )
        for row in rows
    ]


def submit(db, user_id: str, *, kind: str, title: object, body_md: object,
           company: object = "", role: object = "", round: object = "",
           tags: list[Any] | None = None) -> dict[str, Any]:
    """投稿入库：脱敏 → pending。返回给前端的只是提交结果，不是公开内容。"""
    if kind not in KINDS:
        raise ValueError("卡片类型不合法")
    clean_title = redact(_clip(title, MAX_TITLE))
    clean_body = redact(_clip(body_md, MAX_BODY))
    if not clean_title:
        raise ValueError("请填写标题")
    if len(clean_body) < 20:
        raise ValueError("正文太短，写清一面问了什么、你怎么回答的才有参考价值")
    clean_tags = [redact(_clip(tag, MAX_TAG)) for tag in (tags or []) if _clip(tag, MAX_TAG)][:MAX_TAGS]
    anon_id = ensure_anon_id(db, user_id)
    card_id = uuid4().hex
    now = _now()
    db.execute(
        "INSERT INTO public_cards(id, user_id, anon_id, kind, company, role, round, title, body_md,"
        " tags_json, status, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,'pending',?)",
        (card_id, user_id, anon_id, kind, _clip(company, MAX_COMPANY), _clip(role, MAX_ROLE),
         _clip(round, 20), clean_title, clean_body, json.dumps(clean_tags, ensure_ascii=False), now),
    )
    snapshot_revision(db, card_id, 1)
    return {"id": card_id, "status": "pending", "created_at": now}


def list_public(db, *, kind: str | None = None, company: str = "", q: str = "",
                limit: int = 20, before: float | None = None,
                viewer_id: str | None = None) -> list[dict[str, Any]]:
    """公开列表：SQL 里写死 status = 'public'。"""
    conditions = ["status = 'public'"]
    params: list[Any] = []
    if kind:
        conditions.append("kind = ?")
        params.append(kind)
    if company.strip():
        conditions.append("company LIKE ?")
        params.append(f"%{company.strip()}%")
    if q.strip():
        conditions.append("(title LIKE ? OR body_md LIKE ? OR company LIKE ? OR role LIKE ?)")
        params.extend([f"%{q.strip()}%"] * 4)
    if before is not None:
        conditions.append("published_at < ?")
        params.append(before)
    rows = db.execute(
        "SELECT * FROM public_cards WHERE " + " AND ".join(conditions)
        + " ORDER BY published_at DESC, id DESC LIMIT ?",
        (*params, max(1, min(limit, 50))),
    ).fetchall()
    return _attach(db, rows, viewer_id=viewer_id)


def list_mine(db, user_id: str, *, limit: int = 50) -> list[dict[str, Any]]:
    rows = db.execute(
        "SELECT * FROM public_cards WHERE user_id = ? ORDER BY created_at DESC LIMIT ?",
        (user_id, max(1, min(limit, 100))),
    ).fetchall()
    return _attach(db, rows, viewer_id=user_id)


def get_card(db, card_id: str, *, viewer_id: str, admin: bool) -> dict[str, Any] | None:
    """详情：公开卡片谁都能看；未公开的只有作者和管理员能看。"""
    row = db.execute("SELECT * FROM public_cards WHERE id = ?", (card_id,)).fetchone()
    if row is None:
        return None
    if row["status"] != "public" and not admin and row["user_id"] != viewer_id:
        return None
    return _attach(db, [row], viewer_id=viewer_id)[0]


def review(db, card_id: str, *, reviewer_id: str, action: str, note: object = "") -> dict[str, Any]:
    """审核：通过 → public；退回必须写理由，作者要能看懂哪里不行。"""
    if action not in ("approve", "reject"):
        raise ValueError("审核动作不合法")
    clean_note = _clip(redact(note), 200)
    if action == "reject" and not clean_note:
        raise ValueError("退回必须写明原因")
    row = db.execute("SELECT status FROM public_cards WHERE id = ?", (card_id,)).fetchone()
    if row is None:
        raise LookupError("卡片不存在")
    now = _now()
    if action == "approve":
        db.execute(
            "UPDATE public_cards SET status = 'public', published_at = ?, reviewed_by = ?,"
            " reviewed_at = ?, review_note = ? WHERE id = ?",
            (now, reviewer_id, now, clean_note, card_id),
        )
        status = "public"
    else:
        db.execute(
            "UPDATE public_cards SET status = 'rejected', reviewed_by = ?, reviewed_at = ?,"
            " review_note = ? WHERE id = ?",
            (reviewer_id, now, clean_note, card_id),
        )
        status = "rejected"
    return {"id": card_id, "status": status, "review_note": clean_note}


def revise(db, card_id: str, user_id: str, *, title: object = None, body_md: object = None,
           company: object = None, role: object = None, round: object = None,
           tags: list[Any] | None = None) -> dict[str, Any]:
    """作者修改自己的投稿：内容算新版本，重新进入待审。

    为什么改完要重新审：内容一旦公开过，任何修改都等于新内容，不能再沿用上一次的
    审核结论；已发布内容被改后会自动从列表撤下（`status = 'pending'`），等管理员复核。

    **版本语义**：内容变了就是新一版，所以
    - `revision` +1，旧版的「有帮助」票全部作废（票是针对上一版内容的认可）；
    - 旧版评论保留但归属上一版，不再计入这一版的评论数（前端标注“上一版内容下的评论”）；
    - 旧举报按“内容已更新”结案，`report_count` 归零，避免旧举报拖着新内容。
    """
    row = db.execute("SELECT user_id, revision FROM public_cards WHERE id = ?", (card_id,)).fetchone()
    if row is None or row["user_id"] != user_id:
        raise LookupError("投稿不存在或无权修改")
    updates: dict[str, Any] = {}
    if title is not None:
        clean_title = redact(_clip(title, MAX_TITLE))
        if not clean_title:
            raise ValueError("请填写标题")
        updates["title"] = clean_title
    if body_md is not None:
        clean_body = redact(_clip(body_md, MAX_BODY))
        if len(clean_body) < 20:
            raise ValueError("正文太短，写清一面问了什么、你怎么回答的才有参考价值")
        updates["body_md"] = clean_body
    if company is not None:
        updates["company"] = _clip(company, MAX_COMPANY)
    if role is not None:
        updates["role"] = _clip(role, MAX_ROLE)
    if round is not None:
        updates["round"] = _clip(round, 20)
    if tags is not None:
        clean_tags = [redact(_clip(tag, MAX_TAG)) for tag in tags if _clip(tag, MAX_TAG)][:MAX_TAGS]
        updates["tags_json"] = json.dumps(clean_tags, ensure_ascii=False)
    if not updates:
        raise ValueError("没有需要保存的修改")
    assignments = ", ".join(f"{key} = ?" for key in updates)
    revision = int(row["revision"]) + 1
    db.execute(
        f"UPDATE public_cards SET {assignments}, status = 'pending', review_note = '',"
        " published_at = NULL, reviewed_by = NULL, reviewed_at = NULL,"
        " revision = ?, helpful_count = 0, report_count = 0 WHERE id = ?",
        (*updates.values(), revision, card_id),
    )
    # 上一版的帮助票作废；旧举报按“内容已更新”结案
    db.execute("DELETE FROM card_votes WHERE card_id = ?", (card_id,))
    db.execute(
        "UPDATE card_reports SET status = 'resolved', handled_by = NULL, handled_at = ?"
        " WHERE card_id = ? AND status = 'open'",
        (_now(), card_id),
    )
    snapshot_revision(db, card_id, revision)
    return {"id": card_id, "status": "pending", "revision": revision}


def resubmit(db, card_id: str, user_id: str) -> dict[str, Any]:
    """被退回后不改内容、直接重新提交审阅。"""
    row = db.execute("SELECT user_id, status FROM public_cards WHERE id = ?", (card_id,)).fetchone()
    if row is None or row["user_id"] != user_id:
        raise LookupError("投稿不存在或无权操作")
    if row["status"] != "rejected":
        raise ValueError("只有被退回的投稿需要重新提交")
    db.execute(
        "UPDATE public_cards SET status = 'pending', review_note = '', reviewed_by = NULL,"
        " reviewed_at = NULL WHERE id = ?",
        (card_id,),
    )
    return {"id": card_id, "status": "pending"}


def review_queue(db, *, status: str = "pending", before: float | None = None,
                 limit: int = 20) -> list[dict[str, Any]]:
    if status not in STATUSES:
        raise ValueError("状态不合法")
    conditions = ["status = ?"]
    params: list[Any] = [status]
    if before is not None:
        conditions.append("created_at < ?")
        params.append(before)
    rows = db.execute(
        "SELECT * FROM public_cards WHERE " + " AND ".join(conditions)
        + " ORDER BY created_at ASC LIMIT ?",
        (*params, max(1, min(limit, 50))),
    ).fetchall()
    return _attach(db, rows)


def withdraw(db, card_id: str, *, user_id: str, admin: bool = False) -> bool:
    """作者撤回（直接删除）。管理员也可删除违规内容。"""
    row = db.execute("SELECT user_id FROM public_cards WHERE id = ?", (card_id,)).fetchone()
    if row is None:
        return False
    if not admin and row["user_id"] != user_id:
        return False
    db.execute("DELETE FROM public_cards WHERE id = ?", (card_id,))
    return True


def toggle_helpful(db, card_id: str, user_id: str) -> dict[str, Any]:
    """有帮助：一人一票，可再点取消。返回当前用户的状态与最新计数。"""
    row = db.execute("SELECT status FROM public_cards WHERE id = ?", (card_id,)).fetchone()
    if row is None or row["status"] != "public":
        raise LookupError("卡片不存在")
    removed = db.execute(
        "DELETE FROM card_votes WHERE card_id = ? AND user_id = ?", (card_id, user_id)
    ).rowcount
    if removed:
        db.execute("UPDATE public_cards SET helpful_count = MAX(helpful_count - 1, 0) WHERE id = ?",
                   (card_id,))
        helpful = False
    else:
        db.execute(
            "INSERT INTO card_votes(card_id, user_id, created_at) VALUES (?,?,?)",
            (card_id, user_id, _now()),
        )
        db.execute("UPDATE public_cards SET helpful_count = helpful_count + 1 WHERE id = ?", (card_id,))
        helpful = True
    count = db.execute("SELECT helpful_count FROM public_cards WHERE id = ?", (card_id,)).fetchone()[0]
    return {"helpful": helpful, "helpful_count": count}


def report(db, card_id: str, user_id: str, reason: object) -> dict[str, Any]:
    """举报：一人一卡一次；累计到阈值先撤下回到待审，等管理员处理。"""
    clean_reason = _clip(redact(reason), 200)
    if not clean_reason:
        raise ValueError("请填写举报原因")
    row = db.execute("SELECT status FROM public_cards WHERE id = ?", (card_id,)).fetchone()
    if row is None:
        raise LookupError("卡片不存在")
    inserted = db.execute(
        "INSERT OR IGNORE INTO card_reports(card_id, user_id, reason, created_at) VALUES (?,?,?,?)",
        (card_id, user_id, clean_reason, _now()),
    ).rowcount
    if not inserted:
        return {"report_count": _report_count(db, card_id), "already": True, "hidden": False}
    db.execute("UPDATE public_cards SET report_count = report_count + 1 WHERE id = ?", (card_id,))
    count = _report_count(db, card_id)
    hidden = False
    if count >= REPORT_HIDE_THRESHOLD and row["status"] == "public":
        db.execute(
            "UPDATE public_cards SET status = 'pending', review_note = ? WHERE id = ?",
            (f"累计 {count} 条举报，已自动撤下待审", card_id),
        )
        hidden = True
    return {"report_count": count, "already": False, "hidden": hidden}


def _report_count(db, card_id: str) -> int:
    return db.execute("SELECT COUNT(*) FROM card_reports WHERE card_id = ?", (card_id,)).fetchone()[0]


def pending_counts(db) -> dict[str, int]:
    rows = db.execute("SELECT status, COUNT(*) FROM public_cards GROUP BY status").fetchall()
    counts = {status: 0 for status in STATUSES}
    for row in rows:
        counts[row[0]] = row[1]
    return counts


def list_reports(db, *, only_open: bool = True, limit: int = 30) -> list[dict[str, Any]]:
    """管理员举报队列：按卡片聚合，带每条举报原因与卡片当前状态。"""
    condition = "WHERE r.status = 'open'" if only_open else ""
    rows = db.execute(
        f"""SELECT r.card_id, r.reason, r.created_at, c.title, c.kind, c.company, c.role,
                   c.round, c.status AS card_status, c.report_count
            FROM card_reports r JOIN public_cards c ON c.id = r.card_id
            {condition}
            ORDER BY r.id DESC LIMIT ?""",
        (max(1, min(limit, 100)),),
    ).fetchall()
    grouped: dict[str, dict[str, Any]] = {}
    for row in rows:
        item = grouped.setdefault(row["card_id"], {
            "card_id": row["card_id"],
            "title": row["title"],
            "kind": row["kind"],
            "company": row["company"],
            "role": row["role"],
            "round": row["round"],
            "card_status": row["card_status"],
            "reasons": [],
        })
        item["reasons"].append({"reason": row["reason"], "created_at": row["created_at"]})
    for item in grouped.values():
        item["report_count"] = len(item["reasons"])
    return list(grouped.values())


def resolve_reports(db, card_id: str, *, admin_id: str) -> int:
    """把一张卡片的待处理举报标为已处理；记录保留，便于复盘。"""
    reason_rows = db.execute(
        "SELECT reason FROM card_reports WHERE card_id = ? AND status = 'open'", (card_id,)
    ).fetchall()
    if not reason_rows:
        return 0
    db.execute(
        "UPDATE card_reports SET status = 'resolved', handled_by = ?, handled_at = ?"
        " WHERE card_id = ? AND status = 'open'",
        (admin_id, _now(), card_id),
    )
    return len(reason_rows)


def unpublish(db, card_id: str, *, admin_id: str, note: object = "") -> dict[str, Any]:
    """下架已公开内容：从列表撤下但保留记录，作者能看到原因。"""
    row = db.execute("SELECT status FROM public_cards WHERE id = ?", (card_id,)).fetchone()
    if row is None:
        raise LookupError("卡片不存在")
    if row["status"] != "public":
        raise ValueError("只有已发布的内容需要下架")
    clean_note = _clip(redact(note), 200) or "管理员下架：内容不符合社群规范"
    db.execute(
        "UPDATE public_cards SET status = 'rejected', reviewed_by = ?, reviewed_at = ?,"
        " review_note = ? WHERE id = ?",
        (admin_id, _now(), clean_note, card_id),
    )
    return {"id": card_id, "status": "rejected", "review_note": clean_note}
