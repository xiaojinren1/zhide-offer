"""当前账户的工作台快照；版本比较防止多标签页静默覆盖。"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from core import accounts

router = APIRouter(prefix="/api/workspace", tags=["workspace"])
MAX_WORKSPACE_BYTES = 2 * 1024 * 1024


class ExperienceState(BaseModel):
    # 引擎的可追溯字段（如 source_text、quantified）也需原样保留。
    model_config = ConfigDict(strict=True, extra="allow")
    kind: str
    name: str
    role: str
    period: str
    actions: list[str]
    results: list[str]
    skills: list[str]


class ProfileState(BaseModel):
    model_config = ConfigDict(strict=True, extra="allow")
    name: str
    experiences: list[ExperienceState]
    skills: list[str]
    education: list[str]
    raw_text: str = ""
    user_confirmed: bool = False


class WorkspaceState(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")
    source_text: str
    source_name: str
    jd_text: str
    profile: ProfileState | None
    jd_keywords: list[str]
    markdown: str
    page: Literal["workbench", "diagnose", "quality", "interview", "memory"]


class SaveWorkspaceRequest(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")
    expected_user_id: str = Field(min_length=1)
    revision: int = Field(ge=0)
    state: WorkspaceState


def check_account(expected_user_id: str, user: dict) -> None:
    if expected_user_id != user["id"]:
        raise HTTPException(status_code=409, detail="账户已变化，请刷新页面后重新登录")


def encode_record(value: Any, max_bytes: int) -> str:
    try:
        encoded = json.dumps(value, ensure_ascii=False, allow_nan=False)
    except (ValueError, TypeError) as exc:
        raise HTTPException(status_code=422, detail="保存内容必须为有效 JSON 数据") from exc
    if len(encoded.encode("utf-8")) > max_bytes:
        raise HTTPException(status_code=413, detail="保存内容过大，请缩减材料后重试")
    return encoded


def timestamp() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


@router.get("")
def load_workspace(user: dict = Depends(accounts.require_user)):
    with accounts.connection() as db:
        row = db.execute(
            "SELECT revision,saved_at,state_json FROM workspaces WHERE user_id = ?", (user["id"],)
        ).fetchone()
    if row is None:
        return {"ok": True, "revision": 0, "state": None, "saved_at": None}
    return {"ok": True, "revision": row["revision"], "saved_at": row["saved_at"],
            "state": json.loads(row["state_json"])}


@router.post("")
def save_workspace(req: SaveWorkspaceRequest, user: dict = Depends(accounts.require_user)):
    check_account(req.expected_user_id, user)
    state_json = encode_record(req.state.model_dump(), MAX_WORKSPACE_BYTES)
    saved_at = timestamp()
    with accounts.connection() as db:
        if req.revision == 0:
            changed = db.execute(
                "INSERT INTO workspaces(user_id,revision,saved_at,state_json) VALUES(?,1,?,?) "
                "ON CONFLICT(user_id) DO NOTHING", (user["id"], saved_at, state_json)
            ).rowcount
        else:
            changed = db.execute(
                "UPDATE workspaces SET revision=revision+1,saved_at=?,state_json=? "
                "WHERE user_id=? AND revision=?", (saved_at, state_json, user["id"], req.revision)
            ).rowcount
        if not changed:
            raise HTTPException(status_code=409, detail="工作台已在其他页面更新，请加载服务器版本后继续")
    return {"ok": True, "revision": req.revision + 1, "saved_at": saved_at}
