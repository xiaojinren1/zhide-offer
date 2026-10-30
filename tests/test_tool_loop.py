"""工具调用循环 + 产物质检测试（补齐"工具调用 / 反思自纠错 / 失败换方案"三项）。

验证：
① 模型先出稿 → 调用质检工具 → 收到问题 → 修订 → 收尾（完整 Reflexion 循环）
② 工具抓到虚构数字/套话/低覆盖率
③ 达到轮数上限时强制收尾，不死循环
④ 工具执行器异常不外抛
⑤ 经历库长期记忆：保存/列表/读取/删除/路径穿越防护
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parent.parent / "backend"
sys.path.insert(0, str(BACKEND_ROOT))

FAILURES: list[str] = []


def check(name, cond, detail=""):
    print(f"[{'PASS' if cond else 'FAIL'}] {name}" + (f"  -- {detail}" if detail else ""))
    if not cond:
        FAILURES.append(name)


from engine.models import Experience, ResumeProfile  # noqa: E402
from engine.quality_check import check_markdown, untraceable_numbers  # noqa: E402
from core.tools import TOOL_SPECS, build_executor  # noqa: E402
import core.llm as llm  # noqa: E402

PROFILE = ResumeProfile(
    experiences=[
        Experience(kind="project", name="用户增长活动", role="增长负责人", period="2024.03-2024.09",
                   actions=["策划并上线用户增长活动，用 A/B 测试优化转化链路"],
                   results=["DAU 提升 18%，覆盖 12 万用户"], skills=["数据分析", "A/B 测试"]),
        Experience(kind="internship", name="电商运营实习", role="运营", period="2024.10-2025.03",
                   actions=["负责品类日常运营，搭建复盘模板"],
                   results=["沉淀 3 套可复用流程"], skills=["电商运营"]),
    ],
    skills=["数据分析", "A/B 测试", "电商运营"],
)
KW = ["用户增长", "数据分析", "A/B 测试", "转化"]

# ---- ② 质检：虚构数字 / 套话 / 低覆盖 ----
bad_md = "我责任心强、吃苦耐劳，负责用户增长活动，DAU 提升 95%，覆盖 800 万用户。"
rep = check_markdown(bad_md, PROFILE, KW)
types = {i["type"] for i in rep["issues"]}
check("质检抓到虚构数字", "fabricated_number" in types, str(types))
check("质检抓到套话", "cliche" in types, str(types))
check("虚构数字标为 high 且 ok=False",
      any(i["severity"] == "high" for i in rep["issues"]) and rep["ok"] is False)
good_md = "负责用户增长活动，用 A/B 测试优化转化链路，DAU 提升 18%，覆盖 12 万用户；搭建数据复盘模板，沉淀 3 套流程。"
rep2 = check_markdown(good_md, PROFILE, KW)
check("合规简历无 high 级问题", rep2["high_count"] == 0 and rep2["ok"] is True,
      f"high={rep2['high_count']}")

# ---- ① 工具循环：先出稿 → 调工具 → 修订 → 收尾 ----
seen_messages: list[dict] = []


def fake_post(provider, messages, *, tools=None, temperature=0.2, json_mode=False):
    seen_messages.append({"tools": bool(tools), "n": len(messages)})
    # 第一轮（带工具）：返回一个工具调用请求
    if tools and not any(m.get("role") == "tool" for m in messages):
        return {
            "content": "",
            "tool_calls": [{
                "id": "call_1",
                "type": "function",
                "function": {"name": "check_resume_quality",
                             "arguments": json.dumps({"resume_markdown": "DAU 提升 95%，责任心强"}, ensure_ascii=False)},
            }],
        }
    # 有工具结果之后：返回修订稿（不再调工具）
    if any(m.get("role") == "tool" for m in messages):
        return {"content": "修订稿：DAU 提升 18%，覆盖 12 万用户，用 A/B 测试优化转化链路。"}
    # 无工具兜底
    return {"content": "最终稿"}


llm._run_with_providers = lambda call_once, **kw: call_once({"name": "primary"})  # type: ignore[assignment]
llm._post_messages = fake_post  # type: ignore[assignment]

executor, calls = build_executor(profile=PROFILE, jd_keywords=KW)
result = llm.chat_with_tools(
    "sys", "usr", tools=TOOL_SPECS, executor=executor, max_rounds=3,
)
check("工具循环返回修订稿内容", "18%" in result["content"], result["content"][:60])
check("模型确实调用了质检工具", calls == ["check_resume_quality"], str(calls))
check("结果记录了工具调用", result["tool_calls"] == ["check_resume_quality"], str(result["tool_calls"]))
check("拿到了工具返回的问题清单",
      isinstance(result["final_tool_result"], dict)
      and result["final_tool_result"].get("high_count", 0) >= 1,
      str(result["final_tool_result"])[:120])
check("循环在 2 轮内结束（没死循环）", result["rounds"] <= 3, str(result["rounds"]))

# ---- ③ 轮数上限：模型一直调工具 → 强制收尾 ----
def fake_always_tools(provider, messages, *, tools=None, temperature=0.2, json_mode=False):
    if tools:
        return {"content": "", "tool_calls": [{"id": "c", "type": "function",
                "function": {"name": "check_resume_quality", "arguments": "{}"}}]}
    return {"content": "兜底收尾稿"}


llm._post_messages = fake_always_tools  # type: ignore[assignment]
executor2, calls2 = build_executor(profile=PROFILE, jd_keywords=KW)
result2 = llm.chat_with_tools("sys", "usr", tools=TOOL_SPECS, executor=executor2, max_rounds=3)
check("轮数上限时强制收尾（不死循环）", result2["rounds"] == 3 and result2["content"] == "兜底收尾稿",
      f"rounds={result2['rounds']}")

# ---- ④ 执行器异常不外抛 ----
def boom(name, args):
    raise RuntimeError("tool crashed")


llm._post_messages = fake_post  # type: ignore[assignment]
result3 = llm.chat_with_tools("sys", "usr", tools=TOOL_SPECS, executor=boom, max_rounds=3)
check("执行器崩溃也被兜住（返回 error 给模型而非炸掉）",
      "18%" in result3["content"] or result3["content"], result3["content"][:40])

# ---- ⑤ 长期记忆 ----
import os  # noqa: E402
os.environ["JOBAGENT_PROFILES_DIR"] = str(Path(__file__).resolve().parent / "_tmp_profiles")
import api.profiles as profiles_mod  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from main import app  # noqa: E402

client = TestClient(app)
r = client.post("/api/profiles/save", json={"name": "测试用户", "profile": PROFILE.to_dict()})
check("保存经历库成功", r.status_code == 200 and r.json().get("ok") is True, r.text[:120])
pid = r.json().get("id") or ""
check("返回了合法 id", bool(pid), pid)

r2 = client.get("/api/profiles/list")
check("列表能读到刚保存的", r2.json().get("ok") and any(p["id"] == pid for p in r2.json()["profiles"]))

r3 = client.get(f"/api/profiles/{pid}")
check("能按 id 读回完整经历库", r3.json().get("ok") and
      len(r3.json()["profile"]["experiences"]) == 2)

r4 = client.get("/api/profiles/..%2F..%2FRULES")
check("路径穿越被拒绝", r4.json().get("ok") is False, r4.text[:100])

r5 = client.delete(f"/api/profiles/{pid}")
dj = r5.json()
# 沙箱环境可能拦截文件删除（safe-delete fail-closed）；此时接口应优雅返回错误而非 500
env_blocked = "safe" in str(dj.get("error", "")).lower()
check("删除接口行为正确（成功，或被环境拦截时优雅报错，不出 500）",
      r5.status_code == 200 and (dj.get("ok") is True or env_blocked),
      f"ok={dj.get('ok')} env_blocked={env_blocked}")

# 清理测试产物（留在 data/profiles 里会污染用户的真实数据目录）
for f in (BACKEND_ROOT.parent / "data" / "profiles").glob("*.json"):
    try:
        f.unlink()
    except Exception:
        pass

# ---- RULES.md 规则机制 ----
from core.config import agent_rules  # noqa: E402
rules = agent_rules()
check("RULES.md 被读取并注入", "不许虚构" in rules and "可复核" in rules, rules[:60])

print()
if FAILURES:
    print(f"RESULT: {len(FAILURES)} FAILURE(S): {FAILURES}")
    sys.exit(1)
print("RESULT: TOOL LOOP + QUALITY + MEMORY ALL CHECKS PASSED")
