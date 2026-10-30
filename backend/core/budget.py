"""token 计量（从 ARC 老框架 agents/model/token_budget.py 移植，只留计量不设上限）。

沿用 v20m 决策：预算上限整体废除（mode=off），只做计量与用量报告——
不拦截、不抛异常，避免"预算撞顶提前停止"把整棵树截断。
"""
from __future__ import annotations

import json
import os
import threading
from typing import Any

try:  # fcntl 仅 Unix 有；Windows 开发机走纯内存累计
    import fcntl

    _HAVE_FCNTL = True
except Exception:  # pragma: no cover
    _HAVE_FCNTL = False

_lock = threading.Lock()
_state: dict[str, Any] = {
    "mode": "mem",  # mem | file（off 已废除：上限恒为 0，只计量）
    "file": None,
    "used": 0,
    "calls": 0,
    "prompt_tokens": 0,
    "completion_tokens": 0,
    "inited": False,
}


def configure_from_env() -> None:
    """Read config from env once. 上限恒为 0（不拦截），只决定计数落盘位置。"""
    if _state["inited"]:
        return
    with _lock:
        if _state["inited"]:
            return
        _state["file"] = (os.environ.get("JOBAGENT_TOKEN_FILE") or "").strip() or None
        _state["mode"] = "file" if _state["file"] else "mem"
        _state["inited"] = True


def record(prompt_tokens: int, completion_tokens: int) -> None:
    """Record usage. 永不抛异常——上限已废除（v20m 决策）。"""
    configure_from_env()
    add = (prompt_tokens or 0) + (completion_tokens or 0)
    if add <= 0:
        return
    if _state["mode"] == "file":
        path = _state["file"]
        for _ in range(5):
            try:
                with open(path, "a+", encoding="utf-8") as fh:
                    if _HAVE_FCNTL:
                        fcntl.flock(fh, fcntl.LOCK_EX)
                    try:
                        fh.seek(0)
                        try:
                            data = json.load(fh)
                        except Exception:
                            data = {"used": 0, "calls": 0}
                        data["used"] = int(data.get("used", 0)) + add
                        data["calls"] = int(data.get("calls", 0)) + 1
                        fh.seek(0)
                        fh.truncate()
                        json.dump(data, fh)
                    finally:
                        if _HAVE_FCNTL:
                            fcntl.flock(fh, fcntl.LOCK_UN)
                return
            except Exception:
                continue
        return
    with _lock:
        _state["used"] += add
        _state["calls"] += 1
        _state["prompt_tokens"] += int(prompt_tokens or 0)
        _state["completion_tokens"] += int(completion_tokens or 0)


def get_usage() -> dict[str, Any]:
    """Report usage. limit 恒为 0（不设上限），used 是真实累计。"""
    configure_from_env()
    if _state["mode"] == "file" and _state["file"]:
        try:
            with open(_state["file"], "r", encoding="utf-8") as fh:
                data = json.load(fh)
            return {
                "mode": "file",
                "used": int(data.get("used", 0)),
                "calls": int(data.get("calls", 0)),
                "limit": 0,
            }
        except Exception:
            pass
    with _lock:
        return {
            "mode": "mem",
            "used": _state["used"],
            "calls": _state["calls"],
            "prompt_tokens": _state["prompt_tokens"],
            "completion_tokens": _state["completion_tokens"],
            "limit": 0,
        }


def reset() -> None:
    """Test helper: zero the in-memory counters."""
    with _lock:
        _state.update({"used": 0, "calls": 0, "prompt_tokens": 0, "completion_tokens": 0})
