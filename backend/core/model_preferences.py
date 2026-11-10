"""Encrypted account model preferences and request-local model context."""
import base64
import binascii
import os
from contextvars import ContextVar
from urllib.parse import urlsplit

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from fastapi import Depends, HTTPException, Request
from starlette.concurrency import run_in_threadpool

from core import accounts

PROVIDERS = {
    "deepseek": "https://api.deepseek.com",
    "glm": "https://open.bigmodel.cn/api/paas/v4",
}
current_provider: ContextVar[dict | None] = ContextVar("current_provider", default=None)
VERSION = b"\x01"


def cipher() -> AESGCM:
    try:
        key = base64.b64decode(os.getenv("JOBAGENT_MODEL_ENCRYPTION_KEY", ""), altchars=b"-_", validate=True)
        if len(key) != 32:
            raise ValueError
        return AESGCM(key)
    except (ValueError, binascii.Error):
        raise HTTPException(503, "个人模型加密服务未配置，请联系管理员") from None


def aad(config: dict) -> bytes:
    return VERSION + "\0".join(config[field] for field in ("user_id", "provider", "base_url")).encode()


def decrypt(config: dict) -> str:
    blob = config["key_ciphertext"]
    try:
        if blob[:1] != VERSION:
            raise ValueError
        return cipher().decrypt(blob[1:13], blob[13:], aad(config)).decode()
    except (InvalidTag, ValueError):
        raise HTTPException(503, "个人模型密钥无法解密，请检查服务端配置或重新填写 API Key") from None


def get(user_id: str) -> dict | None:
    with accounts.connection() as db:
        row = db.execute("SELECT * FROM user_model_preferences WHERE user_id = ?", (user_id,)).fetchone()
    return dict(row) if row else None


def save(config: dict, key: str, encryption: AESGCM, migration: bool) -> None:
    nonce = os.urandom(12)
    blob = VERSION + nonce + encryption.encrypt(nonce, key.encode(), aad(config))
    with accounts.connection() as db:
        conflict = ("DO NOTHING" if migration else "DO UPDATE SET provider=excluded.provider, "
                    "base_url=excluded.base_url, model=excluded.model, key_ciphertext=excluded.key_ciphertext")
        result = db.execute(
            "INSERT INTO user_model_preferences VALUES (?, ?, ?, ?, ?) ON CONFLICT(user_id) " + conflict,
            (config["user_id"], config["provider"], config["base_url"], config["model"], blob),
        )
        if not result.rowcount:
            raise HTTPException(409, "已有个人模型配置，请刷新后重试")


def clear(user_id: str) -> None:
    with accounts.connection() as db:
        db.execute("DELETE FROM user_model_preferences WHERE user_id = ?", (user_id,))


def approved_url(provider: str, base_url: str) -> str:
    preset = PROVIDERS.get(provider)
    url = base_url.strip().rstrip("/") or preset
    deepseek = PROVIDERS["deepseek"]
    if url == f"{deepseek}/v1" and provider in {"deepseek", "custom"}:
        url = deepseek
    if (preset and url == preset) or (provider == "custom" and url in PROVIDERS.values()):
        return url
    approved = {value.strip().rstrip("/") for value in os.getenv("JOBAGENT_CUSTOM_MODEL_BASE_URLS", "").split(",")}
    if provider != "custom" or not url or url not in approved:
        raise HTTPException(422, "该 Base URL 未获准使用，请检查地址或联系管理员添加")
    try:
        parsed = urlsplit(url)
        valid = (parsed.scheme == "https" and parsed.hostname and not parsed.username
                 and not parsed.password and not parsed.query and not parsed.fragment
                 and not url.endswith("/chat/completions")
                 and all(33 <= ord(char) <= 126 for char in url) and "\\" not in url)
    except ValueError:
        valid = False
    if not valid:
        raise HTTPException(422, "请输入有效的 HTTPS Base URL")
    return url


def resolved_provider() -> dict | None:
    config = current_provider.get()
    if config is None:
        return None
    if config.get("insecure_request"):
        raise HTTPException(403, "请通过 HTTPS 使用个人模型")
    return {"name": config["provider"], "model": config["model"],
            "base_url": approved_url(config["provider"], config["base_url"]), "api_key": decrypt(config)}


async def bind(request: Request, user: dict = Depends(accounts.require_user)):
    config = await run_in_threadpool(get, user["id"])
    if config and request.url.scheme != "https" and request.url.hostname not in {"localhost", "127.0.0.1", "::1"}:
        config = {**config, "insecure_request": True}
    token = current_provider.set(None if request.url.path == "/api/resume/parse-image" else config)
    try:
        yield
    finally:
        current_provider.reset(token)
