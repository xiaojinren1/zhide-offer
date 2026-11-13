"""Encrypted account model preferences and request-local model context."""
import base64
import binascii
import ipaddress
import os
from contextvars import ContextVar
from urllib.parse import urlsplit
from threading import Lock, Timer
from time import time
from typing import Literal

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from fastapi import Depends, HTTPException, Request
from starlette.concurrency import run_in_threadpool

from core import accounts, model_usage

PROVIDERS = {
    "deepseek": "https://api.deepseek.com",
    "glm": "https://open.bigmodel.cn/api/paas/v4",
}
current_provider: ContextVar[dict | None] = ContextVar("current_provider", default=None)
ModelKind = Literal["text", "vision"]
_TABLES = {"text": "user_model_preferences", "vision": "user_vision_preferences"}
VERSION = b"\x01"
_guest_lock = Lock()
_guest_configs: dict[tuple[str, ModelKind], tuple[dict, Timer]] = {}


def clear_guest(user_id: str, kind: ModelKind | None = None) -> None:
    with _guest_lock:
        for slot in (kind,) if kind else _TABLES:
            entry = _guest_configs.pop((user_id, slot), None)
            if entry:
                entry[1].cancel()


def save_guest(config: dict, key: str, expires_at: float, kind: ModelKind = "text") -> None:
    remaining = expires_at - time()
    if remaining <= 0:
        raise HTTPException(401, "试用会话已到期")
    user_id = config["user_id"]
    slot = (user_id, kind)
    timer = Timer(remaining, clear_guest, args=slot)
    timer.daemon = True
    with _guest_lock:
        previous = _guest_configs.get(slot)
        if previous:
            previous[1].cancel()
        _guest_configs[slot] = ({**config, "temporary_key": key}, timer)
        timer.start()


def get_for_user(user: dict, kind: ModelKind = "text") -> dict | None:
    if not user.get("guest"):
        return get(user["id"], kind)
    with _guest_lock:
        entry = _guest_configs.get((user["id"], kind))
        return entry[0] if entry and user["guest_until"] > time() else None


def key_for(config: dict) -> str:
    return config["temporary_key"] if "temporary_key" in config else decrypt(config)



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


def get(user_id: str, kind: ModelKind = "text") -> dict | None:
    with accounts.connection() as db:
        row = db.execute(f"SELECT * FROM {_TABLES[kind]} WHERE user_id = ?", (user_id,)).fetchone()
    return dict(row) if row else None


def save(config: dict, key: str, encryption: AESGCM, migration: bool, kind: ModelKind = "text") -> None:
    nonce = os.urandom(12)
    blob = VERSION + nonce + encryption.encrypt(nonce, key.encode(), aad(config))
    with accounts.connection() as db:
        conflict = ("DO NOTHING" if migration else "DO UPDATE SET provider=excluded.provider, "
                    "base_url=excluded.base_url, model=excluded.model, key_ciphertext=excluded.key_ciphertext")
        result = db.execute(
            f"INSERT INTO {_TABLES[kind]} VALUES (?, ?, ?, ?, ?) ON CONFLICT(user_id) " + conflict,
            (config["user_id"], config["provider"], config["base_url"], config["model"], blob),
        )
        if not result.rowcount:
            raise HTTPException(409, "已有个人模型配置，请刷新后重试")


def clear(user_id: str, kind: ModelKind = "text") -> None:
    with accounts.connection() as db:
        db.execute(f"DELETE FROM {_TABLES[kind]} WHERE user_id = ?", (user_id,))


# 内网/本机保留地址：自定义端点绝不能指向这里，否则服务端会被当成内网跳板
_INTERNAL_SUFFIXES = (".local", ".internal", ".lan", ".home.arpa", ".localhost",
                      ".localdomain", ".intranet", ".corp", ".svc", ".cluster.local")
_INTERNAL_HOSTNAMES = {"localhost", "metadata", "metadata.google.internal",
                       "instance-data", "kubernetes.default"}


def host_is_public(hostname: str) -> bool:
    """判断主机名是否公网可达：字面 IP 必须 global，域名不得是内网/元数据地址。"""
    host = (hostname or "").strip().lower().rstrip(".")
    if not host or host in _INTERNAL_HOSTNAMES:
        return False
    if host.endswith(_INTERNAL_SUFFIXES):
        return False
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        # 域名允许通过：解析时机留到真正请求时，避免配置阶段依赖 DNS 可用性
        return "." in host
    return address.is_global


def _custom_urls_strict() -> bool:
    """严格模式：只允许白名单里的端点（运维需要对内收紧时打开）。"""
    return os.getenv("JOBAGENT_CUSTOM_MODEL_BASE_URLS_STRICT", "").strip().lower() in {"1", "true", "yes"}


def custom_allowlist() -> set[str]:
    raw = os.getenv("JOBAGENT_CUSTOM_MODEL_BASE_URLS", "")
    return {value.strip().rstrip("/") for value in raw.split(",") if value.strip()}


def approved_url(provider: str, base_url: str) -> str:
    """校验并规范化 Base URL。

    规则（按顺序）：
    1. 服务商预设地址直接通过；
    2. 其余地址必须是合法的 **公网 HTTPS** 端点：不带账号密码、query、fragment，
       不是内网/本机/云元数据地址，也不允许直接填 `/chat/completions`；
    3. 只有显式打开 `JOBAGENT_CUSTOM_MODEL_BASE_URLS_STRICT=1` 时才要求命中白名单
       （`JOBAGENT_CUSTOM_MODEL_BASE_URLS`）。

    为什么默认不再要求白名单：用户填的是**自己的 Key 和自己的服务商**，cc-switch、OpenCode 这类
    客户端都不限制地址；强制白名单会让"别处能用、这里 422"，而真正的风险（内网跳板）
    用公网地址校验就能挡住。
    """
    preset = PROVIDERS.get(provider)
    url = base_url.strip().rstrip("/") or preset
    deepseek = PROVIDERS["deepseek"]
    if url == f"{deepseek}/v1" and provider in {"deepseek", "custom"}:
        url = deepseek
    if preset and url == preset:
        return url
    if provider == "custom" and url in PROVIDERS.values():
        return url

    if not url:
        raise HTTPException(422, "请填写 Base URL，例如 https://api.example.com/v1")
    try:
        parsed = urlsplit(url)
        valid = (parsed.scheme == "https" and bool(parsed.hostname) and not parsed.username
                 and not parsed.password and not parsed.query and not parsed.fragment
                 and not url.endswith("/chat/completions")
                 and all(33 <= ord(char) <= 126 for char in url) and "\\" not in url)
    except ValueError:
        valid = False
    if not valid:
        raise HTTPException(422, "请输入有效的 HTTPS Base URL（不要带账号密码、查询参数，也不要直接填 /chat/completions）")

    if _custom_urls_strict() and url not in custom_allowlist():
        raise HTTPException(
            422,
            f"站点开启了 Base URL 白名单（严格模式）：{url} 不在名单里。"
            "请联系管理员把它加入 JOBAGENT_CUSTOM_MODEL_BASE_URLS，或关闭严格模式。",
        )
    if not host_is_public(parsed.hostname or ""):
        raise HTTPException(422, f"{parsed.hostname} 是内网或本机地址，不能用于模型端点")
    return url


def resolved_provider() -> dict | None:
    config = current_provider.get()
    if config is None:
        return None
    if "missing_kind" in config:
        label = "图片解析模型" if config["missing_kind"] == "vision" else "文本模型"
        raise HTTPException(428, f"请先在模型设置中配置并启用{label}")
    if config.get("insecure_request"):
        raise HTTPException(403, "请通过 HTTPS 使用个人模型")
    return {"name": config["provider"], "model": config["model"],
            "base_url": approved_url(config["provider"], config["base_url"]), "api_key": key_for(config)}


async def bind(request: Request, user: dict = Depends(accounts.require_user),
               _usage=Depends(model_usage.bind)):
    kind: ModelKind = "vision" if request.url.path.rstrip("/").endswith(("/parse-image", "/template-image")) else "text"
    config = await run_in_threadpool(get_for_user, user, kind)
    if config and request.url.scheme != "https" and request.url.hostname not in {"localhost", "127.0.0.1", "::1"}:
        config = {**config, "insecure_request": True}
    token = current_provider.set(config or {"missing_kind": kind})
    try:
        yield
    finally:
        current_provider.reset(token)
