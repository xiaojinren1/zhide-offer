from datetime import datetime, timezone
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel, StringConstraints

from api.user_stats import is_admin
from core import accounts

router = APIRouter(prefix="/api/feedback")
FeedbackStatus = Literal["pending", "reviewing", "resolved"]
PAGE_SIZE = 20


class FeedbackRequest(BaseModel):
    message: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2000)]


class StatusRequest(BaseModel):
    status: FeedbackStatus


def require_account(user: dict = Depends(accounts.require_user)):
    if user.get("guest"):
        raise HTTPException(403, "请登录正式账号后使用站内反馈")
    return user


@router.get("")
def list_feedback(response: Response, manage: bool = False,
                  before: int | None = Query(None, ge=1, le=2**53 - 1),
                  user: dict = Depends(require_account)):
    admin = is_admin(user)
    if manage and not admin:
        raise HTTPException(403, "没有管理反馈的权限")
    query = """SELECT f.id, f.message, f.status, f.created_at, u.username
               FROM feedback f JOIN users u ON u.id = f.user_id"""
    conditions = []
    params = []
    if not manage:
        conditions.append("f.user_id = ?")
        params.append(user["id"])
    if before is not None:
        conditions.append("f.id < ?")
        params.append(before)
    if conditions:
        query += " WHERE " + " AND ".join(conditions)
    with accounts.connection() as db:
        rows = db.execute(query + " ORDER BY f.id DESC LIMIT ?", (*params, PAGE_SIZE + 1)).fetchall()
    response.headers["Cache-Control"] = "no-store"
    return {"can_manage": admin, "items": [dict(row) for row in rows[:PAGE_SIZE]],
            "next_before": rows[PAGE_SIZE - 1]["id"] if len(rows) > PAGE_SIZE else None}


@router.post("", status_code=201)
def create_feedback(body: FeedbackRequest, user: dict = Depends(require_account)):
    with accounts.connection() as db:
        db.execute("INSERT INTO feedback(user_id, message, created_at) VALUES (?, ?, ?)",
                   (user["id"], body.message, datetime.now(timezone.utc).isoformat()))
    return {"ok": True}


@router.patch("/{feedback_id}")
def update_feedback(feedback_id: int, body: StatusRequest, user: dict = Depends(require_account)):
    if not is_admin(user):
        raise HTTPException(403, "没有管理反馈的权限")
    if not 1 <= feedback_id <= 2**53 - 1:
        raise HTTPException(404, "反馈不存在")
    with accounts.connection() as db:
        if not db.execute("UPDATE feedback SET status = ? WHERE id = ?",
                          (body.status, feedback_id)).rowcount:
            raise HTTPException(404, "反馈不存在")
    return {"ok": True}
