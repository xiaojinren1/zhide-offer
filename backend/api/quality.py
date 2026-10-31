"""J3 质检报告 API——差异化核心：全部程序判定，不靠模型感觉。

指标（设计文档 5.3.2）：JD 关键词覆盖率 / 量化密度 / 套话检测 / ATS 友好度 /
与经历库一致性 / 复用 E4 疑点清单。
"""
from __future__ import annotations

import re

from fastapi import APIRouter
from pydantic import BaseModel

from core import events
from engine.jd_parser import parse_jd
from engine.models import QualityReport
from engine.resume_parser import profile_from_dict
from engine.suspicion import _tokenize, count_numbers, run_all

router = APIRouter(prefix="/api/quality", tags=["quality"])

# 套话词表：出现即扣分（程序可判）
_CLICHES = [
    "责任心强", "吃苦耐劳", "有团队精神", "抗压能力强", "学习能力强",
    "善于沟通", "工作认真", "积极主动", "执行力强", "良好的沟通能力",
    "团队合作精神", "能适应加班", "服从安排", "性格开朗",
]

_ATS_CHECKS = [
    ("缺少邮箱", re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+")),
    ("缺少手机号", re.compile(r"1[3-9]\d{9}")),
]


class QualityRequest(BaseModel):
    jd_text: str
    resume_profile: dict
    resume_markdown: str = ""      # J2 产物；为空则只检经历库
    jd_keywords: list[str] = []    # 前端从诊断步带过来，有就跳过重复解析

def _cliche_hits(text: str) -> list[str]:
    return [c for c in _CLICHES if c in (text or "")]


def _ats_issues(text: str) -> list[str]:
    issues = [name for name, pat in _ATS_CHECKS if not pat.search(text or "")]
    # 超长段落（ATS 解析困难）
    for para in (text or "").split("\n"):
        if len(para) > 400:
            issues.append(f"存在超长段落（{len(para)} 字符），ATS 解析困难")
            break
    return issues


def _consistency_issues(md: str, profile) -> list[str]:
    """生成简历中出现的数字，若不在经历库量化字段里 → 不一致。"""
    known: set[str] = set()
    for e in profile.experiences:
        for m in re.findall(r"\d+(?:\.\d+)?", " ".join(e.actions + e.results)):
            known.add(m)
    unknown = sorted({n for n in re.findall(r"\d+(?:\.\d+)?", md or "") if n not in known})
    if unknown:
        return [f"出现经历库中不存在的数字：{', '.join(unknown[:10])}（疑似虚构）"]
    return []


@router.post("")
def quality(req: QualityRequest):
    events.emit("quality_started")
    profile = profile_from_dict(req.resume_profile)

    # 关键词覆盖率：优先用前端从诊断步带过来的 jd_keywords（省一次 LLM 解析，
    # 10~20 秒 + 一份 token）；没带才自己解析。解析失败必须传播，不能伪装成
    # 关键词覆盖率为 0 的成功报告。
    keyword_coverage = 0.0
    if not req.jd_text.strip():
        jd_keywords = []
    elif req.jd_keywords:
        jd_keywords = list(req.jd_keywords)
    else:
        jd = parse_jd(req.jd_text)
        jd_keywords = jd.keywords
    if jd_keywords:
        md_tokens = _tokenize(req.resume_markdown or "")
        hits = sum(1 for k in jd_keywords if k.lower() in md_tokens or k.lower() in (req.resume_markdown or "").lower())
        keyword_coverage = round(hits / len(jd_keywords), 3)

    total = len(profile.experiences) or 1
    with_num = sum(1 for e in profile.experiences if count_numbers(" ".join(e.actions + e.results)) > 0)
    quantified_ratio = round(with_num / total, 3)

    scan_text = (req.resume_markdown or "") + " " + " ".join(profile.skills)
    report = QualityReport(
        keyword_coverage=keyword_coverage,
        quantified_ratio=quantified_ratio,
        cliche_hits=_cliche_hits(scan_text),
        ats_issues=_ats_issues(req.resume_markdown or profile.raw_text),
        consistency_issues=_consistency_issues(req.resume_markdown, profile) if req.resume_markdown else [],
        suspicions=run_all(profile, jd_keywords),
    )
    report.passed = (
        (not req.jd_text.strip() or report.keyword_coverage >= 0.6)
        and report.quantified_ratio >= 0.5
        and not report.cliche_hits
        and not report.consistency_issues
        and not any(s.severity == "high" for s in report.suspicions)
    )
    events.emit("quality_done", passed=report.passed,
                coverage=report.keyword_coverage, suspicions=len(report.suspicions))
    result = report.to_dict()
    result["ok"] = True
    result["keyword_applicable"] = bool(req.jd_text.strip())
    return result
