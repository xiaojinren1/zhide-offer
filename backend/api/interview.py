"""J4 面试预演 API——演示爆点：AI 当面试官，专挖简历里的坑。

关键约束（设计文档 5.3.2）：只挖 E4 能定位的疑点类型（没写基数/无法归因/
时间重叠/技能无支撑），不自由发挥——挖出来的每个坑都必须可复核。
"""
from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

from core import events, llm
from engine.resume_parser import profile_from_dict
from engine.suspicion import run_all

router = APIRouter(prefix="/api/interview", tags=["interview"])

_SYSTEM = """你是严苛的业务面试官。给定候选人的定制简历和匹配报告，
只针对简历中**可被质疑的具体点**设计追问。

只输出 JSON：
{
  "questions": [
    {"question": "追问原话", "trap": "这个坑在哪（对应哪条疑点）",
     "answer_key": "好的答题要点", "source_suspicion": "对应的疑点类型"}
  ]
}
规则：
1. 每个追问必须对应给出的疑点清单中的一类，不许自由发挥问无关问题；
2. 语气像真实面试官，直接、不留情；
3. answer_key 给可操作的应对思路，不是空话；
4. 5 条以内，优先 severity=high 的疑点。"""


class InterviewRequest(BaseModel):
    resume_markdown: str
    resume_profile: dict
    jd_text: str = ""


@router.post("")
def interview(req: InterviewRequest):
    events.emit("interview_started")
    profile = profile_from_dict(req.resume_profile)
    suspicions = run_all(profile)
    high = [s for s in suspicions if s.severity == "high"] or suspicions

    payload = {
        "resume": req.resume_markdown,
        "suspicions": [{"type": s.type, "detail": s.detail} for s in high[:6]],
        "jd": req.jd_text[:2000],
    }
    try:
        data = llm.chat_json(_SYSTEM, f"输入：{payload}")
        questions = [q for q in (data.get("questions") or []) if isinstance(q, dict)]
    except Exception as exc:
        events.emit_error("interview", exc)
        return {"ok": False, "error": str(exc)}

    events.emit("interview_done", questions=len(questions), suspicions=len(suspicions))
    return {
        "ok": True,
        "questions": questions,
        "suspicions": [s.to_dict() for s in suspicions],
    }
