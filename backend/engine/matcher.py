"""E3 匹配度计算：JD 要求 ↔ 经历库逐条对齐。

双轨设计（设计文档 5.3.1）：关键词集合运算（程序快筛）+ LLM 语义匹配（补同义表述）。
铁律：每条结论必须带证据（哪段经历支撑），无证据的标 missing。
"""
from __future__ import annotations

from core.llm import chat_json
from engine.models import MatchItem, MatchReport, ParsedJD, ResumeProfile
from engine.suspicion import _tokenize
from core.config import agent_rules

_SYSTEM = """你是求职匹配分析器。给定 JD 的结构化要求和候选人的经历库，
逐条判断每条要求的覆盖情况。只输出 JSON：
{
  "items": [
    {"requirement": "JD 要求原文", "status": "covered | partial | missing",
     "evidence": "支撑它的经历名+具体内容（covered/partial 必填，missing 留空）",
     "note": "partial/missing 的差距说明"}
  ]
}
规则：
1. evidence 必须是经历库里真实存在的内容，不许编造。
2. covered = 有直接对等经历；partial = 相关但不充分；missing = 无支撑。
3. note 要说清"差在哪、怎么补"，不要空话。"""


def _keyword_coverage(jd: ParsedJD, resume: ResumeProfile) -> list[MatchItem]:
    """程序快筛：JD 关键词是否出现在经历库文本中。"""
    blob = " ".join(
        [" ".join(e.actions + e.results + e.skills + [e.name, e.role]) for e in resume.experiences]
        + resume.skills
        + resume.education
    )
    tokens = _tokenize(blob)
    items: list[MatchItem] = []
    for kw in jd.keywords:
        hit = kw.lower() in tokens or kw.lower() in blob.lower()
        items.append(MatchItem(
            requirement=f"关键词：{kw}",
            status="covered" if hit else "missing",
            evidence="经历库文本命中" if hit else "",
            note="" if hit else "经历库中未出现该关键词",
        ))
    return items


def match(jd: ParsedJD, resume: ResumeProfile) -> MatchReport:
    """计算匹配度报告。LLM 不可用时退化为纯关键词覆盖（仍然可用）。"""
    items = _keyword_coverage(jd, resume)

    reqs = list(jd.hard_requirements) + list(jd.soft_requirements)
    if reqs:
        payload = {
            "requirements": reqs,
            "experiences": [
                {
                    "name": e.name, "role": e.role, "period": e.period,
                    "actions": e.actions, "results": e.results, "skills": e.skills,
                }
                for e in resume.experiences
            ],
            "skills": resume.skills,
            "education": resume.education,
        }
        try:
            data = chat_json(_SYSTEM + agent_rules(), f"输入：{payload}")
            for x in (data.get("items") or []):
                if not isinstance(x, dict):
                    continue
                status = str(x.get("status") or "").strip()
                if status not in {"covered", "partial", "missing"}:
                    continue
                items.append(MatchItem(
                    requirement=str(x.get("requirement") or "").strip(),
                    status=status,
                    evidence=str(x.get("evidence") or "").strip(),
                    note=str(x.get("note") or "").strip(),
                ))
        except Exception:
            # 降级：LLM 不可用不影响关键词维度的结论（诚实降级，不假装完整）
            pass

    covered = sum(1 for i in items if i.status == "covered")
    partial = sum(1 for i in items if i.status == "partial")
    total = len(items) or 1
    coverage = round((covered + 0.5 * partial) / total, 3)
    missing_hard = [
        i.requirement for i in items
        if i.status == "missing" and not i.requirement.startswith("关键词：")
    ][:10]

    return MatchReport(
        job_title=jd.job_title,
        coverage=coverage,
        items=items,
        missing_hard=missing_hard,
    )
