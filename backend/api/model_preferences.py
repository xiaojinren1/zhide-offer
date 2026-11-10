from time import monotonic
from base64 import b64encode
from io import BytesIO
from PIL import Image

import httpx
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field, SecretStr

from core import accounts, model_preferences
from core.llm import LLMError, chat_json, chat_json_multimodal

router = APIRouter(prefix="/api/model-preferences")


class Connection(BaseModel):
    provider: Literal["deepseek", "glm", "custom"]
    base_url: str = Field(default="", max_length=512)
    api_key: SecretStr | None = None


class Preference(Connection):
    migration_user_id: str | None = None
    model: str = Field(min_length=1, max_length=120, pattern=r"^[a-zA-Z0-9][a-zA-Z0-9._:/-]*$")


def connection(request: Request, preference: Connection, user: dict, kind: model_preferences.ModelKind) -> tuple[str, str]:
    if request.url.scheme != "https" and request.url.hostname not in {"localhost", "127.0.0.1", "::1"}:
        raise HTTPException(403, "请通过 HTTPS 使用自定义 API Key")
    url = model_preferences.approved_url(preference.provider, preference.base_url)
    key = preference.api_key.get_secret_value().strip() if preference.api_key else ""
    if not key:
        saved = model_preferences.get_for_user(user, kind)
        if saved and saved["provider"] == preference.provider and saved["base_url"] == url:
            key = model_preferences.key_for(saved)
    if not 1 <= len(key) <= 512 or not all(33 <= ord(char) <= 126 for char in key):
        raise HTTPException(422, "请输入当前供应商和 Base URL 对应的 API Key")
    return url, key


@router.post("/models")
def list_models(request: Request, preference: Connection, user: dict = Depends(accounts.require_user), kind: model_preferences.ModelKind = "text"):
    url, key = connection(request, preference, user, kind)
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
    return {**{field: config[field] for field in ("provider", "model", "base_url")},
            "has_api_key": True}


@router.get("")
def read(user: dict = Depends(accounts.require_user), kind: model_preferences.ModelKind = "text"):
    config = model_preferences.get_for_user(user, kind)
    return public_config(config) if config else None


@router.post("")
def activate(request: Request, preference: Preference, user: dict = Depends(accounts.require_user), kind: model_preferences.ModelKind = "text"):
    user_id = user["id"]
    migration = preference.migration_user_id is not None
    if migration and (kind != "text" or user.get("guest") or preference.migration_user_id != user_id or model_preferences.get_for_user(user, kind)):
        raise HTTPException(409, "账户或模型配置已变化，请刷新后重试")
    cipher = None if user.get("guest") else model_preferences.cipher()
    url, key = connection(request, preference, user, kind)
    try:
        options = dict(model=preference.model, api_key=key, base_url=url, deadline_at=monotonic() + 12)
        if kind == "vision":
            sample = BytesIO()
            Image.new("RGB", (64, 64), "blue").save(sample, format="PNG")
            uri = "data:image/png;base64," + b64encode(sample.getvalue()).decode("ascii")
            chat_json_multimodal("Return a JSON object.", 'Describe the image color in {"color":"..."} format.',
                                 uri, **options)
        else:
            chat_json("Return only a JSON object.", 'Return {"ok": true}.', **options)
    except LLMError:
        message = ("图片测试失败，请确认模型支持图片输入，并核对 API Key、模型 ID 和额度"
                   if kind == "vision" else "连接失败，请核对 API Key、模型 ID 和服务商额度")
        raise HTTPException(502, message) from None
    config = {"user_id": user_id, "provider": preference.provider, "base_url": url, "model": preference.model}
    if cipher is None:
        accounts.require_user(request)
        model_preferences.save_guest(config, key, user["guest_until"], kind)
    else:
        model_preferences.save(config, key, cipher, migration, kind)
    return public_config(config)


@router.post("/reveal")
def reveal(request: Request, response: Response, user: dict = Depends(accounts.require_user), kind: model_preferences.ModelKind = "text"):
    if request.url.scheme != "https" and request.url.hostname not in {"localhost", "127.0.0.1", "::1"}:
        raise HTTPException(403, "请通过 HTTPS 查看 API Key")
    config = model_preferences.get_for_user(user, kind)
    if not config:
        raise HTTPException(404, "当前账户没有已保存的 API Key")
    response.headers["Cache-Control"] = "no-store"
    return {"api_key": model_preferences.key_for(config)}


@router.delete("")
def reset(user: dict = Depends(accounts.require_user), kind: model_preferences.ModelKind = "text"):
    if user.get("guest"):
        model_preferences.clear_guest(user["id"], kind)
    else:
        model_preferences.clear(user["id"], kind)
    return {"ok": True}
