"""结构化事件流（从 ARC 老框架 arcbench_agent_runtime/events.py 移植其核心模式：
append_jsonl + UTC 时间戳；去掉 ARC 专有的需求状态机）。

调试与复盘全靠它：现场演示出问题能按时间戳定位，而不是瞎猜。
"""
from __future__ import annotations

import json
import os
import threading
import time
from typing import Any

_lock = threading.Lock()
_path: str | None = None


def utc_timestamp() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime())


def configure(path: str | None) -> None:
    global _path
    with _lock:
        _path = path


def _append(payload: dict[str, Any]) -> None:
    if not _path:
        return
    try:
        os.makedirs(os.path.dirname(_path) or ".", exist_ok=True)
        with _lock:
            with open(_path, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(payload, ensure_ascii=False) + "\n")
    except Exception:
        pass  # 日志失败绝不能拖垮主流程


def emit(event_type: str, **fields: Any) -> None:
    _append({"type": event_type, "timestamp": utc_timestamp(), **fields})


def emit_error(stage: str, error: str, **fields: Any) -> None:
    _append({"type": "error", "stage": stage, "error": str(error)[:800],
             "timestamp": utc_timestamp(), **fields})


def tail(limit: int = 50) -> list[dict]:
    """Read the last N events (used by /api/health and debugging)."""
    if not _path or not os.path.isfile(_path):
        return []
    try:
        with open(_path, "r", encoding="utf-8") as fh:
            lines = fh.readlines()[-limit:]
        return [json.loads(x) for x in lines if x.strip()]
    except Exception:
        return []
