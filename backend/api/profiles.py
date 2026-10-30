"""登录账户的经历库；所有读写均由服务端当前用户限定归属。"""
from __future__ import annotations

import json
import re
import time
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from core import accounts, events

router = APIRouter(prefix="/api/profiles", tags=["profiles"])


class SaveRequest(BaseModel):
    name: str = ""
    profile: dict


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
        "meta": {key: row[key] for key in ("id", "name", "saved_at")},
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
