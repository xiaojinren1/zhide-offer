"""社群接口：投稿、公开浏览、有帮助、举报、管理员审核。

可见性由 `engine.community.cards` 统一裁决（SQL 里限定 `status='public'`），
接口层不自己拼条件；返回体不含账号 ID，只给匿名马甲名。
"""
from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel, ConfigDict, Field

from api.user_stats import is_admin
from core import accounts
from engine import community
from engine.documents import store

router = APIRouter(prefix="/api/community", tags=["community"])

KIND_LABEL = {"interview": "面经", "referral": "内推", "jd_review": "JD 评价"}


class SubmitRequest(BaseModel):
    """投稿。`doc_id` 可以从自己的资料里一键带入正文（仍会脱敏、仍要审核）。"""

    model_config = ConfigDict(strict=True, extra="forbid")

    kind: Literal["interview", "referral", "jd_review"]
    title: str = Field(default="", max_length=200)
    body_md: str = Field(default="", max_length=20000)
    company: str = Field(default="", max_length=200)
    role: str = Field(default="", max_length=200)
    round: str = Field(default="", max_length=40)
    tags: list[str] = Field(default_factory=list, max_length=20)
    doc_id: str = Field(default="", max_length=64)


class ReviewRequest(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")

    action: Literal["approve", "reject"]
    note: str = Field(default="", max_length=500)


class ReportRequest(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")

    reason: str = Field(min_length=1, max_length=300)


def _require_account(user: dict = Depends(accounts.require_user)) -> dict:
    if user.get("guest"):
        raise HTTPException(status_code=403, detail="试用账号不能投稿或举报，请先注册正式账号")
    return user


def _require_admin(user: dict = Depends(accounts.require_user)) -> dict:
    if not is_admin(user):
        raise HTTPException(status_code=403, detail="只有管理员可以审核社群内容")
    return user


def _from_draft(doc_id: str, user_id: str) -> dict[str, Any]:
    """从自己的资料里取正文；看不见的资料明确报错，不静默当成"没选"。

    用 422 而不是 404：这是"你选中的引用对象用不了"的表单错误，不是"页面不存在"。
    静默忽略更糟——用户会以为自己引用了资料，实际却是另一段正文。
    """
    with accounts.connection() as db:
        row = store.get_document(db, doc_id, user_id=user_id)
        if row is None:
            raise HTTPException(
                status_code=422,
                detail="选中的资料不存在或不属于当前账号，请重新选择；如果不需要引用资料，留空直接写正文",
            )
        return {
            "title": row["title"],
            "body_md": row["content_md"],
            "company": row["company"],
            "role": row["role"],
        }


@router.post("/cards", status_code=201)
def submit_card(req: SubmitRequest, user: dict = Depends(_require_account)):
    title, body = req.title, req.body_md
    company, role = req.company, req.role
    doc_id = req.doc_id.strip()
    if doc_id:
        draft = _from_draft(doc_id, user["id"])
        title = title or draft["title"]
        body = body or draft["body_md"]
        company = company or draft["company"]
        role = role or draft["role"]
    try:
        with accounts.connection() as db:
            result = community.cards.submit(
                db, user["id"], kind=req.kind, title=title, body_md=body,
                company=company, role=role, round=req.round, tags=req.tags,
            )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"ok": True, **result,
            "message": "已提交，等待管理员审核。审核通过后其他人看到的是匿名马甲，看不到你的账号。"}


@router.get("/cards")
def list_cards(response: Response, kind: str | None = None, company: str = "", q: str = "",
               before: float | None = None, limit: int = Query(20, ge=1, le=50),
               user: dict = Depends(accounts.require_user)):
    if kind and kind not in community.cards.KINDS:
        raise HTTPException(status_code=422, detail="卡片类型不合法")
    with accounts.connection() as db:
        items = community.cards.list_public(
            db, kind=kind, company=company[:60], q=q[:100], limit=limit, before=before)
    response.headers["Cache-Control"] = "no-store"
    return {"ok": True, "items": items,
            "next_before": items[-1]["published_at"] if len(items) == limit else None}


@router.get("/cards/{card_id}")
def get_card(card_id: str, user: dict = Depends(accounts.require_user)):
    with accounts.connection() as db:
        card = community.cards.get_card(db, card_id, viewer_id=user["id"], admin=is_admin(user))
    if card is None:
        raise HTTPException(status_code=404, detail="内容不存在或尚未通过审核")
    return {"ok": True, "card": card}


@router.get("/mine")
def my_cards(user: dict = Depends(_require_account)):
    with accounts.connection() as db:
        items = community.cards.list_mine(db, user["id"])
    return {"ok": True, "items": items}


@router.post("/cards/{card_id}/helpful")
def mark_helpful(card_id: str, user: dict = Depends(_require_account)):
    try:
        with accounts.connection() as db:
            return {"ok": True, **community.cards.mark_helpful(db, card_id, user["id"])}
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/cards/{card_id}/report")
def report_card(card_id: str, req: ReportRequest,
                user: dict = Depends(_require_account)):
    try:
        with accounts.connection() as db:
            result = community.cards.report(db, card_id, user["id"], req.reason)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    message = "已记录举报，管理员会尽快处理。" + ("该内容已暂时撤下待审。" if result["hidden"] else "")
    return {"ok": True, **result, "message": message}


@router.delete("/cards/{card_id}")
def withdraw_card(card_id: str, user: dict = Depends(accounts.require_user)):
    with accounts.connection() as db:
        removed = community.cards.withdraw(db, card_id, user_id=user["id"], admin=is_admin(user))
    if not removed:
        raise HTTPException(status_code=404, detail="内容不存在或无权删除")
    return {"ok": True}


@router.get("/review")
def review_queue(status: str = "pending", before: float | None = None,
                 limit: int = Query(20, ge=1, le=50),
                 user: dict = Depends(_require_admin)):
    try:
        with accounts.connection() as db:
            items = community.cards.review_queue(db, status=status, before=before, limit=limit)
            counts = community.cards.pending_counts(db)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"ok": True, "items": items, "counts": counts}


@router.patch("/cards/{card_id}")
def review_card(card_id: str, req: ReviewRequest, user: dict = Depends(_require_admin)):
    try:
        with accounts.connection() as db:
            return {"ok": True, **community.cards.review(
                db, card_id, reviewer_id=user["id"], action=req.action, note=req.note)}
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
