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


def _card_dict(row: Any, anon_name: str) -> dict[str, Any]:
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
        "helpful_count": row["helpful_count"],
        "report_count": row["report_count"],
        "review_note": row["review_note"],
        "created_at": row["created_at"],
        "published_at": row["published_at"],
    }


def _attach(db, rows: list[Any]) -> list[dict[str, Any]]:
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
    return [_card_dict(row, names.get(row["anon_id"], "匿名")) for row in rows]


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
    return {"id": card_id, "status": "pending", "created_at": now}


def list_public(db, *, kind: str | None = None, company: str = "", q: str = "",
                limit: int = 20, before: float | None = None) -> list[dict[str, Any]]:
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
    return _attach(db, rows)


def list_mine(db, user_id: str, *, limit: int = 50) -> list[dict[str, Any]]:
    rows = db.execute(
        "SELECT * FROM public_cards WHERE user_id = ? ORDER BY created_at DESC LIMIT ?",
        (user_id, max(1, min(limit, 100))),
    ).fetchall()
    return _attach(db, rows)


def get_card(db, card_id: str, *, viewer_id: str, admin: bool) -> dict[str, Any] | None:
    """详情：公开卡片谁都能看；未公开的只有作者和管理员能看。"""
    row = db.execute("SELECT * FROM public_cards WHERE id = ?", (card_id,)).fetchone()
    if row is None:
        return None
    if row["status"] != "public" and not admin and row["user_id"] != viewer_id:
        return None
    return _attach(db, [row])[0]


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


def mark_helpful(db, card_id: str, user_id: str) -> dict[str, Any]:
    """有帮助：一人一票，重复点击不重复计数。"""
    row = db.execute("SELECT status FROM public_cards WHERE id = ?", (card_id,)).fetchone()
    if row is None:
        raise LookupError("卡片不存在")
    if row["status"] != "public":
        raise LookupError("卡片不存在")
    inserted = db.execute(
        "INSERT OR IGNORE INTO card_votes(card_id, user_id, created_at) VALUES (?,?,?)",
        (card_id, user_id, _now()),
    ).rowcount
    if inserted:
        db.execute("UPDATE public_cards SET helpful_count = helpful_count + 1 WHERE id = ?", (card_id,))
    count = db.execute("SELECT helpful_count FROM public_cards WHERE id = ?", (card_id,)).fetchone()[0]
    return {"helpful_count": count, "already": not bool(inserted)}


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
