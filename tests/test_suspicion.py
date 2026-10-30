"""E4 疑点检测验收测试（设计文档 4.3 的硬门槛）。

通过标准：三份坏简历各自的目标疑点**全部命中**，对照简历无高危疑点。
缺任何一个都不算 E4 解锁，不许带着上半成品进 D2。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parent.parent / "backend"
sys.path.insert(0, str(BACKEND_ROOT))

from engine.models import Experience, ResumeProfile  # noqa: E402
from engine.suspicion import run_all  # noqa: E402

FIXTURES = Path(__file__).resolve().parent / "fixtures"

FAILURES: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"[{'PASS' if cond else 'FAIL'}] {name}" + (f"  -- {detail}" if detail else ""))
    if not cond:
        FAILURES.append(name)


def load(fixture: str) -> ResumeProfile:
    data = json.loads((FIXTURES / fixture).read_text(encoding="utf-8"))
    experiences = [
        Experience(
            kind=x.get("kind", "project"),
            name=x.get("name", ""),
            role=x.get("role", ""),
            period=x.get("period", ""),
            actions=x.get("actions", []),
            results=x.get("results", []),
            skills=x.get("skills", []),
        )
        for x in data.get("experiences", [])
    ]
    from engine.suspicion import parse_period

    for e in experiences:
        s, en, _ = parse_period(e.period or "")
        e.start, e.end = s, en
    return ResumeProfile(
        name=data.get("name", ""),
        experiences=experiences,
        skills=data.get("skills", []),
        education=data.get("education", []),
        raw_text="",
        user_confirmed=True,
    )


def types_of(findings) -> set[str]:
    return {f.type for f in findings}


# ---- 坏简历 A：时间重叠必须命中 ----
a = load("bad_resume_overlap.json")
fa = run_all(a)
ta = types_of(fa)
check("A-时间重叠命中", "timeline_overlap" in ta, f"types={sorted(ta)}")
overlap = [f for f in fa if f.type == "timeline_overlap"]
check("A-重叠 detail 含具体月数", overlap and "重叠" in overlap[0].detail and "个月" in overlap[0].detail,
      overlap[0].detail if overlap else "无")

# ---- 坏简历 B：无量化必须命中 ----
b = load("bad_resume_no_numbers.json")
fb = run_all(b)
tb = types_of(fb)
check("B-无量化命中", "no_quantification" in tb, f"types={sorted(tb)}")
noq = [f for f in fb if f.type == "no_quantification"]
check("B-无量化 detail 含条数与零数字", any("0" in f.detail for f in noq),
      noq[0].detail if noq else "无")

# ---- 坏简历 C：技能无支撑必须命中 ----
c = load("bad_resume_skill_gap.json")
fc = run_all(c)
tc = types_of(fc)
check("C-技能无支撑命中", "skill_without_evidence" in tc, f"types={sorted(tc)}")
sw = [f for f in fc if f.type == "skill_without_evidence"]
check("C-技能无支撑 detail 列出未支撑技能", sw and ("Python" in sw[0].detail or "SQL" in sw[0].detail),
      sw[0].detail if sw else "无")

# ---- 关键词堆砌：C 简历的技能与 JD 关键词对照 ----
jd_kw = ["Python", "SQL", "A/B 测试", "用户画像", "增长黑客"]
fc2 = run_all(c, jd_kw)
check("C-关键词堆砌命中（带 JD 关键词时）", "keyword_stuffing" in types_of(fc2),
      f"types={sorted(types_of(fc2))}")

# ---- 对照简历：无高危疑点 ----
g = load("good_resume.json")
fg = run_all(g, ["数据分析", "活动策划"])
high = [f for f in fg if f.severity == "high"]
check("对照简历无高危疑点", not high,
      "; ".join(f"{f.type}:{f.detail}" for f in high) or "无")

# ---- 输出契约：统一字段 ----
for label, findings in (("A", fa), ("B", fb), ("C", fc)):
    ok = all(hasattr(f, "type") and hasattr(f, "location") and hasattr(f, "detail")
             and hasattr(f, "suggestion") and f.program_verified for f in findings)
    check(f"{label}-输出契约完整(type/location/detail/suggestion/program_verified)", ok)

print()
if FAILURES:
    print(f"RESULT: {len(FAILURES)} FAILURE(S): {FAILURES}")
    sys.exit(1)
print("RESULT: E4 ALL CHECKS PASSED — 疑点检测已解锁")
