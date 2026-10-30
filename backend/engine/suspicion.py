"""E4 疑点检测——全套产品差异化的技术根（设计文档 4.3 节施工）。

四类检测器，全部 stdlib 实现、全部程序可判、零外部依赖：
  1. timeline_overlap / timeline_gap  时间线重叠 / 空窗（日期解析 + 区间求交）
  2. no_quantification                经历无量化（数字密度）
  3. skill_without_evidence           技能声明与项目经验不一致（集合差）
  4. keyword_stuffing                 关键词堆砌（JD 词在技能清单却不在任何项目描述）

铁律：detail 必须含具体证据（哪两段重叠几个月、哪条经历几个数字），
不可复核的疑点等于没有疑点——这是"帮你验"定位的底线。
"""
from __future__ import annotations

import re
from datetime import date
from typing import Iterable

from engine.models import Experience, ResumeProfile, Suspicion

# --------------------------------------------------------------------------
# 日期解析（兼容中文简历常见写法，纯 stdlib，不引 dateutil）
# --------------------------------------------------------------------------

_MONTH_RE = r"(?:19|20)\d{2}\s*[年./\-]?\s*(?:1[0-2]|0?[1-9])\s*月?"
_PERIOD_RE = re.compile(
    rf"(?P<start>{_MONTH_RE})\s*[-–—~至到]\s*(?P<end>{_MONTH_RE}|至今|现在|now|present|Present)",
    re.IGNORECASE,
)
_SINGLE_RE = re.compile(rf"(?P<start>{_MONTH_RE})")
_OPEN_ENDED = {"至今", "现在", "now", "present"}

_CN_MONTH = re.compile(r"(?P<y>(?:19|20)\d{2})\s*[年.\-/]?\s*(?P<m>1[0-2]|0?[1-9])\s*月?")


def _parse_ym(token: str) -> tuple[int, int] | None:
    m = _CN_MONTH.match(token.strip())
    if not m:
        return None
    return int(m.group("y")), int(m.group("m"))


def parse_period(text: str) -> tuple[tuple[int, int] | None, tuple[int, int] | None, bool]:
    """解析时间串 → (start, end, parsed_ok)。end=None 且 parsed_ok=True 表示至今。"""
    if not text:
        return None, None, False
    m = _PERIOD_RE.search(text)
    if m:
        start = _parse_ym(m.group("start"))
        end_token = m.group("end")
        if end_token.strip().lower() in _OPEN_ENDED:
            return start, None, start is not None
        end = _parse_ym(end_token)
        return start, end, start is not None and end is not None
    m2 = _SINGLE_RE.search(text)
    if m2:
        start = _parse_ym(m2.group("start"))
        return start, None, start is not None
    return None, None, False


def _ym_key(ym: tuple[int, int] | None) -> int:
    if not ym:
        return 0
    return ym[0] * 12 + (ym[1] - 1)


def _today_ym() -> tuple[int, int]:
    t = date.today()
    return t.year, t.month


def _fmt_ym(ym: tuple[int, int]) -> str:
    return f"{ym[0]}.{ym[1]:02d}"


# --------------------------------------------------------------------------
# 1. 时间线重叠 / 空窗
# --------------------------------------------------------------------------

def detect_timeline(experiences: Iterable[Experience]) -> list[Suspicion]:
    out: list[Suspicion] = []
    exp_list = [e for e in experiences if e and (e.start or e.end)]
    parsed: list[tuple[Experience, tuple[int, int], tuple[int, int]]] = []
    for e in exp_list:
        start, end, ok = parse_period(e.period or "")
        if not ok or not start:
            continue
        s_key = _ym_key(start)
        e_key = _ym_key(end) if end else _ym_key(_today_ym())
        if e_key < s_key:
            e_key = s_key
        parsed.append((e, start, (e_key // 12, e_key % 12 + 1)))

    # 重叠：两两求交
    for i in range(len(parsed)):
        for j in range(i + 1, len(parsed)):
            e1, s1, en1 = parsed[i]
            e2, s2, en2 = parsed[j]
            lo = max(_ym_key(s1), _ym_key(s2))
            hi = min(_ym_key(en1), _ym_key(en2))
            if lo < hi:
                months = hi - lo
                out.append(Suspicion(
                    type="timeline_overlap",
                    location=f"{e1.name or e1.kind} vs {e2.name or e2.kind}",
                    detail=(
                        f"「{e1.name or e1.kind}」({_fmt_ym(s1)}-{_fmt_ym(en1)}) 与 "
                        f"「{e2.name or e2.kind}」({_fmt_ym(s2)}-{_fmt_ym(en2)}) "
                        f"重叠 {months} 个月"
                    ),
                    suggestion="面试必被追问：确认是并行还是笔误；若并行，写明各自投入比例",
                    severity="high" if months >= 3 else "medium",
                ))

    # 空窗：按开始时间排序后，相邻段间隔 > 6 个月
    ordered = sorted(parsed, key=lambda x: _ym_key(x[1]))
    for k in range(1, len(ordered)):
        prev_e, prev_s, prev_en = ordered[k - 1]
        cur_e, cur_s, _ = ordered[k]
        gap = _ym_key(cur_s) - _ym_key(prev_en)
        if gap > 6:
            out.append(Suspicion(
                type="timeline_gap",
                location=f"{prev_e.name or prev_e.kind} → {cur_e.name or cur_e.kind}",
                detail=f"两段经历之间空窗 {gap} 个月（{_fmt_ym(prev_en)} → {_fmt_ym(cur_s)}）",
                suggestion="空窗超 6 个月建议主动说明去向（学习/项目/健康），避免面试被反复问",
                severity="medium" if gap < 12 else "high",
            ))
    return out


# --------------------------------------------------------------------------
# 2. 经历无量化
# --------------------------------------------------------------------------

_QUANT_RE = re.compile(r"\d+(?:\.\d+)?\s*(?:%|％|个|人次|天|周年|万|k|K|m|M|b|B|元|块|单|次|条|篇|款|家|人)?")


def count_numbers(text: str) -> int:
    return len(_QUANT_RE.findall(text or ""))


def detect_missing_quantification(experiences: Iterable[Experience]) -> list[Suspicion]:
    out: list[Suspicion] = []
    exp_list = [e for e in experiences if e]
    no_num: list[str] = []
    total = 0
    with_num = 0
    for e in exp_list:
        total += 1
        text = " ".join(e.actions + e.results)
        n = count_numbers(text)
        if n > 0:
            with_num += 1
        else:
            no_num.append(e.name or e.kind)

    for name in no_num:
        out.append(Suspicion(
            type="no_quantification",
            location=name,
            detail=f"「{name}」的行动/结果描述中数字个数为 0",
            suggestion="补一个可验证数字（提升 X%/处理 N 条/覆盖 M 人），没有精确值就给量级",
            severity="medium",
        ))

    if total > 0 and with_num / total < 0.3:
        out.append(Suspicion(
            type="no_quantification",
            location="整份简历",
            detail=f"量化密度过低：{with_num}/{total} 段经历含数字（阈值 30%）",
            suggestion="过半经历无量化表述，HR 初筛时无法判断你的实际产出",
            severity="high",
        ))
    return out


# --------------------------------------------------------------------------
# 3. 技能声明与项目经验不一致（集合差）
# --------------------------------------------------------------------------

def _tokenize(text: str) -> set[str]:
    """粗分词：英文词 + 连续中文片段（2 字以上）。"""
    if not text:
        return set()
    words = set(re.findall(r"[A-Za-z][A-Za-z0-9+#.\-]{1,}", text))
    words |= {m for m in re.findall(r"[\u4e00-\u9fff]{2,}", text)}
    return {w.lower() for w in words}


def detect_skill_without_evidence(
    experiences: Iterable[Experience],
    declared_skills: Iterable[str],
) -> list[Suspicion]:
    out: list[Suspicion] = []
    project_tokens: set[str] = set()
    for e in experiences:
        if e:
            project_tokens |= _tokenize(" ".join(e.actions + e.results + e.skills + [e.name]))
    unsupported = [s for s in (declared_skills or []) if s and s.lower() not in project_tokens]
    if unsupported:
        out.append(Suspicion(
            type="skill_without_evidence",
            location="技能清单",
            detail=f"声明了 {len(unsupported)} 项技能但任何项目描述中找不到支撑：{', '.join(unsupported[:10])}",
            suggestion="要么补一个用该技能的项目，要么从清单删除——空声明会被面试官当成质疑点",
            severity="high" if len(unsupported) >= 4 else "medium",
        ))
    return out


# --------------------------------------------------------------------------
# 4. 关键词堆砌
# --------------------------------------------------------------------------

def detect_keyword_stuffing(
    experiences: Iterable[Experience],
    declared_skills: Iterable[str],
    jd_keywords: Iterable[str],
) -> list[Suspicion]:
    """JD 关键词出现在技能清单、却不出现在任何项目描述 = 堆砌。"""
    out: list[Suspicion] = []
    project_tokens: set[str] = set()
    for e in experiences:
        if e:
            project_tokens |= _tokenize(" ".join(e.actions + e.results + [e.name]))
    skill_blob = " ".join(declared_skills or []).lower()
    stuffed = [
        kw for kw in (jd_keywords or [])
        if kw and kw.lower() in skill_blob and kw.lower() not in project_tokens
    ]
    if stuffed:
        out.append(Suspicion(
            type="keyword_stuffing",
            location="技能清单",
            detail=f"{len(stuffed)} 个 JD 关键词只出现在技能清单、无项目支撑：{', '.join(stuffed[:10])}",
            suggestion="这是典型的关键词堆砌，ATS 与面试官都会识别；把关键词写进具体项目成果里",
            severity="medium",
        ))
    return out


# --------------------------------------------------------------------------
# 统一入口
# --------------------------------------------------------------------------

def run_all(resume: ResumeProfile, jd_keywords: list[str] | None = None) -> list[Suspicion]:
    """跑全部四类检测器，返回按 severity 排序的疑点清单。"""
    findings: list[Suspicion] = []
    findings += detect_timeline(resume.experiences)
    findings += detect_missing_quantification(resume.experiences)
    findings += detect_skill_without_evidence(resume.experiences, resume.skills)
    if jd_keywords:
        findings += detect_keyword_stuffing(resume.experiences, resume.skills, jd_keywords)
    order = {"high": 0, "medium": 1, "low": 2}
    findings.sort(key=lambda s: order.get(s.severity, 3))
    return findings
