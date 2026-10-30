"""应用配置与 .env 加载（从 ARC 老框架 main.py 的 _load_dotenv() 整函数复用）。

GOSIM 教训（v20l 真根因）：平台不会替你 source .env，且依赖错误的 repo_root
计算会去上一级目录找文件。这里从"脚本实际所在目录"加载，平台已设的环境变量
优先（override=False），python-dotenv 不可用时降级为手写解析器。
"""
from __future__ import annotations

import os
from pathlib import Path
from functools import lru_cache

_HERE = Path(__file__).resolve().parent
BACKEND_ROOT = _HERE.parent
PROJECT_ROOT = BACKEND_ROOT.parent


def _load_dotenv() -> None:
    """Robustly load the project .env so MODEL / api_key / base_url take effect."""
    candidates = []
    _custom = os.environ.get("JOBAGENT_ENV_FILE", "").strip()
    if _custom:
        candidates.append(Path(_custom))
    candidates += [
        BACKEND_ROOT / ".env",
        Path(os.getcwd()) / ".env",
        PROJECT_ROOT / ".env",
    ]
    env_path = next((p for p in candidates if p.is_file()), None)
    if not env_path:
        return
    try:
        from dotenv import load_dotenv

        load_dotenv(str(env_path), override=False)
        return
    except Exception:
        pass
    # Minimal parser: only fill keys not already present in the environment.
    try:
        with open(env_path, "r", encoding="utf-8") as fh:
            for _line in fh:
                _line = _line.strip()
                if not _line or _line.startswith("#") or "=" not in _line:
                    continue
                _k, _, _v = _line.partition("=")
                _k, _v = _k.strip(), _v.strip()
                if _k and _k not in os.environ:
                    os.environ[_k] = _v
    except Exception:
        pass


@lru_cache(maxsize=1)
def settings() -> dict:
    """Resolve runtime settings once. Env vars always win over .env."""
    _load_dotenv()
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
        "port": int(os.environ.get("JOBAGENT_PORT") or 8000),
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
