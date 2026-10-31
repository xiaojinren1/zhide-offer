"""登录账户的经历库；所有读写均由服务端当前用户限定归属。"""
from __future__ import annotations

import hashlib
import json
import re
import time
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from api.workspace import ProfileState, encode_record, timestamp, MAX_WORKSPACE_BYTES

from core import accounts, events

router = APIRouter(prefix="/api/profiles", tags=["profiles"])


class SaveRequest(BaseModel):
    name: str = ""
    profile: dict


class UpdateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    expected_revision: str = Field(min_length=64, max_length=64)
    profile: ProfileState | None = None


def revision(row) -> str:
    return hashlib.sha256(json.dumps([row["name"], row["saved_at"], row["profile_json"]], ensure_ascii=False).encode("utf-8")).hexdigest()


def _new_id(name: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9_-]", "", (name or "profile"))[:20] or "profile"
    return f"{slug}-{uuid4().hex}"


@router.post("/save")
def save(req: SaveRequest, user: dict = Depends(accounts.require_user)):
    if not req.profile.get("experiences"):
        return {"ok": False, "error": "经历库为空，拒绝保存"}
    pid = _new_id(req.name or str(req.profile.get("name") or ""))
    name = (req.name or str(req.profile.get("name") or "")).strip()
    saved_at = time.strftime("%Y-%m-%d %H:%M:%S")
    count = len(req.profile["experiences"])
    with accounts.connection() as db:
        db.execute(
            "INSERT INTO profiles(id,user_id,name,saved_at,experience_count,profile_json) VALUES(?,?,?,?,?,?)",
            (pid, user["id"], name, saved_at, count, json.dumps(req.profile, ensure_ascii=False)),
        )
    events.emit("profile_saved", id=pid, experiences=count)
    return {"ok": True, "id": pid, "saved_at": saved_at}


@router.get("/list")
def list_profiles(user: dict = Depends(accounts.require_user)):
    with accounts.connection() as db:
        rows = db.execute(
            "SELECT id,name,saved_at,experience_count FROM profiles WHERE user_id = ? ORDER BY rowid DESC",
            (user["id"],),
        ).fetchall()
    return {"ok": True, "profiles": [dict(row) for row in rows]}


@router.get("/{profile_id}")
def load(profile_id: str, user: dict = Depends(accounts.require_user)):
    with accounts.connection() as db:
        row = db.execute(
            "SELECT id,name,saved_at,profile_json FROM profiles WHERE id = ? AND user_id = ?",
            (profile_id, user["id"]),
        ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="经历库不存在")
    return {
        "ok": True,
        "profile": json.loads(row["profile_json"]),
        "meta": {**{key: row[key] for key in ("id", "name", "saved_at")}, "revision": revision(row)},
    }


@router.delete("/{profile_id}")
def delete(profile_id: str, user: dict = Depends(accounts.require_user)):
    with accounts.connection() as db:
        deleted = db.execute(
            "DELETE FROM profiles WHERE id = ? AND user_id = ?", (profile_id, user["id"])
        ).rowcount
    if not deleted:
        raise HTTPException(status_code=404, detail="经历库不存在")
    events.emit("profile_deleted", id=profile_id)
    return {"ok": True, "deleted": profile_id}


@router.patch("/{profile_id}", dependencies=[Depends(accounts.require_csrf)])
def update(profile_id: str, req: UpdateRequest, user: dict = Depends(accounts.require_user)):
    name = req.name.strip()
    if not name:
        raise HTTPException(status_code=422, detail="经历库名称不能为空")
    profile_json = None
    if req.profile is not None:
        if not req.profile.experiences or any(not exp.name.strip() or not any(line.strip() for line in exp.actions + exp.results) for exp in req.profile.experiences):
            raise HTTPException(status_code=422, detail="每段经历需有名称和至少一项行动或成果")
        profile_json = encode_record(req.profile.model_dump(), MAX_WORKSPACE_BYTES)
    with accounts.connection() as db:
        row = db.execute("SELECT name,saved_at,profile_json FROM profiles WHERE id=? AND user_id=?", (profile_id, user["id"])).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="经历库不存在")
        if revision(row) != req.expected_revision:
            raise HTTPException(status_code=409, detail="经历库已在其他页面修改，请重新查看后再保存")
        saved_at = timestamp()
        content = profile_json if profile_json is not None else row["profile_json"]
        count = len(json.loads(content)["experiences"])
        changed = db.execute("UPDATE profiles SET name=?,saved_at=?,profile_json=?,experience_count=? WHERE id=? AND user_id=? AND name=? AND saved_at=? AND profile_json=?", (name, saved_at, content, count, profile_id, user["id"], row["name"], row["saved_at"], row["profile_json"])).rowcount
        if not changed:
            raise HTTPException(status_code=409, detail="经历库已变化，请重新查看后再保存")
    events.emit("profile_updated", id=profile_id, experiences=count)
    return {"ok": True, "profile": json.loads(content), "meta": {"id": profile_id, "name": name, "saved_at": saved_at, "revision": revision({"name": name, "saved_at": saved_at, "profile_json": content})}}
