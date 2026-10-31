"""注册、登录及当前会话入口，不返回密码摘要或会话令牌。"""
from __future__ import annotations

from io import BytesIO

from fastapi import APIRouter, Depends, File, HTTPException, Request, Response, UploadFile
from pydantic import BaseModel, Field
from PIL import Image, UnidentifiedImageError
from fastapi.responses import Response as ImageResponse

from core import accounts

router = APIRouter(prefix="/api/auth", tags=["auth"], dependencies=[Depends(accounts.require_csrf)])


class Credentials(BaseModel):
    username: str = Field(min_length=3, max_length=32, pattern=r"^[A-Za-z0-9_]+\z", strict=True)
    password: str = Field(min_length=8, max_length=128, strict=True)


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(min_length=8, max_length=128, strict=True)
    new_password: str = Field(min_length=8, max_length=128, strict=True)


class ResetPasswordRequest(BaseModel):
    username: str = Field(min_length=3, max_length=32, pattern=r"^[A-Za-z0-9_]+\z", strict=True)
    recovery_code: str = Field(min_length=8, max_length=128, strict=True)
    new_password: str = Field(min_length=8, max_length=128, strict=True)


MAX_AVATAR_BYTES = 2 * 1024 * 1024
MAX_AVATAR_DIMENSION = 4096
AVATAR_FORMATS = {"JPEG": "image/jpeg", "PNG": "image/png", "WEBP": "image/webp"}


def _validated_avatar(data: bytes) -> str:
    try:
        with Image.open(BytesIO(data)) as image:
            image.verify()
        with Image.open(BytesIO(data)) as image:
            if image.format not in AVATAR_FORMATS:
                raise HTTPException(status_code=422, detail="头像仅支持 JPEG、PNG 或 WebP")
            if image.width > MAX_AVATAR_DIMENSION or image.height > MAX_AVATAR_DIMENSION:
                raise HTTPException(status_code=422, detail="头像尺寸不能超过 4096×4096")
            image.load()
            return AVATAR_FORMATS[image.format]
    except HTTPException:
        raise
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError, Image.DecompressionBombWarning) as exc:
        raise HTTPException(status_code=422, detail="上传内容不是有效的 JPEG、PNG 或 WebP 图片") from exc


def _set_session(request: Request, response: Response, token: str) -> None:
    response.set_cookie(
        accounts.COOKIE_NAME, token, max_age=accounts.SESSION_SECONDS,
        httponly=True, secure=request.url.scheme == "https", samesite="strict", path="/",
    )


@router.post("/register")
def register(req: Credentials, request: Request, response: Response):
    user, token, recovery_code = accounts.register(req.username, req.password)
    _set_session(request, response, token)
    return {"ok": True, "user": user, "recovery_code": recovery_code}


@router.post("/reset-password")
def reset_password(req: ResetPasswordRequest, request: Request, response: Response):
    user, token = accounts.reset_password(req.username, req.recovery_code, req.new_password)
    _set_session(request, response, token)
    return {"ok": True, "user": user}


@router.post("/login")
def login(req: Credentials, request: Request, response: Response):
    user, token = accounts.login(req.username, req.password)
    _set_session(request, response, token)
    return {"ok": True, "user": user}


@router.get("/me")
def me(user: dict = Depends(accounts.require_user)):
    return {"ok": True, "user": user}


@router.get("/profile")
def get_profile(user: dict = Depends(accounts.require_user)):
    return {"ok": True, "user": accounts.profile(user["id"])}


@router.post("/change-password")
def change_password(req: ChangePasswordRequest, request: Request, response: Response,
                    user: dict = Depends(accounts.require_user)):
    token = accounts.change_password(user["id"], req.current_password, req.new_password)
    _set_session(request, response, token)
    return {"ok": True, "user": {"id": user["id"], "username": user["username"]}}


@router.get("/avatar")
def get_avatar(user: dict = Depends(accounts.require_user)):
    data, content_type = accounts.get_avatar(user["id"])
    return ImageResponse(content=data, media_type=content_type, headers={"Cache-Control": "private, no-store"})


@router.post("/avatar")
async def upload_avatar(file: UploadFile = File(...), user: dict = Depends(accounts.require_user)):
    data = await file.read(MAX_AVATAR_BYTES + 1)
    await file.close()
    if len(data) > MAX_AVATAR_BYTES:
        raise HTTPException(status_code=413, detail="头像文件不能超过 2 MiB")
    content_type = _validated_avatar(data)
    accounts.set_avatar(user["id"], data, content_type)
    return {"ok": True, "avatar_url": "/api/auth/avatar"}


@router.delete("/avatar")
def remove_avatar(user: dict = Depends(accounts.require_user)):
    accounts.delete_avatar(user["id"])
    return {"ok": True}


@router.post("/logout")
def logout(request: Request, response: Response):
    accounts.logout(request.cookies.get(accounts.COOKIE_NAME))
    response.delete_cookie(
        accounts.COOKIE_NAME, path="/", httponly=True,
        secure=request.url.scheme == "https", samesite="strict",
    )
    return {"ok": True}
