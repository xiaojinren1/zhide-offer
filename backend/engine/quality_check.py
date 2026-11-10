"""产物质检：对"生成的简历正文"跑全套确定性检查。

同时服务两条路径，保证判定标准一致（DRY）：
  1. J3 质检报告路由（/api/quality）
  2. 模型自检工具（check_resume_quality，生成循环里由模型自己调用）
"""
from __future__ import annotations

import re

from engine.models import ResumeProfile
from engine.suspicion import run_all

_CLICHES = [
    "责任心强", "吃苦耐劳", "有团队精神", "抗压能力强", "学习能力强",
    "善于沟通", "工作认真", "积极主动", "执行力强", "良好的沟通能力",
    "团队合作精神", "能适应加班", "服从安排", "性格开朗",
]


def cliche_hits(text: str) -> list[str]:
    return [c for c in _CLICHES if c in (text or "")]


def known_numbers(profile: ResumeProfile) -> set[str]:
    """经历库里出现过的全部数字（可追溯真值）。"""
    known: set[str] = set(re.findall(r"\d+(?:\.\d+)?", " ".join([profile.name] + profile.skills + profile.education)))
    for e in profile.experiences:
        blob = " ".join([e.name, e.role, e.period] + e.actions + e.results + e.quantified + e.skills)
        known |= set(re.findall(r"\d+(?:\.\d+)?", blob))
    return known


_YEAR_MONTH = r"(?:19|20)\d{2}(?:[./-](?:0?[1-9]|1[0-2])|年[ \t]*(?:0?[1-9]|1[0-2])月)"
_DATE_RANGE = re.compile(rf"(?<!\d){_YEAR_MONTH}(?!\d)[ \t]*(?:[-–—~～]|至|到)[ \t]*(?:{_YEAR_MONTH}(?!\d)|至今|现在|present)", re.I)
_LABELED_DATE = re.compile(rf"((?:时间|日期|入职|离职|入学|毕业)[* \t]*[：:][* \t]*){_YEAR_MONTH}(?!\d)")
_CONTACT = re.compile(r"(?:手机(?:号码)?|电话|联系方式|QQ|微信|tel|phone)[* \t]*[：:][* \t]*(?:\+?86[ -]?)?\d(?:[ \t-]?\d){4,19}(?!\d)", re.I)
_EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")


def untraceable_numbers(md: str, profile: ResumeProfile, sample: int = 8) -> list[str]:
    """简历里出现、但经历库中不存在的数字 → 疑似虚构。"""
    known = known_numbers(profile)
    body = _DATE_RANGE.sub(" ", md or "")
    body = _LABELED_DATE.sub(r"\1 ", body)
    body = _EMAIL.sub(" ", _CONTACT.sub(" ", body))
    unknown = sorted({n for n in re.findall(r"\d+(?:\.\d+)?", body) if n not in known})
    return unknown[:sample]


def keyword_coverage(md: str, jd_keywords: list[str]) -> float:
    if not jd_keywords:
        return 0.0
    low = (md or "").lower()
    hits = sum(1 for k in jd_keywords if k and k.lower() in low)
    return round(hits / len(jd_keywords), 3)


def check_markdown(md: str, profile: ResumeProfile, jd_keywords: list[str] | None = None) -> dict:
    """对简历正文跑全套检查，返回结构化问题清单。

    `ok` = 没有 high 级问题。每条 issue 都带 severity 与具体证据——
    不可复核的问题等于没有问题。
    """
    jd_keywords = list(jd_keywords or [])
    issues: list[dict] = []

    for n in untraceable_numbers(md, profile):
        issues.append({
            "type": "fabricated_number", "severity": "high",
            "detail": f"数字 {n} 在经历库中不存在，疑似虚构",
            "fix": "删除该数字，或改回经历库中的真实数值",
        })
    for c in cliche_hits(md):
        issues.append({
            "type": "cliche", "severity": "medium",
            "detail": f"出现套话：{c}", "fix": "换成具体事实或量化表述",
        })
    cov = keyword_coverage(md, jd_keywords)
    if jd_keywords and cov < 0.5:
        issues.append({
            "type": "low_keyword_coverage", "severity": "medium",
            "detail": f"JD 关键词覆盖率仅 {round(cov * 100)}%",
            "fix": "仅当已确认事实支持时，在相关行动中使用岗位术语；没有事实依据的关键词是缺口，不得编造或硬塞进技能清单",
        })
    for s in run_all(profile, jd_keywords):
        if s.type == "no_quantification":
            issues.append({
                "type": s.type, "severity": "medium", "source": "profile",
                "detail": s.detail,
                "fix": "原始资料没有量化依据时保留定性成果，不新增数字或量级；仅由用户后续补充可验证数据，不因此反复修订简历",
            })
            continue
        issues.append({
            "type": s.type, "severity": s.severity,
            "detail": s.detail, "fix": s.suggestion,
        })

    order = {"high": 0, "medium": 1, "low": 2}
    issues.sort(key=lambda x: order.get(x["severity"], 3))
    return {
        "ok": not any(i["severity"] == "high" for i in issues),
        "issue_count": len(issues),
        "high_count": sum(1 for i in issues if i["severity"] == "high"),
        "keyword_coverage": cov,
        "issues": issues,
    }
