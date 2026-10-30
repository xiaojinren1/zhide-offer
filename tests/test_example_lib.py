"""范例库（轻量 RAG）测试。

验证：① 语料可加载且规模足够 ② 按岗位类型检索准确 ③ 空/坏语料不拖垮主流程
④ 检索结果只含写法参考字段（不带原文关键词等噪声） ⑤ 方法论可读
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


from engine.example_lib import count, load_library, methodology, retrieve  # noqa: E402

# ---- ① 语料规模与完整性 ----
lib = load_library()
n = count()
check("范例库已加载且规模 >= 25", n >= 25, f"{n} 条")
check("方法论非空", len(methodology()) >= 4, f"{len(methodology())} 条")

required = {"id", "role_tags", "skill_tags", "weak", "strong", "technique", "keywords"}
bad = [e.get("id") for e in lib["examples"] if not required.issubset(e.keys())]
check("每条范例字段完整（id/role_tags/skill_tags/weak/strong/technique/keywords）",
      not bad, f"缺字段: {bad}")
ids = [e["id"] for e in lib["examples"]]
check("范例 id 无重复", len(ids) == len(set(ids)), f"{len(ids)} 条 / {len(set(ids))} 唯一")
check("strong 均含数字（量化是硬要求）",
      all(any(c.isdigit() for c in e["strong"]) for e in lib["examples"]),
      "有空壳条目")

# ---- ② 按岗位检索 ----
JD_GROWTH = "岗位：用户增长运营。负责用户增长活动策划，通过 A/B 测试优化转化链路，提升 DAU 与留存。要求熟悉数据分析。"
KW_GROWTH = ["用户增长", "A/B测试", "转化", "DAU", "留存", "数据分析"]
top = retrieve(JD_GROWTH, KW_GROWTH, top_k=3)
check("增长岗检索返回 3 条", len(top) == 3, str([e["id"] for e in top]))
check("增长岗 Top1 来自增长类范例",
      top and any(t in top[0]["id"] for t in ("growth", "content", "event")),
      top[0]["id"] if top else "无")
check("增长岗检索命中了增长类范例（前 3 里至少 1 条 growth-）",
      any(e["id"].startswith("growth-") for e in top), str([e["id"] for e in top]))

JD_PM = "岗位：产品经理。负责 App 核心模块迭代与需求管理，基于数据优化转化率，跨部门协作推进版本上线。"
KW_PM = ["产品经理", "需求", "迭代", "转化率", "跨部门"]
top_pm = retrieve(JD_PM, KW_PM, top_k=3)
check("产品岗 Top1 是产品类范例", top_pm and top_pm[0]["id"].startswith("pm-"),
      top_pm[0]["id"] if top_pm else "无")

JD_GAME = "岗位：游戏策划。负责数值框架设计与平衡性调整，基于留存数据迭代关卡难度，输出策划文档。"
KW_GAME = ["游戏策划", "数值", "平衡性", "留存", "关卡"]
top_game = retrieve(JD_GAME, KW_GAME, top_k=3)
check("游戏策划岗能检索到游戏类范例", any(e["id"].startswith("game-") for e in top_game),
      str([e["id"] for e in top_game]))

# ---- ③ 鲁棒性：坏输入不炸 ----
check("空 JD + 空关键词不炸", retrieve("", [], top_k=3) is not None)
check("top_k=0 返回空", retrieve(JD_GROWTH, KW_GROWTH, top_k=0) == [])

# ---- ④ 返回字段干净（只带 id + 写法参考三件套）----
if top:
    check("检索结果只含 id+weak/strong/technique（不带检索用噪声）",
          set(top[0].keys()) == {"id", "weak", "strong", "technique"},
          str(set(top[0].keys())))
    check("每条范例都带 id（便于日志追溯检索到哪条）",
          all(e.get("id") for e in top), str([e.get("id") for e in top]))

# ---- ⑤ 语料文件可被外部扩充（schema 稳定）----
raw = json.loads((BACKEND_ROOT / "data" / "knowledge" / "examples.json").read_text(encoding="utf-8"))
check("语料文件含 version 与 note（便于维护）",
      "version" in raw and "note" in raw, f"version={raw.get('version')}")

print()
if FAILURES:
    print(f"RESULT: {len(FAILURES)} FAILURE(S): {FAILURES}")
    sys.exit(1)
print(f"RESULT: EXAMPLE LIBRARY ALL CHECKS PASSED（{n} 条范例）")
