"""E1 JD 解析器：JD 原文 → 结构化 JSON。

防幻觉设计（设计文档 5.3.1）：每条要求必须能在原文找到依据；
找不到依据的标 inferred=True，不当成硬性要求使用。
"""
from __future__ import annotations

from core.llm import chat_json
from engine.models import ParsedJD
from core.config import agent_rules

_SYSTEM = """你是招聘需求分析器。把用户给的 JD 原文解析成结构化 JSON。
只输出 JSON，字段如下：
{
  "job_title": "岗位名",
  "company": "公司名（没有则为空串）",
  "hard_requirements": ["硬性要求：学历/年限/证书/年龄类"],
  "soft_requirements": ["软性要求：技能/素质/经验类"],
  "responsibilities": ["岗位职责"],
  "keywords": ["该 JD 的核心关键词，5-15 个，用于匹配度计算"],
  "evidence": {"要求原文": "该要求在 JD 中的原文片段（逐字摘录）"}
}
规则：
1. evidence 的 value 必须是 JD 原文中**逐字存在**的片段，不许改写、不许编造。
2. hard_requirements 只放真正会刷人的硬条件（学历/年限/必须证书）。
3. keywords 放岗位核心技能与领域词，不要放"沟通能力"这类泛化词。
4. 严禁把原文没有的要求写进任何字段。"""


def _verify_evidence(jd_text: str, parsed: ParsedJD) -> ParsedJD:
    """程序校验：evidence 的原文依据是否真实存在于 JD 中。

    可追溯铁律：回溯不了的一律降级为 inferred，不参与硬性判断。
    """
    verified: dict[str, str] = {}
    inferred: list[str] = []
    for req, quote in (parsed.evidence or {}).items():
        quote = (quote or "").strip()
        if quote and quote in jd_text:
            verified[req] = quote
        else:
            inferred.append(req)
    # 没有 evidence 的要求也算无依据
    all_reqs = list(parsed.hard_requirements) + list(parsed.soft_requirements)
    for req in all_reqs:
        if req not in verified and req not in inferred:
            inferred.append(req)
    parsed.evidence = verified
    parsed.inferred = inferred
    return parsed


def parse_jd(jd_text: str) -> ParsedJD:
    """解析 JD。LLM 不可用时抛异常（不返回半成品）。"""
    if not jd_text or not jd_text.strip():
        raise ValueError("JD 文本为空")
    data = chat_json(_SYSTEM + agent_rules(), f"JD 原文：\n{jd_text}")
    parsed = ParsedJD(
        job_title=str(data.get("job_title") or "").strip(),
        company=str(data.get("company") or "").strip(),
        hard_requirements=[str(x).strip() for x in (data.get("hard_requirements") or []) if str(x).strip()],
        soft_requirements=[str(x).strip() for x in (data.get("soft_requirements") or []) if str(x).strip()],
        responsibilities=[str(x).strip() for x in (data.get("responsibilities") or []) if str(x).strip()],
        keywords=[str(x).strip() for x in (data.get("keywords") or []) if str(x).strip()],
        evidence={str(k).strip(): str(v) for k, v in (data.get("evidence") or {}).items()},
    )
    return _verify_evidence(jd_text, parsed)
