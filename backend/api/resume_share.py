import json
import secrets

from fastapi import APIRouter, Depends, HTTPException, Path, Response
from pydantic import BaseModel, ConfigDict, Field

from api.workspace import ResumeAppearance, check_account, encode_record, timestamp
from core import accounts

router = APIRouter(prefix="/api/resume-share")
public_router = APIRouter(prefix="/api/shared-resumes")


class OwnerRequest(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")
    expected_user_id: str


class PublishRequest(OwnerRequest):
    markdown: str = Field(min_length=1, max_length=100_000)
    appearance: ResumeAppearance


def require_owner(user: dict = Depends(accounts.require_user)) -> dict:
    if user.get("guest"):
        raise HTTPException(403, "请登录正式账号后发布在线简历")
    return user


@router.get("")
def current_share(response: Response, user: dict = Depends(require_owner)):
    response.headers["Cache-Control"] = "no-store"
    with accounts.connection() as db:
        row = db.execute("SELECT token,published_at FROM resume_shares WHERE user_id = ?", (user["id"],)).fetchone()
    return dict(row) if row else None


@router.post("")
def publish(req: PublishRequest, user: dict = Depends(require_owner)):
    check_account(req.expected_user_id, user)
    if not req.markdown.strip():
        raise HTTPException(422, "请先填写简历正文")
    appearance = req.appearance.model_dump()
    if req.appearance.headerStyle != "portrait":
        appearance.pop("portrait", None)
    snapshot = encode_record({"markdown": req.markdown, "appearance": appearance}, 400_000)
    published_at = timestamp()
    with accounts.connection() as db:
        row = db.execute(
            "INSERT INTO resume_shares(user_id,token,snapshot_json,published_at) VALUES(?,?,?,?) "
            "ON CONFLICT(user_id) DO UPDATE SET snapshot_json=excluded.snapshot_json,published_at=excluded.published_at "
            "RETURNING token,published_at",
            (user["id"], secrets.token_urlsafe(24), snapshot, published_at),
        ).fetchone()
    return dict(row)


@router.post("/revoke")
def revoke(req: OwnerRequest, user: dict = Depends(require_owner)):
    check_account(req.expected_user_id, user)
    with accounts.connection() as db:
        db.execute("DELETE FROM resume_shares WHERE user_id = ?", (user["id"],))
    return {"ok": True}


@public_router.get("/{token}")
def view_share(response: Response, token: str = Path(pattern=r"^[A-Za-z0-9_-]{32}$")):
    headers = {"Cache-Control": "no-store", "X-Robots-Tag": "noindex, nofollow"}
    response.headers.update(headers)
    with accounts.connection() as db:
        row = db.execute("SELECT snapshot_json FROM resume_shares WHERE token = ?", (token,)).fetchone()
    if row is None:
        raise HTTPException(404, "分享链接不存在或已撤回", headers=headers)
    return json.loads(row["snapshot_json"])
