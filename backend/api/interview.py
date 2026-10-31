"""三题模拟面试与可复核评分。

面试题和评分先由确定性规则生成，保证演示在模型暂时不可用时仍然可完成。
每个分数都带有程序可复核的证据；后续如果接入模型，模型只能补充文字反馈，
不能替换四个维度的事实评分。
"""
from __future__ import annotations

import re
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from core import events
from engine.resume_parser import profile_from_dict
from engine.suspicion import run_all

router = APIRouter(prefix="/api/interview", tags=["interview"])
from api.interview_v2 import router as continuous_router
router.include_router(continuous_router)
QUESTION_CATEGORIES = ("timeline", "skill_authenticity", "project_match")


class InterviewRequest(BaseModel):
    resume_markdown: str = ""
    resume_profile: dict
    jd_text: str = ""


class InterviewScoreRequest(BaseModel):
    resume_profile: dict
    jd_text: str = ""
    question: dict
    answer: str = Field(default="", max_length=12000)


def _first_detail(profile, category: str) -> dict[str, Any]:
    experiences = profile.experiences
    if category == "timeline":
        periods = [e for e in experiences if e.period]
        if len(periods) >= 2:
            evidence = "；".join(f"{e.name or e.kind}（{e.period}）" for e in periods[:2])
            question = "请按时间线介绍这两段经历的先后关系，并说明每段中你本人承担的工作。"
        elif periods:
            evidence = f"{periods[0].name or periods[0].kind}（{periods[0].period}）"
            question = "请按时间线讲清这段经历的起止时间、你的职责，以及它和前后经历的衔接。"
        else:
            evidence = "经历中没有可解析的时间字段"
            question = "你的简历没有清晰的时间线，请说明每段经历的先后关系和时间依据。"
        return {"question": question, "evidence": evidence, "focus": "时间线与个人职责"}

    if category == "skill_authenticity":
        declared_skill = next((str(item).strip() for item in profile.skills if str(item).strip()), "")
        skill = declared_skill or "简历中的核心技能"
        supporting = (
            [e for e in experiences if skill.lower() in " ".join(e.skills + e.actions + e.results).lower()]
            if declared_skill else []
        )
        evidence = (
            f"技能“{skill}”在经历中出现于：" + "、".join(e.name or e.kind for e in supporting[:3])
            if supporting
            else f"技能清单声明“{skill}”，经历描述中暂未找到直接支撑"
        )
        return {
            "question": f"你在简历中写了“{skill}”。请举一段具体经历，说明你如何使用它、解决了什么问题。",
            "evidence": evidence,
            "focus": "技能使用证据与个人贡献",
        }

    exp = experiences[0] if experiences else None
    name = (exp.name or exp.kind) if exp else "简历中的项目"
    result = exp.results[0] if exp and exp.results else "未填写量化结果"
    return {
        "question": f"请介绍项目“{name}”中最重要的一项成果，说明目标、你的关键行动、结果和复盘。",
        "evidence": f"项目：{name}；成果依据：{result}",
        "focus": "项目成果与岗位匹配",
    }


def _build_questions(profile, jd_text: str) -> list[dict[str, Any]]:
    suspicions = run_all(profile)
    by_type = {s.type: s for s in suspicions}
    out: list[dict[str, Any]] = []
    for index, category in enumerate(QUESTION_CATEGORIES, start=1):
        detail = _first_detail(profile, category)
        suspicion = by_type.get({
            "timeline": "timeline_overlap",
            "skill_authenticity": "skill_without_evidence",
            "project_match": "no_quantification",
        }[category])
        out.append({
            "id": f"q{index}",
            "index": index,
            "category": category,
            "question": detail["question"],
            "evidence": detail["evidence"],
            "focus": detail["focus"],
            "trap": suspicion.detail if suspicion else "请只使用简历中能举证的事实，明确区分个人贡献与团队结果。",
            "source_suspicion": suspicion.type if suspicion else "rule_based_prompt",
            "answer_key": "背景/目标 → 个人行动 → 结果证据 → 复盘与岗位迁移",
        })
    return out


def _canonical_question(profile, jd_text: str, requested: dict[str, Any]) -> dict[str, Any]:
    """只接受服务端按当前简历生成的题目，避免客户端篡改评分依据。"""
    question_id = str(requested.get("id") or "")
    question = next((item for item in _build_questions(profile, jd_text) if item["id"] == question_id), None)
    if question is None:
        raise HTTPException(status_code=422, detail="题目已失效，请重新开始一轮面试。")
    return question


def _tokens(text: str) -> set[str]:
    words = set(re.findall(r"[A-Za-z][A-Za-z0-9+#.\-]{1,}", text or ""))
    words |= set(re.findall(r"[\u4e00-\u9fff]{2,}", text or ""))
    return {word.lower() for word in words}


def _score_answer(profile, jd_text: str, question: dict[str, Any], answer: str) -> dict[str, Any]:
    answer = answer.strip()
    if not answer:
        raise HTTPException(status_code=422, detail="请先填写本题回答，再提交评分。")

    evidence_text = str(question.get("evidence") or "")
    evidence_tokens = {t for t in _tokens(evidence_text) if len(t) >= 2}
    answer_tokens = _tokens(answer)
    evidence_hits = sorted(token for token in evidence_tokens if token in answer or token in answer_tokens)
    evidence_score = min(100, 35 + len(evidence_hits) * 15)
    if any(char.isdigit() for char in answer):
        evidence_score = min(100, evidence_score + 10)

    jd_tokens = {t for t in _tokens(jd_text) if len(t) >= 2}
    jd_hits = sorted(token for token in jd_tokens if token in answer or token in answer_tokens)
    match_score = 60 if not jd_tokens else min(100, 35 + len(jd_hits) * 15)

    sentence_count = max(1, len(re.findall(r"[。！？.!?]", answer)))
    clarity_score = min(100, 35 + min(40, len(answer) // 6) + (15 if sentence_count >= 2 else 0))

    structure_markers = ("背景", "目标", "任务", "行动", "结果", "数据", "复盘", "STAR", "挑战")
    structure_hits = [marker for marker in structure_markers if marker.lower() in answer.lower()]
    structure_score = min(100, 30 + len(structure_hits) * 12 + (10 if len(answer) >= 80 else 0))

    dimensions = {
        "evidence": evidence_score,
        "job_match": match_score,
        "clarity": clarity_score,
        "structure": structure_score,
    }
    total = round(sum(dimensions.values()) / len(dimensions), 1)
    issues: list[str] = []
    if not evidence_hits:
        issues.append("回答没有复述题目依据中的具体项目、技能或时间信息。")
    if jd_tokens and not jd_hits:
        issues.append("回答尚未体现岗位关键词与经历的对应关系。")
    if sentence_count < 2:
        issues.append("表达只有一个句群，建议拆成背景、行动和结果。")
    if len(structure_hits) < 2:
        issues.append("缺少清晰的 STAR 结构标记或复盘。")
    if not any(char.isdigit() for char in answer):
        issues.append("暂未给出数字或范围；若原始材料没有数字，请补充可核验的定性结果。")

    if total >= 80:
        summary = "回答覆盖了主要事实，可以继续压缩措辞并突出岗位迁移。"
    elif total >= 60:
        summary = "回答有部分依据，但还需要更清楚地说明个人行动和结果。"
    else:
        summary = "回答依据不足，建议按推荐结构重答，避免只讲背景或团队成果。"

    return {
        "score": total,
        "dimensions": dimensions,
        "evidence": {
            "matched_resume_tokens": evidence_hits,
            "matched_jd_tokens": jd_hits,
            "structure_markers": structure_hits,
            "question_basis": evidence_text,
        },
        "summary": summary,
        "issues": issues,
        "improvement": "；".join(issues[:3]) if issues else "保持事实依据，补一句与目标岗位的迁移关系。",
        "recommended_structure": "背景/目标 → 个人行动 → 结果证据（数字或定性产出）→ 复盘 → 与岗位匹配",
        "scored_by": "deterministic_rules",
    }


@router.post("")
def interview(req: InterviewRequest):
    """生成一轮固定三题：时间线、技能真实性、项目成果/岗位匹配。"""
    profile = profile_from_dict(req.resume_profile)
    if not profile.experiences:
        raise HTTPException(status_code=422, detail="至少确认一段经历后，才能生成有依据的面试题。")
    events.emit("interview_started")
    questions = _build_questions(profile, req.jd_text)
    suspicions = run_all(profile)
    events.emit("interview_done", questions=len(questions), suspicions=len(suspicions))
    return {
        "ok": True,
        "round": 1,
        "questions": questions,
        "suspicions": [s.to_dict() for s in suspicions],
        "scoring_dimensions": ["evidence", "job_match", "clarity", "structure"],
    }


@router.post("/score")
def score_interview(req: InterviewScoreRequest):
    """提交单题文字回答并返回带证据的四维评分。"""
    profile = profile_from_dict(req.resume_profile)
    if not profile.experiences:
        raise HTTPException(status_code=422, detail="至少确认一段经历后，才能进行有依据的评分。")
    question = _canonical_question(profile, req.jd_text, req.question)
    result = _score_answer(profile, req.jd_text, question, req.answer)
    events.emit("interview_answer_scored", question_id=question["id"], score=result["score"])
    return {"ok": True, "question_id": question["id"], **result}
