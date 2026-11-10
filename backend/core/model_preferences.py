"""Session-scoped configuration for approved text model providers."""
from contextvars import ContextVar
from threading import Lock
from time import monotonic

from fastapi import Request

from core import accounts

PROVIDERS = {
    "deepseek": "https://api.deepseek.com",
    "glm": "https://open.bigmodel.cn/api/paas/v4",
}
current_provider: ContextVar[dict | None] = ContextVar("current_provider", default=None)
_configs: dict[str, tuple[float, dict]] = {}
_lock = Lock()


def session_id(request: Request) -> str:
    return accounts.token_hash(request.cookies[accounts.COOKIE_NAME])


def get(request: Request) -> dict | None:
    with _lock:
        key = session_id(request)
        entry = _configs.get(key)
        if entry and entry[0] > monotonic():
            return entry[1]
        _configs.pop(key, None)
        return None


def save(request: Request, provider: dict) -> None:
    with _lock:
        now = monotonic()
        for key, (expires, _) in list(_configs.items()):
            if expires <= now:
                del _configs[key]
        _configs[session_id(request)] = (now + 7 * 86400, provider)


def clear(request: Request) -> None:
    with _lock:
        if accounts.COOKIE_NAME in request.cookies:
            _configs.pop(session_id(request), None)


async def bind(request: Request):
    token = current_provider.set(None if request.url.path == "/api/resume/parse-image" else get(request))
    try:
        yield
    finally:
        current_provider.reset(token)
