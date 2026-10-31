"""LLM 客户端（ARC 老框架移植 + 借鉴 Pi 的 pi-ai 层 + 工具调用循环）。

三条主线：
1. **保命**：瞬时限错误指数退避 + 多 provider 故障链（Pi 的 pi-ai 层思路）
2. **可信**：JSON 模式强制可解析；token 用量全量计量
3. **自主**：chat_with_tools 提供工具调用循环——模型可调用确定性工具
   （如质检器）并据结果自我修订，对应"反思/自纠错"与"失败换方案"
"""
from __future__ import annotations

import json
import os
import random
import time as _time
from typing import Any, Callable

import httpx

from core import budget, events
from core.config import settings

# 分级超时：连接/池快速失败，读给足时间（原来 blanket 240s，连不通也要等 4 分钟）
_HTTP_TIMEOUT = httpx.Timeout(connect=8.0, read=90.0, write=30.0, pool=8.0)

# 双层墙钟：
#   JOBAGENT_LLM_DEADLINE  单次 provider 链的最长耗时（秒），到点明确失败而非磨完重试
#   JOBAGENT_FLOW_DEADLINE  chat_with_tools 全流程（含多轮自检修订）的总预算（秒）
def _chain_deadline() -> float:
    try:
        return float(os.environ.get("JOBAGENT_LLM_DEADLINE") or 100)
    except ValueError:
        return 100.0


def _flow_deadline() -> float:
    try:
        return float(os.environ.get("JOBAGENT_FLOW_DEADLINE") or 150)
    except ValueError:
        return 150.0

_TRANSIENT_NETWORK_SIGNATURES = (
    "proxy_error", "connection reset by peer", "read tcp", "connection aborted",
    "remotedisconnected", "econnreset", "broken pipe", "socket hang up",
    "upstream connect error", "network is unreachable", "tls handshake",
    "timeout", "timed out", "429", "502", "503", "504",
)


class LLMError(RuntimeError):
    """模型调用最终失败（所有 provider 都已尝试）。"""

    def __init__(self, message: str, *, providers_tried: list[str] | None = None,
                 status_code: int = 503):
        super().__init__(message)
        self.providers_tried = providers_tried or []
        self.status_code = status_code


def _is_transient_network_error(exc: Exception) -> bool:
    if isinstance(exc, httpx.HTTPStatusError):
        return False
    if isinstance(exc, httpx.TransportError):
        return True
    if isinstance(exc, LLMError):
        return False
    msg = str(exc).lower()
    return any(sig in msg for sig in _TRANSIENT_NETWORK_SIGNATURES)


def _is_retryable_status(exc: Exception) -> bool:
    return isinstance(exc, httpx.HTTPStatusError) and (
        exc.response.status_code == 429 or exc.response.status_code >= 500
    )


def _failure_status(exc: Exception | None) -> int:
    """仅使用结构化异常分类；上游鉴权不是应用账户失效。"""
    if isinstance(exc, LLMError):
        return exc.status_code
    if isinstance(exc, httpx.TimeoutException):
        return 504
    if isinstance(exc, httpx.HTTPStatusError):
        if exc.response.status_code == 429:
            return 429
        if exc.response.status_code in (408, 504):
            return 504
    return 503


# --------------------------------------------------------------------------
# Provider 链
# --------------------------------------------------------------------------

def _parse_fallbacks(raw: str) -> list[dict]:
    """解析 JOBAGENT_FALLBACKS：`base_url|api_key|model`，多个用逗号分隔。

    容错：任何一段格式不对就跳过，绝不让一个坏配置拖垮整条链。
    """
    out: list[dict] = []
    for chunk in (raw or "").split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        parts = [p.strip() for p in chunk.split("|")]
        if len(parts) < 2 or not parts[0] or not parts[1]:
            continue
        out.append({
            "name": f"fallback-{len(out) + 1}",
            "base_url": parts[0].rstrip("/"),
            "api_key": parts[1],
            "model": parts[2] if len(parts) > 2 and parts[2] else "",
        })
    return out


def provider_chain(
    *,
    model: str | None = None,
    api_key: str | None = None,
    base_url: str | None = None,
) -> list[dict]:
    """按优先级排列的 provider 链（主 + 备用）。

    显式参数优先级最高，会覆盖主 provider 并**禁用** fallback
    （调用方明确指定了端点时，不该静默跳到别处）。
    """
    if (model or api_key or base_url):
        cfg = settings()
        return [{
            "name": "explicit",
            "base_url": (base_url or cfg["base_url"]).rstrip("/"),
            "api_key": (api_key or cfg["api_key"]).strip(),
            "model": (model or cfg["model"]).strip(),
        }]

    cfg = settings()
    primary = {
        "name": "primary",
        "base_url": cfg["base_url"].rstrip("/"),
        "api_key": cfg["api_key"],
        "model": cfg["model"],
    }
    fallbacks = _parse_fallbacks(os.environ.get("JOBAGENT_FALLBACKS", ""))
    for fb in fallbacks:
        if not fb["model"]:
            fb["model"] = cfg["model"]
    return [primary] + fallbacks


def _run_with_providers(
    call_once: Callable[[dict], Any],
    *,
    model: str | None = None,
    api_key: str | None = None,
    base_url: str | None = None,
    deadline: float | None = None,
) -> Any:
    """统一的重试 + 故障切换 + 墙钟外壳。

    call_once(provider) 完成一次调用（含 budget.record）。同一 provider 内对
    瞬时限错误指数退避；不可重试或重试耗尽 → 换下一个 provider。
    deadline：整条链的最长耗时（秒），到点直接抛 LLMError，不再磨完剩余重试
    ——现场演示最怕"转圈 3 分钟然后悄悄失败"。
    """
    budget_s = deadline if deadline is not None else _chain_deadline()
    chain = provider_chain(model=model, api_key=api_key, base_url=base_url)
    tried: list[str] = []
    last_exc: Exception | None = None
    started = _time.monotonic()

    for provider in chain:
        tried.append(provider["name"])
        for attempt in range(8):
            elapsed = _time.monotonic() - started
            if elapsed >= budget_s:
                events.emit("llm_chain_deadline", provider=provider["name"],
                            elapsed=round(elapsed, 1), budget=budget_s)
                raise LLMError(
                    "llm deadline exceeded",
                    providers_tried=tried, status_code=504,
                ) from last_exc
            try:
                result = call_once(provider)
                if provider["name"] != "primary":
                    events.emit("llm_failover_ok", provider=provider["name"],
                                after_attempts=attempt + 1)
                return result
            except Exception as exc:
                last_exc = exc
                retryable = _is_transient_network_error(exc) or _is_retryable_status(exc)
                if retryable and attempt < 7:
                    remaining = budget_s - (_time.monotonic() - started)
                    if remaining <= 0:
                        raise LLMError(
                            "llm deadline exceeded",
                            providers_tried=tried, status_code=504,
                        ) from exc
                    # 退避不超过剩余预算，避免"睡过头"
                    _time.sleep(min(min(2 ** attempt, 30) + random.uniform(0, 1), remaining))
                    continue
                events.emit("llm_provider_failed", provider=provider["name"],
                            attempt=attempt + 1, status_code=_failure_status(exc))
                break

    raise LLMError(
        "all model providers failed",
        providers_tried=tried, status_code=_failure_status(last_exc),
    ) from last_exc


# --------------------------------------------------------------------------
# 单次调用
# --------------------------------------------------------------------------

def _estimate_tokens(text: str) -> int:
    """无 usage 字段时的保守估算：约 3 字符 1 token（偏向多算，安全方向）。"""
    return max(1, len(text or "") // 3)


def _post_messages(
    provider: dict,
    messages: list[dict],
    *,
    tools: list[dict] | None = None,
    temperature: float = 0.2,
    json_mode: bool = False,
) -> dict:
    """单次 chat/completions 调用，返回原始 message dict。"""
    headers = {"Content-Type": "application/json"}
    if provider.get("api_key"):
        headers["Authorization"] = f"Bearer {provider['api_key']}"
    payload: dict[str, Any] = {
        "model": provider["model"],
        "messages": messages,
        "temperature": temperature,
        "stream": False,
    }
    if json_mode:
        payload["response_format"] = {"type": "json_object"}
    if tools:
        payload["tools"] = tools
        payload["tool_choice"] = "auto"

    base = provider["base_url"]
    url = base if base.endswith("/chat/completions") else f"{base}/chat/completions"
    with httpx.Client(timeout=_HTTP_TIMEOUT) as client:
        resp = client.post(url, headers=headers, json=payload)
    resp.raise_for_status()
    try:
        data = resp.json()
        if not isinstance(data, dict):
            raise ValueError("response must be an object")
        choices = data.get("choices")
        if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
            raise ValueError("response choices missing")
        msg = choices[0].get("message")
        if not isinstance(msg, dict):
            raise ValueError("response message missing")
        content = msg.get("content")
        if content is not None and not isinstance(content, str):
            raise ValueError("response content must be text")
        calls = msg.get("tool_calls") or []
        if not isinstance(calls, list) or any(
            not isinstance(call, dict)
            or not isinstance(call.get("id"), str) or not call["id"]
            or not isinstance(call.get("function"), dict)
            or not isinstance(call["function"].get("name"), str) or not call["function"]["name"]
            or not isinstance(call["function"].get("arguments"), str)
            for call in calls
        ):
            raise ValueError("invalid response tool calls")
        if not json_mode and not (content or "").strip() and not calls:
            raise ValueError("empty response content")
        usage = data.get("usage") or {}
        if not isinstance(usage, dict):
            raise ValueError("response usage must be an object")
        prompt_tokens = int(usage.get("prompt_tokens") or 0)
        completion_tokens = int(usage.get("completion_tokens") or 0)
    except (ValueError, TypeError) as exc:
        raise LLMError("invalid model response", status_code=502) from exc
    in_text = " ".join(str(m.get("content") or "") for m in messages)
    pt = prompt_tokens or _estimate_tokens(in_text)
    ct = completion_tokens or _estimate_tokens(str(msg.get("content") or ""))
    budget.record(pt, ct)
    return msg


# --------------------------------------------------------------------------
# 公开 API
# --------------------------------------------------------------------------

def chat(
    system: str,
    user: str,
    *,
    temperature: float = 0.2,
    json_mode: bool = False,
    model: str | None = None,
    api_key: str | None = None,
    base_url: str | None = None,
) -> str:
    """普通文本调用。用量自动计量；provider 故障自动切换。"""
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]
    msg = _run_with_providers(
        lambda p: _post_messages(p, messages, temperature=temperature, json_mode=json_mode),
        model=model, api_key=api_key, base_url=base_url,
    )
    content = str(msg.get("content") or "")
    if not content.strip():
        raise LLMError("empty model response", status_code=502)
    return content


def chat_json(
    system: str,
    user: str,
    *,
    temperature: float = 0.2,
    model: str | None = None,
    api_key: str | None = None,
    base_url: str | None = None,
) -> dict:
    """JSON 调用。强制 json_object 模式；解析失败带错误信息重试一次。

    防幻觉第一关：拿不到可解析 JSON 就明说失败，不返回半成品。
    """
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]
    msg = _run_with_providers(
        lambda p: _post_messages(p, messages, temperature=temperature, json_mode=True),
        model=model, api_key=api_key, base_url=base_url,
    )
    content = str(msg.get("content") or "")
    def parse_object(value: str) -> dict:
        data = json.loads(value)
        if not isinstance(data, dict):
            raise ValueError("model JSON must be an object")
        return data

    try:
        return parse_object(content)
    except ValueError:
        retry_messages = messages + [
            {"role": "assistant", "content": content},
            {"role": "user", "content": "[SYSTEM] 上次返回不是合法 JSON，请只输出 JSON，不要 markdown 代码块。"},
        ]
        msg2 = _run_with_providers(
            lambda p: _post_messages(p, retry_messages, temperature=0.0, json_mode=True),
            model=model, api_key=api_key, base_url=base_url,
        )
        try:
            return parse_object(str(msg2.get("content") or ""))
        except ValueError as exc:
            raise LLMError("model did not return a valid JSON object", status_code=502) from exc


def chat_with_tools(
    system: str,
    user: str,
    *,
    tools: list[dict],
    executor: Callable[[str, dict], dict],
    max_rounds: int = 3,
    temperature: float = 0.3,
    flow_deadline: float | None = None,
    model: str | None = None,
    api_key: str | None = None,
    base_url: str | None = None,
) -> dict:
    """带工具调用的生成循环（反思/自纠错的载体）。

    流程：生成 → 模型决定调用工具 → 执行并把结果回给模型 → 模型据结果修订
    → 直到不再调用工具（或达到 max_rounds / flow_deadline）。

    双层墙钟：整流程 flow_deadline（默认 150s）封顶，每轮再受单链墙钟约束。
    流程预算或轮次耗尽时保留草稿并标记 deadline_hit，由调用方拒绝交付；
    模型调用本身失败则传播 LLMError，保留限流、服务不可用或超时分类。

    返回 {content, rounds, tool_calls, final_tool_result, deadline_hit}。
    """
    flow_budget = flow_deadline if flow_deadline is not None else _flow_deadline()
    flow_started = _time.monotonic()
    messages: list[dict] = [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]
    tool_calls_made: list[str] = []
    last_result: dict | None = None
    last_content = ""

    rounds_done = 0
    for round_no in range(max_rounds):
        remaining = flow_budget - (_time.monotonic() - flow_started)
        # 首轮无论如何都要跑：此时手里还没有任何内容，跳过就等于空手而归。
        # 之后的轮次只在剩余预算够用时继续（5s 是"还够改一版"的经验下界）。
        if round_no > 0 and remaining <= 5:
            events.emit("llm_flow_deadline", rounds_done=round_no,
                        elapsed=round(_time.monotonic() - flow_started, 1))
            break
        rounds_done = round_no + 1
        use_tools = round_no < max_rounds - 1
        if not use_tools:
            messages.append({"role": "user", "content": "工具检查轮次已结束。请立即按原始任务要求交付最终完整产物；仅使用已有事实，原始资料缺失的事实不得推断或补造。不要输出思考、工具讨论或继续修订的计划。"})
        # 下限 1s：预算可能已被前序环节吃尽，仍给一个最小的尝试窗口，
        # 而不是把负数/0 当成 deadline 传下去（那会连一次请求都发不出就失败）。
        per_round_budget = max(1.0, min(_chain_deadline(), remaining))
        try:
            msg = _run_with_providers(
                lambda p: _post_messages(p, messages, tools=tools if use_tools else None,
                                         temperature=temperature),
                model=model, api_key=api_key, base_url=base_url,
                deadline=per_round_budget,
            )
        except LLMError as exc:
            events.emit("llm_tool_round_failed", status_code=exc.status_code, round=round_no)
            raise
        content = str(msg.get("content") or "")
        if content.strip():
            last_content = content
        calls = msg.get("tool_calls") or []
        if not calls:
            return {
                "content": content,
                "rounds": round_no + 1,
                "tool_calls": tool_calls_made,
                "final_tool_result": last_result,
                "deadline_hit": False,
            }

        messages.append({"role": "assistant", "content": content, "tool_calls": calls})
        for call in calls:
            fn = (call.get("function") or {})
            name = str(fn.get("name") or "")
            tool_calls_made.append(name)
            try:
                args = json.loads(fn.get("arguments") or "{}")
            except Exception:
                args = {}
            try:
                result = executor(name, args)
            except Exception as exc:  # 执行器本身不该炸，双保险
                result = {"error": f"tool executor crashed: {exc}"}
            last_result = result
            messages.append({
                "role": "tool",
                "tool_call_id": str(call.get("id") or ""),
                "content": json.dumps(result, ensure_ascii=False)[:4000],
            })

    # 收尾：模型持续调用工具，或流程预算已不足；调用失败已向上传播。
    remaining = flow_budget - (_time.monotonic() - flow_started)
    if last_content.strip() and remaining > 5:
        # 还有时间：最后一轮不给工具，逼它基于已有信息收尾
        try:
            final = _run_with_providers(
                lambda p: _post_messages(p, messages, temperature=temperature),
                model=model, api_key=api_key, base_url=base_url,
                deadline=min(_chain_deadline(), remaining),
            )
            last_content = str(final.get("content") or "") or last_content
        except LLMError as exc:
            events.emit("llm_tool_final_failed", status_code=exc.status_code)
            raise
    elif last_content.strip():
        events.emit("llm_flow_degraded", rounds=max_rounds,
                    note="超时，返回已产出的最好内容而非报错")

    return {
        "content": last_content,
        "rounds": rounds_done,
        "tool_calls": tool_calls_made,
        "final_tool_result": last_result,
        "deadline_hit": True,
    }


def is_configured() -> bool:
    """是否具备调用条件（链上任一 provider 有 api_key）。"""
    return any(p.get("api_key") for p in provider_chain())
