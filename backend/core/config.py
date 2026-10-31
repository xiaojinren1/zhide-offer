"""加载服务端配置，进程环境优先；显式配置文件错误必须阻止启动。"""
from __future__ import annotations

import os
from pathlib import Path
from functools import lru_cache

_HERE = Path(__file__).resolve().parent
BACKEND_ROOT = _HERE.parent
PROJECT_ROOT = BACKEND_ROOT.parent


def _load_dotenv() -> None:
    """指定文件时只加载该文件，否则沿用本地配置查找顺序。"""
    _custom = os.environ.get("JOBAGENT_ENV_FILE", "").strip()
    if _custom:
        env_path = Path(_custom)
    else:
        candidates = [
            BACKEND_ROOT / ".env",
            Path(os.getcwd()) / ".env",
            PROJECT_ROOT / ".env",
        ]
        env_path = next((p for p in candidates if p.is_file()), None)
        if env_path is None:
            return
    from dotenv import load_dotenv

    # 自己打开文件，使缺失、目录误配和权限错误明确传播；不自动改读其他文件。
    with env_path.open("r", encoding="utf-8") as stream:
        load_dotenv(stream=stream, override=False)


@lru_cache(maxsize=1)
def settings() -> dict:
    """Resolve runtime settings once. Env vars always win over .env."""
    _load_dotenv()
    try:
        port = int(os.environ.get("JOBAGENT_PORT") or 8000)
    except ValueError as exc:
        raise ValueError("JOBAGENT_PORT 必须为 1–65535 的整数") from exc
    if not 1 <= port <= 65535:
        raise ValueError("JOBAGENT_PORT 必须为 1–65535 的整数")
    return {
        "model": (os.environ.get("MODEL") or os.environ.get("model") or "deepseek-v4-flash").strip(),
        "api_key": (
            os.environ.get("OPENAI_API_KEY")
            or os.environ.get("api_key")
            or ""
        ).strip(),
        "base_url": (
            os.environ.get("OPENAI_BASE_URL")
            or os.environ.get("base_url")
            or "https://api.openai-next.com/v1"
        ).strip(),
        "host": (os.environ.get("JOBAGENT_HOST") or "127.0.0.1").strip(),
        "port": port,
        # token 预算上限：0 = 不限（只计量）。沿用 ARC v20m 的决策。
        "token_budget": int(os.environ.get("JOBAGENT_TOKEN_BUDGET") or 0),
        "events_path": os.environ.get("JOBAGENT_EVENTS_PATH") or str(PROJECT_ROOT / "data" / "events.jsonl"),
        "data_dir": str(PROJECT_ROOT / "data"),
        # 生成循环轮数上限（工具调用 + 自我修订）
        "tool_rounds": int(os.environ.get("JOBAGENT_TOOL_ROUNDS") or 3),
    }


def agent_rules() -> str:
    """读取 backend/RULES.md（若存在）作为全局行为规则，拼进系统提示词。

    可扩展性机制：改规则不用改代码，编辑 RULES.md 重启即可。
    """
    path = BACKEND_ROOT / "RULES.md"
    if not path.is_file():
        return ""
    try:
        text = path.read_text(encoding="utf-8").strip()
    except Exception:
        return ""
    if not text:
        return ""
    return f"\n\n【项目规则（优先级高于上述通用指令）】\n{text}"


def reload_settings() -> dict:
    """Force-refresh cached settings (used by tests)."""
    settings.cache_clear()
    return settings()
