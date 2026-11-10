import os
from time import monotonic
from urllib.parse import urlsplit

import httpx
from typing import Literal

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, Field, SecretStr

from core import model_preferences
from core.llm import LLMError, chat_json

router = APIRouter(prefix="/api/model-preferences")


class Connection(BaseModel):
    provider: Literal["deepseek", "glm", "custom"]
    base_url: str = Field(default="", max_length=512)
    api_key: SecretStr | None = None


class Preference(Connection):
    model: str = Field(min_length=1, max_length=120, pattern=r"^[a-zA-Z0-9][a-zA-Z0-9._:/-]*$")


def connection(request: Request, preference: Connection) -> tuple[str, str]:
    if request.url.scheme != "https" and request.url.hostname not in {"localhost", "127.0.0.1", "::1"}:
        raise HTTPException(403, "请通过 HTTPS 使用自定义 API Key")
    preset = model_preferences.PROVIDERS.get(preference.provider)
    url = preference.base_url.strip().rstrip("/") or preset
    deepseek = model_preferences.PROVIDERS["deepseek"]
    if url == f"{deepseek}/v1" and preference.provider in {"deepseek", "custom"}:
        url = deepseek
    key = preference.api_key.get_secret_value().strip() if preference.api_key else ""
    if not key:
        saved = model_preferences.get(request)
        if saved and saved["base_url"] == url:
            key = saved["api_key"]
    if not 1 <= len(key) <= 512 or not all(33 <= ord(char) <= 126 for char in key):
        raise HTTPException(422, "请输入当前 Base URL 对应的 API Key")

    if (preset and url == preset) or (preference.provider == "custom" and url in model_preferences.PROVIDERS.values()):
        return url, key
    approved = {value.strip().rstrip("/") for value in os.getenv("JOBAGENT_CUSTOM_MODEL_BASE_URLS", "").split(",")}
    if preference.provider != "custom" or not url or url not in approved:
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
    return url, key


@router.post("/models")
def list_models(request: Request, preference: Connection):
    url, key = connection(request, preference)
    try:
        response = httpx.get(f"{url}/models", headers={"Authorization": f"Bearer {key}"},
                             timeout=10, follow_redirects=False)
        response.raise_for_status()
        data = response.json()["data"]
        if not isinstance(data, list):
            raise ValueError("invalid models list")
        models = sorted({item["id"] for item in data if isinstance(item, dict)
                         and isinstance(item.get("id"), str) and 1 <= len(item["id"]) <= 120})
    except httpx.HTTPStatusError as exc:
        status = exc.response.status_code
        messages = {
            401: "服务商拒绝了 API Key，请确认 Key 属于当前 Base URL 且仍然有效。",
            403: "服务商拒绝访问模型列表，请检查 API Key 权限。",
            404: "该 Base URL 的 /models 接口不可用，可以手动填写模型 ID。",
            405: "该服务商不支持通过 /models 获取列表，可以手动填写模型 ID。",
            429: "服务商限制了模型列表请求，请稍后重试。",
        }
        raise HTTPException(502, messages.get(status, f"服务商的模型列表接口返回 HTTP {status}。")) from None
    except httpx.TimeoutException:
        raise HTTPException(504, "连接模型列表接口超时，请稍后重试。") from None
    except httpx.RequestError:
        raise HTTPException(502, "运行职得offer 的服务器无法连接此 Base URL，请检查服务器网络或代理。") from None
    except (ValueError, TypeError, KeyError):
        raise HTTPException(502, "服务商返回的模型列表格式无法识别，可以手动填写模型 ID。") from None
    return {"models": models[:1000]}


def public_config(config: dict) -> dict:
    result = {"provider": config["name"], "model": config["model"]}
    if config["name"] == "custom":
        result["base_url"] = config["base_url"]
    return result


@router.get("")
def read(request: Request):
    config = model_preferences.get(request)
    return public_config(config) if config else None


@router.post("")
def activate(request: Request, preference: Preference):
    url, key = connection(request, preference)
    try:
        chat_json('Return only a JSON object.', 'Return {"ok": true}.',
             model=preference.model, api_key=key, base_url=url, deadline_at=monotonic() + 12)
    except LLMError as exc:
        raise HTTPException(502, "连接失败，请核对 API Key、模型 ID 和服务商额度") from exc
    model_preferences.save(request, {"name": preference.provider, "base_url": url,
                                     "model": preference.model, "api_key": key})
    return read(request)


@router.post("/reveal")
def reveal(request: Request, response: Response):
    if request.url.scheme != "https" and request.url.hostname not in {"localhost", "127.0.0.1", "::1"}:
        raise HTTPException(403, "请通过 HTTPS 查看 API Key")
    config = model_preferences.get(request)
    if not config:
        raise HTTPException(404, "当前会话没有已保存的 API Key")
    response.headers["Cache-Control"] = "no-store"
    return {"api_key": config["api_key"]}


@router.delete("")
def reset(request: Request):
    model_preferences.clear(request)
    return {"ok": True}
