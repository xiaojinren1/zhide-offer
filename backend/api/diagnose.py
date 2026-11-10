"""J1 JD 匹配诊断 API（E3 的展示层）。"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, field_validator

from core import events
from core.llm import LLMError
from engine.jd_parser import parse_jd
from engine.matcher import match
from engine.resume_parser import profile_from_dict
from engine.role_requirements import generate_role_requirements

router = APIRouter(prefix="/api/diagnose", tags=["diagnose"])


class GenerateRoleRequest(BaseModel):
    job_title: str = Field(min_length=1, max_length=120)

    @field_validator("job_title")
    @classmethod
    def require_title(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("请填写目标岗位名称")
        return value.strip()


@router.post("/generate-role")
def generate_role(req: GenerateRoleRequest):
    jd_text = generate_role_requirements(req.job_title)
    return {"ok": True, "job_title": req.job_title, "jd_text": jd_text}


class DiagnoseRequest(BaseModel):
    jd_text: str
    resume_profile: dict          # 前端已确认的经历库结构（profile_from_dict 回填）


@router.post("")
def diagnose(req: DiagnoseRequest):
    events.emit("diagnose_started", jd_len=len(req.jd_text or ""))
    if not req.jd_text.strip():
        raise HTTPException(status_code=422, detail="请先填写目标岗位 JD")
    stage = "JD 解析"
    try:
        jd = parse_jd(req.jd_text)
        if jd.inferred:
            jd = parse_jd(req.jd_text)
        stage = "岗位匹配"
        resume = profile_from_dict(req.resume_profile)
        report = match(jd, resume)
    except LLMError as exc:
        if exc.status_code == 502:
            detail = ("JD 解析结果有要求缺少原文依据。请核对岗位描述，或尝试用条目列出职责和要求。"
                      if str(exc) == "untraceable JD requirement"
                      else f"{stage}未得到可验证的结果。请重试，或换用能稳定返回 JSON 的文本模型。")
            events.emit("diagnose_model_validation_failed", stage=stage)
            raise HTTPException(502, detail) from None
        raise
    except Exception as exc:
        events.emit_error("diagnose", exc)
        return {"ok": False, "error": str(exc)}

    # 硬性缺失排前面（投前最关心的就是"会不会被直接刷掉"）
    result = report.to_dict()
    result["ok"] = True
    result["jd"] = jd.to_dict()
    result["missing_hard_count"] = len(report.missing_hard)
    events.emit("diagnose_done", coverage=report.coverage, items=len(report.items))
    return result


class ParseJdRequest(BaseModel):
    jd_text: str


@router.post("/parse-jd")
def parse_jd_only(req: ParseJdRequest):
    """只解析 JD（前端上传 JD 后先展示解析结果供确认）。"""
    if not req.jd_text.strip():
        raise HTTPException(status_code=422, detail="请先填写目标岗位 JD")
    try:
        jd = parse_jd(req.jd_text)
    except LLMError:
        raise
    except Exception as exc:
        events.emit_error("parse_jd", exc)
        return {"ok": False, "error": str(exc)}
    return {"ok": True, "jd": jd.to_dict()}
