"""投递看板：一个岗位一条记录，状态只能沿约定的方向推进。

边界：

- **同一岗位只有一条记录**（`idx_applications_doc` 唯一索引），推进状态是更新而不是新增。
- **每次状态变化都写一条留痕**（`application_events`），刷新后能回看走了哪些步。
- **账号隔离**：所有读写按 `user_id` 限定，别人的记录一律当作不存在。
- 只记"下一次动作时间"，不做推送（推送要额外通道，本期不做）。
"""
from __future__ import annotations

import time
from typing import Any
from uuid import uuid4

# 主线：保存 → 定制 → 投递 → 面试 → offer；任意非终态都能归档或标记被拒
STAGES = ("saved", "tailored", "applied", "interview", "offer", "rejected", "archived")
STAGE_LABEL = {
    "saved": "已收藏",
    "tailored": "已定制简历",
    "applied": "已投递",
    "interview": "面试中",
    "offer": "拿到 offer",
    "rejected": "被拒",
    "archived": "已归档",
}
NEXT_STAGES: dict[str, tuple[str, ...]] = {
    "saved": ("tailored", "applied", "archived"),
    "tailored": ("applied", "archived"),
    "applied": ("interview", "rejected", "archived"),
    "interview": ("offer", "rejected", "archived"),
    "offer": ("archived",),
    "rejected": ("archived",),
    # 归档后可以重新开始，避免"归档错了只能删记录"
    "archived": ("saved",),
}


def _now() -> float:
    return time.time()


def _clip(value: object, limit: int) -> str:
    return str(value or "").strip()[:limit]


def parse_next_action(value: object) -> float | None:
    """接受 `YYYY-MM-DD`，存成当天 09:00 的本地时间戳；空值表示不提醒。"""
    text = str(value or "").strip()
    if not text:
        return None
    from datetime import datetime

    try:
        day = datetime.strptime(text[:10], "%Y-%m-%d")
    except ValueError as exc:
        raise ValueError("下一次动作时间请用 YYYY-MM-DD") from exc
    return day.replace(hour=9).timestamp()


def format_next_action(value: float | None) -> str:
    if not value:
        return ""
    from datetime import datetime

    return datetime.fromtimestamp(value).strftime("%Y-%m-%d")


def _event_dict(row: Any) -> dict[str, Any]:
    return {
        "from_stage": row["from_stage"],
        "to_stage": row["to_stage"],
        "note": row["note"],
        "created_at": row["created_at"],
    }


def _record_dict(row: Any, doc: Any) -> dict[str, Any]:
    return {
        "id": row["id"],
        "doc_id": row["doc_id"],
        "stage": row["stage"],
        "stage_label": STAGE_LABEL.get(row["stage"], row["stage"]),
        "next_stage": list(NEXT_STAGES.get(row["stage"], ())),
        "next_action_at": row["next_action_at"],
        "next_action_date": format_next_action(row["next_action_at"]),
        "note": row["note"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "job": {
            "title": doc["title"],
            "company": doc["company"],
            "city": doc["city"],
            "url": doc["url"],
            "salary_text": doc["salary_text"],
        } if doc is not None else None,
    }


def _history(db, application_id: str, limit: int = 50) -> list[dict[str, Any]]:
    rows = db.execute(
        "SELECT from_stage, to_stage, note, created_at FROM application_events"
        " WHERE application_id = ? ORDER BY id DESC LIMIT ?",
        (application_id, limit),
    ).fetchall()
    return [_event_dict(row) for row in rows]


def list_applications(db, user_id: str, *, stage: str | None = None,
                      include_archived: bool = False, limit: int = 50) -> list[dict[str, Any]]:
    """列表：默认排除归档（归档是收尾状态），按最近更新排序。"""
    clauses = ["a.user_id = ?"]
    params: list[Any] = [user_id]
    if stage:
        clauses.append("a.stage = ?")
        params.append(stage)
    elif not include_archived:
        clauses.append("a.stage != 'archived'")
    rows = db.execute(
        "SELECT a.*, d.title, d.company, d.city, d.url, d.salary_text"
        " FROM applications a JOIN documents d ON d.id = a.doc_id"
        " WHERE " + " AND ".join(clauses) + " ORDER BY a.updated_at DESC LIMIT ?",
        (*params, max(1, min(limit, 200))),
    ).fetchall()
    return [_record_dict(row, row) for row in rows]


def get_application(db, user_id: str, doc_id: str) -> dict[str, Any] | None:
    row = db.execute(
        "SELECT a.*, d.title, d.company, d.city, d.url, d.salary_text"
        " FROM applications a JOIN documents d ON d.id = a.doc_id"
        " WHERE a.user_id = ? AND a.doc_id = ?",
        (user_id, doc_id),
    ).fetchone()
    if row is None:
        return None
    result = _record_dict(row, row)
    result["history"] = _history(db, row["id"])
    return result


def advance(db, user_id: str, doc_id: str, *, stage: str, note: object = "",
            next_action: object = "") -> dict[str, Any]:
    """推进（或创建）一条投递记录。校验文档属于本人、状态转移合法。"""
    if stage not in STAGES:
        raise ValueError("投递状态不合法")
    # 用统一的可见性规则：自己的私有资料 + 公共岗位池都能加入看板
    # （公共池文档的 user_id 是 NULL，早先按 owner 相等判断会把采集来的岗位全部误判为不存在）
    from .store import get_document

    if get_document(db, doc_id, user_id=user_id) is None:
        raise LookupError("岗位不存在或无权操作")
    clean_note = _clip(note, 500)
    next_at = parse_next_action(next_action)
    row = db.execute(
        "SELECT * FROM applications WHERE user_id = ? AND doc_id = ?", (user_id, doc_id)
    ).fetchone()
    now = _now()
    if row is None:
        if stage != "saved":
            raise ValueError("请在收件箱里先「加入投递看板」，再推进状态")
        application_id = uuid4().hex
        db.execute(
            "INSERT INTO applications(id, user_id, doc_id, stage, note, next_action_at,"
            " created_at, updated_at) VALUES (?,?,?,?,?,?,?,?)",
            (application_id, user_id, doc_id, stage, clean_note, next_at, now, now),
        )
        db.execute(
            "INSERT INTO application_events(application_id, from_stage, to_stage, note, created_at)"
            " VALUES (?,?,?,?,?)",
            (application_id, "", stage, clean_note, now),
        )
        from_stage = ""
    else:
        application_id = row["id"]
        from_stage = row["stage"]
        if stage != from_stage and stage not in NEXT_STAGES.get(from_stage, ()):
            raise ValueError(
                f"不能从「{STAGE_LABEL.get(from_stage, from_stage)}」直接推进到"
                f"「{STAGE_LABEL.get(stage, stage)}」，可选："
                + "、".join(STAGE_LABEL[s] for s in NEXT_STAGES.get(from_stage, ()))
            )
        db.execute(
            "UPDATE applications SET stage = ?, note = ?, next_action_at = ?, updated_at = ?"
            " WHERE id = ?",
            (stage, clean_note or row["note"], next_at if next_action else row["next_action_at"],
             now, application_id),
        )
        if stage != from_stage:
            db.execute(
                "INSERT INTO application_events(application_id, from_stage, to_stage, note, created_at)"
                " VALUES (?,?,?,?,?)",
                (application_id, from_stage, stage, clean_note, now),
            )
    return get_application(db, user_id, doc_id) or {}


def remove(db, user_id: str, doc_id: str) -> bool:
    """删除投递记录（连带留痕）；岗位资料本身不动。"""
    row = db.execute(
        "SELECT id FROM applications WHERE user_id = ? AND doc_id = ?", (user_id, doc_id)
    ).fetchone()
    if row is None:
        return False
    db.execute("DELETE FROM application_events WHERE application_id = ?", (row["id"],))
    db.execute("DELETE FROM applications WHERE id = ?", (row["id"],))
    return True


def summary(db, user_id: str) -> dict[str, int]:
    """各阶段条数，用于列表页的筛选徽标。"""
    rows = db.execute(
        "SELECT stage, COUNT(*) AS total FROM applications WHERE user_id = ? GROUP BY stage",
        (user_id,),
    ).fetchall()
    counts = {stage: 0 for stage in STAGES}
    for row in rows:
        counts[row["stage"]] = row["total"]
    return counts
