"""注册、登录及当前会话入口，不返回密码摘要或会话令牌。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, Field

from core import accounts

router = APIRouter(prefix="/api/auth", tags=["auth"], dependencies=[Depends(accounts.require_csrf)])


class Credentials(BaseModel):
    username: str = Field(min_length=3, max_length=32, pattern=r"^[A-Za-z0-9_]+\z", strict=True)
    password: str = Field(min_length=8, max_length=128, strict=True)


def _set_session(request: Request, response: Response, token: str) -> None:
    response.set_cookie(
        accounts.COOKIE_NAME, token, max_age=accounts.SESSION_SECONDS,
        httponly=True, secure=request.url.scheme == "https", samesite="strict", path="/",
    )


@router.post("/register")
def register(req: Credentials, request: Request, response: Response):
    user, token = accounts.register(req.username, req.password)
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


@router.post("/logout")
def logout(request: Request, response: Response):
    accounts.logout(request.cookies.get(accounts.COOKIE_NAME))
    response.delete_cookie(
        accounts.COOKIE_NAME, path="/", httponly=True,
        secure=request.url.scheme == "https", samesite="strict",
    )
    return {"ok": True}
