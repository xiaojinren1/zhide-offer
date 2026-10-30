"""长期记忆：经历库持久化（跨会话记住用户，不用每次重新上传）。

存储：`<项目>/data/profiles/<id>.json`，纯本地文件，无外部依赖。
安全：id 做路径清洗，杜绝 `../` 穿越；简历内容属个人隐私，只落本地。
"""
from __future__ import annotations

import json
import re
import time
from uuid import uuid4
from pathlib import Path

from fastapi import APIRouter
from pydantic import BaseModel

from core import events
from core.config import PROJECT_ROOT

router = APIRouter(prefix="/api/profiles", tags=["profiles"])

STORE = PROJECT_ROOT / "data" / "profiles"
_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


class SaveRequest(BaseModel):
    name: str = ""
    profile: dict


def _safe_path(profile_id: str) -> Path | None:
    if not _ID_RE.match(profile_id or ""):
        return None
    p = STORE / f"{profile_id}.json"
    try:
        p.resolve().relative_to(STORE.resolve())
    except Exception:
        return None
    return p


def _new_id(name: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9_-]", "", (name or "profile"))[:20] or "profile"
    return f"{slug}-{uuid4().hex}"


@router.post("/save")
def save(req: SaveRequest):
    """保存经历库，返回 id。"""
    if not isinstance(req.profile, dict) or not req.profile.get("experiences"):
        return {"ok": False, "error": "经历库为空，拒绝保存"}
    try:
        STORE.mkdir(parents=True, exist_ok=True)
        pid = _new_id(req.name or str(req.profile.get("name") or ""))
        payload = {
            "id": pid,
            "name": (req.name or str(req.profile.get("name") or "")).strip(),
            "saved_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "experience_count": len(req.profile.get("experiences") or []),
            "profile": req.profile,
        }
        (STORE / f"{pid}.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    except Exception as exc:
        events.emit_error("profile_save", exc)
        return {"ok": False, "error": str(exc)}
    events.emit("profile_saved", id=pid, experiences=payload["experience_count"])
    return {"ok": True, "id": pid, "saved_at": payload["saved_at"]}


@router.get("/list")
def list_profiles():
    """列出已保存的经历库（不含完整内容，避免列表过大）。"""
    out = []
    try:
        if STORE.is_dir():
            for f in sorted(STORE.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
                try:
                    d = json.loads(f.read_text(encoding="utf-8"))
                    out.append({
                        "id": d.get("id") or f.stem,
                        "name": d.get("name") or "",
                        "saved_at": d.get("saved_at") or "",
                        "experience_count": d.get("experience_count") or 0,
                    })
                except Exception:
                    continue
    except Exception as exc:
        events.emit_error("profile_list", exc)
        return {"ok": False, "error": str(exc)}
    return {"ok": True, "profiles": out}


@router.get("/{profile_id}")
def load(profile_id: str):
    """读取一个已保存的经历库。"""
    p = _safe_path(profile_id)
    if p is None or not p.is_file():
        return {"ok": False, "error": f"经历库不存在或 id 非法: {profile_id}"}
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
    except Exception as exc:
        return {"ok": False, "error": f"读取失败: {exc}"}
    return {"ok": True, "profile": d.get("profile") or {}, "meta": {
        "id": d.get("id"), "name": d.get("name"), "saved_at": d.get("saved_at"),
    }}


@router.delete("/{profile_id}")
def delete(profile_id: str):
    """删除一个已保存的经历库（用户数据，仅限本端点显式删除）。"""
    p = _safe_path(profile_id)
    if p is None or not p.is_file():
        return {"ok": False, "error": f"经历库不存在或 id 非法: {profile_id}"}
    try:
        p.unlink()
    except Exception as exc:
        return {"ok": False, "error": str(exc)}
    events.emit("profile_deleted", id=profile_id)
    return {"ok": True, "deleted": profile_id}
