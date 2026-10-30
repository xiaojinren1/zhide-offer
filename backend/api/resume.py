"""J2 定制简历生成 API。

防幻觉铁律（设计文档 5.3.2）：LLM 只做改写/拼接/排序，禁止新增事实。
生成后跑一遍可追溯校验：抽 N 条陈述回溯经历库，回溯不了就标出来，
不让虚构内容流到用户手上——自己产品造假，凭什么验别人。
"""
from __future__ import annotations

import os
import re

from fastapi import APIRouter, File, Form, UploadFile, HTTPException
from pydantic import BaseModel

from core import events
from core.llm import chat, chat_with_tools, is_configured
from core.tools import TOOL_SPECS, build_executor
from engine.quality_check import check_markdown, untraceable_numbers
from engine.resume_parser import extract_text, parse_resume, profile_from_dict
from core.config import agent_rules

router = APIRouter(prefix="/api/resume", tags=["resume"])

_SYSTEM = """你是简历改写器。给定目标 JD 和候选人的结构化经历库，
产出一份针对该 JD 定制的简历正文（Markdown）。

工作方式（必须遵守）：
1. 先写第一版简历正文；
2. **必须调用 check_resume_quality 工具检查你写的这一版**；
3. 按返回 issues 里的 fix 逐条修订，写出第二版；
4. 修订后再调用一次工具确认，若仍有 high 级问题就继续改；
5. 没有 high 级问题后，输出最终简历正文（纯 Markdown，不要解释）。

绝对规则（违反即失败）：
1. 只能使用经历库中已有的事实做**改写、拼接、排序、侧重调整**；
2. **严禁新增任何经历库中没有的事实、数字、公司、项目**；
3. 每条经历用 STAR 结构：情境-任务-行动-结果，结果优先放量化数据；
4. 按 JD 要求重排经历顺序与措辞，让匹配点前置；
5. 技能清单只允许从经历库技能中挑选并重排，不许添加；
6. 输入里的 reference_examples 是同岗位的**优秀写法范例，只许参考其句式、
   结构与量化方式；严禁照搬其中任何事实、数字、公司、项目**——范例里的
   数字不属于你的候选人，写进来就是虚构。
7. 原始材料没有量化数据时，使用已有的定性产出，不推断数字或量级；
   原始资料待补充项不属于改写可修复的问题，不要为其反复调用工具。
8. 最终回复必须以 Markdown 一级标题的姓名开始，直接交付完整简历，
   不要输出思考过程、质检讨论或下一步计划。"""


class GenerateRequest(BaseModel):
    jd_text: str
    resume_profile: dict
    jd_keywords: list[str] = []     # 前端从诊断步带过来，缺失则程序提取
    use_examples: bool = True       # 是否启用范例库检索（可关闭做对照实验）


# --------------------------------------------------------------------------
# 上下文瘦身（借鉴 Pi 的核心实证：上下文体积就是成本和质量）
# --------------------------------------------------------------------------

def _bigrams(text: str) -> set[str]:
    t = re.sub(r"\s+", "", text or "")
    return {t[i:i + 2] for i in range(len(t) - 1)} if len(t) >= 2 else set()


def _exp_text(e) -> str:
    return " ".join([e.name, e.role] + e.actions + e.results + e.skills)


def _jd_keywords_programmatic(jd_text: str) -> list[str]:
    """无 LLM 调用的 JD 关键词提取（兜底）：英文词 + 高频中文二元组。

    注意：中文二元组必须按**文本顺序**计数（不是按集合），否则每个词只出现
    一次，`c >= 2` 的阈值永远不成立（v1 踩过，测试抓出来的）。
    """
    words = re.findall(r"[A-Za-z][A-Za-z0-9+#.\-]{1,}", jd_text or "")
    cleaned = re.sub(r"\s+", "", jd_text or "")
    freq: dict[str, int] = {}
    for i in range(len(cleaned) - 1):
        bg = cleaned[i:i + 2]
        if re.search(r"[\u4e00-\u9fff]", bg):
            freq[bg] = freq.get(bg, 0) + 1
    top_cn = [w for w, c in sorted(freq.items(), key=lambda x: -x[1]) if c >= 2][:20]
    return sorted({w.lower() for w in words if len(w) >= 2} | set(top_cn))


def _relevance(jd_text: str, jd_keywords: list[str], e) -> float:
    """经历与 JD 的相关度：JD 关键词命中（权重高）+ 字符二元组包含度。"""
    exp_text = _exp_text(e).lower()
    kw_hits = sum(1 for k in (jd_keywords or []) if k and k.lower() in exp_text)
    jd_bg, exp_bg = _bigrams(jd_text), _bigrams(_exp_text(e))
    containment = len(jd_bg & exp_bg) / max(1, len(exp_bg))
    return kw_hits * 0.15 + containment


def slim_experiences(profile, jd_text: str, jd_keywords: list[str], max_n: int):
    """挑出与 JD 最相关的 max_n 段经历；返回 (选中, 未选中, 实际用的关键词)。

    只做筛选不做改写——经历库是事实来源，瘦身只为省 token 与聚焦。
    max_n <= 0 表示不瘦身（全量保留），避免"挑 0 段"把生成变成无米之炊。
    """
    if not jd_keywords:
        jd_keywords = _jd_keywords_programmatic(jd_text)
    scored = sorted(
        profile.experiences,
        key=lambda e: -_relevance(jd_text, jd_keywords, e),
    )
    if max_n and max_n > 0:
        return scored[:max_n], scored[max_n:], jd_keywords
    return scored, [], jd_keywords


@router.post("/parse")
async def parse_resume_file(file: UploadFile = File(...)):
    """上传简历 → 文本 → 结构化经历库（前端展示供人工确认）。"""
    content = await file.read()
    try:
        text = extract_text(file.filename, content)
    except Exception as exc:
        events.emit_error("resume_extract", exc)
        return {"ok": False, "error": str(exc)}
    if not is_configured():
        raise HTTPException(status_code=503, detail="请在 backend/.env 配置应用 API key 后再解析")
    try:
        profile = parse_resume(text)
    except Exception as exc:
        events.emit_error("resume_parse", exc)
        return {"ok": False, "error": str(exc)}
    events.emit("resume_parsed", experiences=len(profile.experiences))
    return {"ok": True, "profile": profile.to_dict(), "raw_text": text}


@router.post("/parse-text")
def parse_resume_text(payload: dict):
    """粘贴简历文本 → 结构化（无文件时的入口）。"""
    text = str(payload.get("text") or "")
    if not is_configured():
        raise HTTPException(status_code=503, detail="请在 backend/.env 配置应用 API key 后再解析")
    try:
        profile = parse_resume(text)
    except Exception as exc:
        events.emit_error("resume_parse", exc)
        return {"ok": False, "error": str(exc)}
    return {"ok": True, "profile": profile.to_dict(), "raw_text": text}


@router.post("/generate")
def generate(req: GenerateRequest):
    """按 JD 定制简历。返回 Markdown + 可追溯校验结果 + 瘦身报告。"""
    events.emit("resume_generate_started", jd_len=len(req.jd_text or ""))
    if req.resume_profile.get("user_confirmed") is not True:
        raise HTTPException(status_code=422, detail="请先核对并确认经历事实，再生成简历")
    if not req.jd_text.strip():
        raise HTTPException(status_code=422, detail="请先填写目标岗位 JD")
    profile = profile_from_dict(req.resume_profile)
    if not profile.experiences:
        raise HTTPException(status_code=422, detail="请先补充至少一段真实经历")

    if not is_configured():
        raise HTTPException(status_code=503, detail="请在 backend/.env 配置应用 API key 后再生成")

    max_n = int(os.environ.get("JOBAGENT_MAX_EXPERIENCES") or 4)
    selected, dropped, used_kw = slim_experiences(
        profile, req.jd_text, list(req.jd_keywords or []), max_n
    )
    events.emit("resume_generate_slimmed",
                total=len(profile.experiences), selected=len(selected),
                dropped=[e.name for e in dropped])

    # 范例库检索（轻量 RAG）：按 JD 相关度取 top-3 作为写法参考
    examples_used: list[dict] = []
    if req.use_examples:
        try:
            from engine.example_lib import retrieve

            examples_used = retrieve(req.jd_text, used_kw, top_k=3)
        except Exception as exc:
            events.emit_error("example_retrieve", exc)
    events.emit("resume_generate_examples", count=len(examples_used),
                ids=[e.get("id") for e in examples_used])

    payload = {
        "name": profile.name,
        "jd": req.jd_text,
        "jd_keywords": used_kw[:40],
        "experiences": [
            {"name": e.name, "role": e.role, "period": e.period,
             "actions": e.actions, "results": e.results, "skills": e.skills}
            for e in selected
        ],
        "skills": profile.skills,
        "education": profile.education,
        "reference_examples": examples_used,
        "writing_methodology": [
            "STAR：情境-任务-行动-结果，四步缺一不可",
            "动词开头、结果导向、数据证明",
            "量化收益（营收/成本/效率）、规模（用户数/订单量）、时间（周期缩短%）",
            "用前后对比值（从 X 到 Y），不用'大幅提升'这类模糊词",
            "数据涉密时用相对值或排名",
        ],
    }
    try:
        loop = chat_with_tools(
            _SYSTEM + agent_rules(),
            f"输入：{payload}\n\n请按工作方式输出定制简历正文（Markdown）。",
            tools=TOOL_SPECS,
            executor=build_executor(profile=profile, jd_keywords=used_kw)[0],
            max_rounds=int(os.environ.get("JOBAGENT_TOOL_ROUNDS") or 3),
        )
        md = loop["content"]
    except Exception as exc:
        events.emit_error("resume_generate", exc)
        return {"ok": False, "error": str(exc)}

    if loop.get("deadline_hit"):
        raise HTTPException(status_code=504, detail="模型生成或自检未完成，请检查服务状态后重试")
    if not md or not md.strip():
        raise HTTPException(status_code=502, detail="模型返回了空内容，请重新生成")

    # 收尾仍以全量经历库为真值做一次独立校验（不依赖模型自报）
    report = check_markdown(md, profile, used_kw)
    untraceable = untraceable_numbers(md, profile)
    events.emit("resume_generate_done", untraceable=len(untraceable),
                tool_rounds=loop.get("rounds"), tool_calls=loop.get("tool_calls"))
    return {
        "ok": True,
        "markdown": md,
        "untraceable": untraceable,
        "traceability_passed": not untraceable,
        "self_check": {
            "rounds": loop.get("rounds"),
            "tool_calls": loop.get("tool_calls"),
            "issues_remaining": report["issue_count"],
            "high_remaining": report["high_count"],
            "passed": report["ok"],
        },
        "slimming": {
            "total": len(profile.experiences),
            "used": len(selected),
            "dropped": [e.name for e in dropped],
        },
        "examples_used": len(examples_used),
    }
