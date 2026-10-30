"""超时与墙钟测试（演示保命：任何 LLM 环节都必须有确定的上界）。

验证：① 分级超时配置正确 ② 单链墙钟到点明确失败 ③ 全流程墙钟超时时
降级返回已产出的最好内容（不空手而归）④ 退避睡眠不超过剩余预算
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parent.parent / "backend"
sys.path.insert(0, str(BACKEND_ROOT))

FAILURES: list[str] = []


def check(name, cond, detail=""):
    print(f"[{'PASS' if cond else 'FAIL'}] {name}" + (f"  -- {detail}" if detail else ""))
    if not cond:
        FAILURES.append(name)


import httpx  # noqa: E402
import core.llm as llm  # noqa: E402
from core import events  # noqa: E402

# ---- ① 分级超时 ----
t = llm._HTTP_TIMEOUT
check("超时是分级配置（connect/read/write/pool 各自取值）", isinstance(t, httpx.Timeout))
check("connect 快速失败（<=10s）", t.connect <= 10, f"connect={t.connect}")
check("read 给足时间（>=60s）", t.read >= 60, f"read={t.read}")
check("不再是 blanket 240s", not (t.connect == 240 and t.read == 240), f"connect={t.connect} read={t.read}")

# ---- ② 单链墙钟：重试中到点明确失败 ----
calls = {"n": 0}


def slow_failing(provider):
    calls["n"] += 1
    time.sleep(0.3)
    raise Exception("503 upstream unavailable")


started = time.monotonic()
try:
    llm._run_with_providers(slow_failing, deadline=1.0)
    check("单链墙钟到点应抛 LLMError", False, "未抛异常")
except llm.LLMError as exc:
    elapsed = time.monotonic() - started
    check("单链墙钟到点抛 LLMError", "deadline" in str(exc).lower(), str(exc)[:80])
    check("墙钟真的生效（<=2s，不会磨完 8 次重试）", elapsed <= 2.0, f"{elapsed:.2f}s")
    check("重试次数被墙钟截断（<8 次）", calls["n"] < 8, f"实际 {calls['n']} 次")

# ---- ③ 全流程墙钟：超时时降级返回最好内容 ----
def slow_with_tool_call(provider, messages, **kw):
    time.sleep(2.0)   # 每轮真实消耗 2s，模拟"模型很慢"
    return {"content": "第一版稿子（尚未修订）", "tool_calls": [
        {"id": "c1", "type": "function",
         "function": {"name": "check_resume_quality", "arguments": "{}"}}]}


llm._post_messages = slow_with_tool_call  # type: ignore[assignment]
events.configure(str(Path(__file__).resolve().parent.parent / "data" / "test-events.jsonl"))

started = time.monotonic()
result = llm.chat_with_tools(
    "sys", "usr",
    tools=[{"type": "function", "function": {"name": "check_resume_quality", "parameters": {}}}],
    executor=lambda n, a: {"ok": True, "issues": []},
    max_rounds=3,
    flow_deadline=3.0,   # 第一轮吃掉 2s，剩下 1s 不够再改一版 → 应停手并交付
)
elapsed = time.monotonic() - started
check("全流程墙钟生效（<=4s，不会跑满 3 轮）", elapsed <= 4.0, f"{elapsed:.2f}s")
check("超时时降级返回已产出的内容（不空手而归）",
      result["content"] == "第一版稿子（尚未修订）", result["content"][:40])
check("超时标记为 deadline_hit", result.get("deadline_hit") is True, str(result.get("deadline_hit")))
check("记录了工具调用痕迹", result["tool_calls"] == ["check_resume_quality"], str(result["tool_calls"]))
check("rounds 报实际执行轮数而非上限", result["rounds"] == 1, str(result["rounds"]))

# ---- ④ 正常路径不受影响（无超时）----
llm._post_messages = lambda provider, messages, **kw: {"content": "正常稿子"}  # type: ignore[assignment]
ok = llm.chat_with_tools(
    "sys", "usr",
    tools=[{"type": "function", "function": {"name": "check_resume_quality", "parameters": {}}}],
    executor=lambda n, a: {"ok": True},
    max_rounds=3,
    flow_deadline=150.0,
)
check("正常路径：一轮出稿、无超时标记",
      ok["content"] == "正常稿子" and ok["deadline_hit"] is False and ok["rounds"] == 1,
      f"rounds={ok['rounds']} hit={ok['deadline_hit']}")

# ---- ⑤ 预算已被前序吃尽时，仍必须跑一轮（回归：不能空手而归）----
llm._post_messages = lambda provider, messages, **kw: {"content": "兜底稿"}  # type: ignore[assignment]
starved = llm.chat_with_tools(
    "sys", "usr",
    tools=[{"type": "function", "function": {"name": "check_resume_quality", "parameters": {}}}],
    executor=lambda n, a: {"ok": True},
    max_rounds=3,
    flow_deadline=0.0,   # 一开始就没有余额
)
check("预算为 0 也至少跑一轮并出稿（而非空内容）",
      starved["content"] == "兜底稿" and starved["rounds"] >= 1,
      f"content={starved['content'][:20]!r} rounds={starved['rounds']}")

# ---- ⑥ 环境变量默认值合理 ----
check("默认单链墙钟 100s", llm._chain_deadline() == 100.0, str(llm._chain_deadline()))
check("默认全流程墙钟 150s", llm._flow_deadline() == 150.0, str(llm._flow_deadline()))

print()
if FAILURES:
    print(f"RESULT: {len(FAILURES)} FAILURE(S): {FAILURES}")
    sys.exit(1)
print("RESULT: TIMEOUT GUARDS ALL CHECKS PASSED")
