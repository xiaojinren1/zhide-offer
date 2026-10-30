"""数据契约：引擎模块之间、引擎与 API 之间的所有数据结构。

为什么单独一个文件：三天工期里前后端/模块要并行开工，契约先定死，
任何人改字段都会立刻在别处炸出来，而不是演示前才发现对不上。
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any


# ---------- E1 JD 解析 ----------

@dataclass
class ParsedJD:
    job_title: str = ""
    company: str = ""
    hard_requirements: list[str] = field(default_factory=list)   # 硬性要求（学历/年限/证书）
    soft_requirements: list[str] = field(default_factory=list)   # 软性要求（技能/素质）
    responsibilities: list[str] = field(default_factory=list)    # 职责
    keywords: list[str] = field(default_factory=list)            # 提取的关键词
    # 可追溯：每条要求都带 JD 原文依据；依据为空的标 inferred=True
    evidence: dict[str, str] = field(default_factory=dict)       # requirement -> 原文片段
    inferred: list[str] = field(default_factory=list)            # 无原文依据、标"推断"的要求

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ---------- E2 经历结构化 ----------

@dataclass
class Experience:
    kind: str = "project"           # project | internship | education
    name: str = ""
    role: str = ""
    period: str = ""                # 原文时间串，如 "2024.03-2024.09"
    start: tuple | None = None      # (year, month)
    end: tuple | None = None        # (year, month)；None = 至今
    actions: list[str] = field(default_factory=list)
    results: list[str] = field(default_factory=list)
    quantified: list[str] = field(default_factory=list)          # 抽取到的数字+单位
    skills: list[str] = field(default_factory=list)
    source_text: str = ""           # 原文片段（可追溯）

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["start"] = list(self.start) if self.start else None
        d["end"] = list(self.end) if self.end else None
        return d


@dataclass
class ResumeProfile:
    name: str = ""
    experiences: list[Experience] = field(default_factory=list)
    skills: list[str] = field(default_factory=list)
    education: list[str] = field(default_factory=list)
    raw_text: str = ""
    # 人工确认：E2 抽取结果必须可编辑，防错
    user_confirmed: bool = False

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["experiences"] = [e.to_dict() for e in self.experiences]
        return d


# ---------- E4 疑点检测 ----------

@dataclass
class Suspicion:
    type: str                       # timeline_overlap | timeline_gap | no_quantification
                                   # | skill_without_evidence | keyword_stuffing
    location: str                   # 哪段经历/哪个字段
    detail: str                     # 具体证据（哪两段重叠几个月、哪条零数字）
    suggestion: str                 # 修改建议
    severity: str = "medium"        # high | medium | low
    program_verified: bool = True   # 恒 True：本模块只产出程序可判的疑点

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ---------- E3 匹配度 ----------

@dataclass
class MatchItem:
    requirement: str
    status: str = "missing"         # covered | partial | missing
    evidence: str = ""              # 哪段经历支撑（可追溯铁律）
    note: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class MatchReport:
    job_title: str = ""
    coverage: float = 0.0           # 覆盖率 0~1
    items: list[MatchItem] = field(default_factory=list)
    missing_hard: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["items"] = [i.to_dict() for i in self.items]
        return d


# ---------- J3 质检报告 ----------

@dataclass
class QualityReport:
    keyword_coverage: float = 0.0
    quantified_ratio: float = 0.0
    cliche_hits: list[str] = field(default_factory=list)      # 命中套话
    ats_issues: list[str] = field(default_factory=list)       # ATS 友好度问题
    consistency_issues: list[str] = field(default_factory=list)  # 与经历库不一致
    suspicions: list[Suspicion] = field(default_factory=list)    # 复用 E4
    passed: bool = False

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["suspicions"] = [s.to_dict() for s in self.suspicions]
        return d
