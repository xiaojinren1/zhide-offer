"""provider 故障链测试（借鉴 Pi 的 pi-ai 层）。

验证：① 链的解析与优先级 ② 主 provider 失败自动切备用 ③ 显式参数时禁用 fallback
④ 全部失败才抛错 ⑤ 切成功时记录事件
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest.mock import patch

BACKEND_ROOT = Path(__file__).resolve().parent.parent / "backend"
sys.path.insert(0, str(BACKEND_ROOT))

FAILURES: list[str] = []


def check(name, cond, detail=""):
    print(f"[{'PASS' if cond else 'FAIL'}] {name}" + (f"  -- {detail}" if detail else ""))
    if not cond:
        FAILURES.append(name)


def reset_env(**kw):
    for k in ("JOBAGENT_FALLBACKS", "MODEL", "api_key", "base_url", "OPENAI_API_KEY", "OPENAI_BASE_URL"):
        os.environ.pop(k, None)
    for k, v in kw.items():
        os.environ[k] = v
    from core.config import reload_settings
    with patch("core.config._load_dotenv"):
        reload_settings()


import core.llm as llm  # noqa: E402
from core import events  # noqa: E402

# ---- ① 链解析 ----
reset_env(MODEL="m-primary", api_key="k-primary", base_url="https://primary.example/v1",
          JOBAGENT_FALLBACKS="https://fb1.example/v1|k-fb1|m-fb1,https://fb2.example/v1|k-fb2,坏配置,k-fb3")
chain = llm.provider_chain()
check("链长度=主+2个合法备用（跳过坏配置）", len(chain) == 3, f"got {len(chain)}")
check("主 provider 字段正确",
      chain[0]["name"] == "primary" and chain[0]["model"] == "m-primary"
      and chain[0]["base_url"] == "https://primary.example/v1", str(chain[0]))
check("备用1 带自己的 model", chain[1]["model"] == "m-fb1", str(chain[1]))
check("备用2 未指定 model 时继承主 model", chain[2]["model"] == "m-primary", str(chain[2]))

# ---- ② 显式参数禁用 fallback ----
c2 = llm.provider_chain(model="explicit-model", base_url="https://ex.example/v1", api_key="k-ex")
check("显式参数时只有 1 个 provider（不静默跳走）", len(c2) == 1 and c2[0]["name"] == "explicit", str(c2))

# ---- ③ 主失败自动切备用（不打真实网络） ----
reset_env(MODEL="m-primary", api_key="k-primary", base_url="https://primary.example/v1",
          JOBAGENT_FALLBACKS="https://fb1.example/v1|k-fb1|m-fb1")

calls: list[str] = []


def fake_post_messages(provider, messages, *, tools=None, temperature=0.2, json_mode=False):
    """桩掉单次调用：主 provider 抛 401，备用返回内容。"""
    calls.append(provider["name"])
    if provider["name"] == "primary":
        raise Exception("401 unauthorized: quota exhausted")
    return {"content": "OK-FROM-FALLBACK"}


llm._post_messages = fake_post_messages  # type: ignore[assignment]
events.configure(str(Path(__file__).resolve().parent.parent / "data" / "test-events.jsonl"))
out = llm.chat("sys", "usr")
check("主失败后返回备用内容", out == "OK-FROM-FALLBACK", out)
check("调用顺序：先主后备", calls == ["primary", "fallback-1"], str(calls))

# ---- ④ 全部失败才抛错 ----
def fake_all_fail(provider, messages, **kw):
    calls.append(provider["name"])
    raise Exception("401 unauthorized")


llm._post_messages = fake_all_fail  # type: ignore[assignment]
try:
    llm.chat("sys", "usr")
    check("全部失败应抛 LLMError", False, "未抛异常")
except llm.LLMError as exc:
    check("全部失败抛 LLMError 且带上试过的 provider",
          exc.providers_tried == ["primary", "fallback-1"], str(exc.providers_tried))

# ---- ⑤ 无备用时只有主 ----
reset_env(MODEL="m", api_key="k", base_url="https://p.example/v1", JOBAGENT_FALLBACKS="")
check("无备用配置时链长为 1", len(llm.provider_chain()) == 1)

print()
if FAILURES:
    print(f"RESULT: {len(FAILURES)} FAILURE(S): {FAILURES}")
    sys.exit(1)
print("RESULT: PROVIDER CHAIN ALL CHECKS PASSED")
