"""上下文瘦身测试（借鉴 Pi：上下文体积就是成本和质量）。

验证：① JD 相关度高的经历被选中 ② 不相关的被剔除 ③ max_n 生效
④ 无关键词时程序提取兜底 ⑤ 瘦身不改写事实（只筛选）
"""
from __future__ import annotations

import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parent.parent / "backend"
sys.path.insert(0, str(BACKEND_ROOT))

from api.resume import _jd_keywords_programmatic, _relevance, slim_experiences  # noqa: E402
from engine.models import Experience, ResumeProfile  # noqa: E402

FAILURES: list[str] = []


def check(name, cond, detail=""):
    print(f"[{'PASS' if cond else 'FAIL'}] {name}" + (f"  -- {detail}" if detail else ""))
    if not cond:
        FAILURES.append(name)


JD = """岗位：用户增长运营
职责：负责用户增长活动的策划与上线，通过数据分析优化转化链路，
搭建增长策略并推动跨部门落地。要求熟悉 A/B 测试与用户画像方法，
能用 SQL 独立完成数据提取与分析。
硬性要求：本科及以上学历，3 年以上互联网运营经验。"""


def exp(name, role, actions, results, skills, period="2024.03-2024.09"):
    return Experience(kind="project", name=name, role=role, period=period,
                      actions=actions, results=results, skills=skills)


profile = ResumeProfile(
    experiences=[
        exp("校园二手交易平台", "产品负责人",
            ["带 3 人团队完成需求调研与原型设计，主导搜索模块交互方案"],
            ["上线 3 个月注册用户 5000，日均成交 80 单"], ["需求分析", "原型设计"]),
        exp("用户增长活动项目", "增长负责人",
            ["策划并上线用户增长活动，用 A/B 测试优化转化链路，搭建用户画像标签体系"],
            ["活动 DAU 提升 18%，覆盖 12 万用户，转化率提升 25%"],
            ["数据分析", "A/B 测试", "用户画像", "活动策划"]),
        exp("支教志愿者", "志愿者",
            ["在山区小学教授语文与数学，负责课程设计与课堂管理"],
            ["完成 2 学期教学任务，覆盖 120 名学生"], ["沟通协调"]),
        exp("校园快递站兼职", "分拣员",
            ["负责快递分拣、入库与货架整理，处理客户投诉"],
            ["日均处理 800 件包裹"], ["执行力"]),
        exp("学院迎新晚会", "场务组长",
            ["负责场地布置与流程把控，协调 20 名志愿者分工"],
            ["晚会顺利举行，到场 500 人"], ["项目管理"]),
    ],
    skills=["数据分析", "A/B 测试", "用户画像", "活动策划", "需求分析"],
)

kws = ["用户增长", "数据分析", "A/B 测试", "用户画像", "转化", "活动策划"]

# ---- ① 相关度排序 ----
scores = {e.name: _relevance(JD, kws, e) for e in profile.experiences}
top = max(scores, key=scores.get)
check("相关度最高的是增长活动项目", top == "用户增长活动项目", str(scores))

# ---- ②③ 瘦身挑选 ----
selected, dropped, used = slim_experiences(profile, JD, kws, 3)
sel_names = [e.name for e in selected]
check("挑 3 段：增长活动排第一", sel_names[0] == "用户增长活动项目", str(sel_names))
check("挑 3 段：前二是增长+二手（相关度最高的两段）",
      set(sel_names[:2]) == {"用户增长活动项目", "校园二手交易平台"}, str(sel_names))
check("dropped 与 selected 互补且不丢失",
      len(selected) + len(dropped) == len(profile.experiences),
      f"sel={len(selected)} drop={len(dropped)}")
check("dropped 的正是分数最低的两段（结构化断言，不写死名字）",
      {e.name for e in dropped} == set(sorted(scores, key=scores.get)[:2]),
      f"dropped={[e.name for e in dropped]} 期望={sorted(scores, key=scores.get)[:2]}")
check("瘦身不改写经历内容（actions 原样保留）",
      all(e.actions for e in selected), "有经历被改空了")

# ---- max_n=0 表示不瘦身 ----
sel_all, drop_all, _ = slim_experiences(profile, JD, kws, 0)
check("max_n=0 时全量保留（0 被当作不瘦身）",
      len(sel_all) == len(profile.experiences) and not drop_all,
      f"sel={len(sel_all)}")

# ---- ④ 程序关键词兜底 ----
pk = _jd_keywords_programmatic(JD)
check("无关键词时程序提取非空", len(pk) > 0, f"{len(pk)} 个")
check("程序提取含中文关键词（增长/用户/运营）",
      {"增长", "用户", "运营"} & set(pk), str(pk))
check("程序提取含英文术语 SQL", "sql" in pk, str(pk))
sel_fb, drop_fb, used_fb = slim_experiences(profile, JD, [], 2)
check("无传入关键词也能瘦身（走兜底提取）",
      len(sel_fb) == 2 and len(used_fb) > 0, f"sel={len(sel_fb)} kw={len(used_fb)}")

print()
if FAILURES:
    print(f"RESULT: {len(FAILURES)} FAILURE(S): {FAILURES}")
    sys.exit(1)
print("RESULT: CONTEXT SLIMMING ALL CHECKS PASSED")
