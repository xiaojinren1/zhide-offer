"""个性化题库、连续对话和整体报告，旧接口继续兼容。"""
from __future__ import annotations

import copy
import hashlib
import json
import sqlite3
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, model_validator

from api import interview_store as store
from api.workspace import ProfileState, check_account, encode_record, timestamp
from core import accounts
from engine import interview_v2 as engine

router = APIRouter()


class Request(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")
    expected_user_id: str = Field(min_length=1, max_length=100)
    request_id: str = Field(min_length=1, max_length=80)

    @model_validator(mode="after")
    def uuid_request(self):
        try:
            UUID(self.request_id)
        except ValueError as exc:
            raise ValueError("request_id 必须为 UUID") from exc
        return self


class BankRequest(Request):
    resume_profile: ProfileState
    resume_markdown: str = Field(min_length=1, max_length=60000)
    jd_text: str = Field(min_length=1, max_length=20000)


class StartRequest(Request):
    bank_id: str | None = Field(default=None, min_length=1, max_length=100)
    resume_profile: ProfileState | None = None
    resume_markdown: str | None = Field(default=None, min_length=1, max_length=60000)
    jd_text: str | None = Field(default=None, min_length=1, max_length=20000)

    @model_validator(mode="after")
    def one_source(self):
        materials = (self.resume_profile, self.resume_markdown, self.jd_text)
        if self.bank_id is not None:
            if any(value is not None for value in materials):
                raise ValueError("题库与直接面试材料不能同时提交")
        elif any(value is None for value in materials):
            raise ValueError("直接面试必须提供最新生成简历、已确认经历和岗位JD")
        return self


class TurnRequest(Request):
    bank_id: str | None = None
    session_id: str | None = None
    version: int = Field(default=0, ge=0)
    answer: str = Field(default="", max_length=12000)
    skip: bool = False
    elapsed_seconds: int = Field(default=0, ge=0, le=86400)

    @model_validator(mode="after")
    def one_target(self):
        if bool(self.bank_id) == bool(self.session_id):
            raise ValueError("提供题库或面试会话中的一个")
        return self


class ReportRequest(Request):
    session_id: str
    version: int = Field(ge=1)
    elapsed_seconds: int = Field(ge=0, le=86400)
    final_answer: str = Field(default="", max_length=12000)


def fingerprint(req: Request) -> str:
    return hashlib.sha256(json.dumps(req.model_dump(), sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def public_session(session: dict) -> dict:
    return {"id": session["id"], "bank_id": session["bank_id"], "version": session["version"],
            "status": session["status"], "turns": session["turns"], "elapsed_seconds": session["elapsed_seconds"],
            "job_title": session_context(session)["job_title"], "started_at": session["started_at"],
            "mode": session.get("mode", "bank"), "snapshot": session["snapshot"]}


def session_context(session: dict) -> dict:
    # 同时支持升级前仍在进行的 v2 会话。
    return session["context"] if "context" in session else engine.context_from_bank(session["bank"], session["snapshot"])


def response(session: dict):
    return {"ok": True, "session": public_session(session)}


def duplicate(session: dict, req: Request) -> bool:
    if session.get("last_request_id") == req.request_id:
        if session.get("last_fingerprint") != fingerprint(req):
            raise HTTPException(409, "相同请求编号不能提交不同内容")
        return True
    return False


def validate_version(session: dict, version: int):
    if session["version"] != version:
        raise HTTPException(409, "面试内容已更新，请勿重复提交")


def make_snapshot(profile: ProfileState, markdown: str, jd: str) -> dict:
    profile_data = profile.model_dump()
    if not profile_data["user_confirmed"] or not profile_data["experiences"] or not jd.strip() or not markdown.strip():
        raise HTTPException(422, "请先确认至少一段经历，生成简历并填写岗位 JD")
    snapshot = {"resume_profile": profile_data, "resume_markdown": markdown, "jd_text": jd,
                "captured_at": timestamp()}
    encode_record(snapshot, 400000)
    return snapshot


@router.post("/bank")
def bank(req: BankRequest, user: dict = Depends(accounts.require_user)):
    check_account(req.expected_user_id, user)
    snapshot = make_snapshot(req.resume_profile, req.resume_markdown, req.jd_text)
    artifact_id = "bank-" + req.request_id
    try:
        with store.lock(user["id"] + artifact_id):
            found = store.find(artifact_id, user["id"], "bank")
            if found:
                data = found[0]
                if data["fingerprint"] != fingerprint(req):
                    raise HTTPException(409, "相同请求编号不能生成不同题库")
            else:
                data = {"id": artifact_id, "snapshot": snapshot, "fingerprint": fingerprint(req), **engine.generate_bank(snapshot)}
                store.write(artifact_id, user["id"], "bank", data, None)
        return {"ok": True, "bank": {k: v for k, v in data.items() if k != "fingerprint"}}
    except sqlite3.Error as exc:
        store.unavailable(exc)


def create_session(req: Request, user: dict, bank_id: str | None, snapshot: dict | None = None):
    session_id = "session-" + req.request_id
    with store.lock(user["id"] + session_id):
        found = store.find(session_id, user["id"], "session")
        if found:
            if duplicate(found[0], req):
                return response(found[0])
            raise HTTPException(409, "本轮已开始")
        if bank_id:
            bank_data, _ = store.load(bank_id, user["id"], "bank")
            snapshot = bank_data["snapshot"]
            context = engine.context_from_bank(bank_data, snapshot)
            question = engine.next_question(context, [], 0)
            practice_bank = {k: bank_data[k] for k in ("job_title", "questions", "sources")}
        else:
            context, question = engine.start_direct(snapshot)
            practice_bank = None
        session = {"id": session_id, "bank_id": bank_id, "snapshot": snapshot,
                   "bank": practice_bank, "context": context, "mode": "bank" if bank_id else "direct",
                   "version": 1, "status": "active", "started_at": timestamp(), "elapsed_seconds": 0,
                   "turns": [{"id": "turn-1", "question": question, "answer": None, "skipped": False}],
                   "last_request_id": req.request_id, "last_fingerprint": fingerprint(req)}
        # 只有全部模型字段通过校验才保存，失败重试不创建半完成会话。
        store.write(session_id, user["id"], "session", session, None)
        return response(session)


@router.post("/start")
def start(req: StartRequest, user: dict = Depends(accounts.require_user)):
    check_account(req.expected_user_id, user)
    snapshot = None if req.bank_id else make_snapshot(req.resume_profile, req.resume_markdown, req.jd_text)
    try:
        return create_session(req, user, req.bank_id, snapshot)
    except sqlite3.Error as exc:
        store.unavailable(exc)


@router.post("/turn")
def turn(req: TurnRequest, user: dict = Depends(accounts.require_user)):
    check_account(req.expected_user_id, user)
    if req.bank_id:
        if req.version or req.answer or req.skip:
            raise HTTPException(422, "开始面试时不提交回答")
        try:
            return create_session(req, user, req.bank_id)
        except sqlite3.Error as exc:
            store.unavailable(exc)
    session_id = req.session_id or "session-" + req.request_id
    try:
        with store.lock(user["id"] + session_id):
            found = store.find(session_id, user["id"], "session")
            if not found:
                raise HTTPException(404, "面试内容不存在或已过期")
            session, revision = found
            if duplicate(session, req):
                return response(session)
            validate_version(session, req.version)
            if session["status"] != "active":
                raise HTTPException(409, "本轮已结束，请重试生成报告")
            if not req.skip and not req.answer.strip():
                raise HTTPException(422, "请输入回答或选择跳过")
            if req.skip and req.answer.strip():
                raise HTTPException(422, "跳过时不能同时提交回答")
            if len(session["turns"]) >= 100:
                raise HTTPException(422, "本轮已达100次对话，请结束并查看复盘")
            session = copy.deepcopy(session)
            session["turns"][-1].update(answer=req.answer.strip(), skipped=req.skip)
            session["elapsed_seconds"] = max(session["elapsed_seconds"], req.elapsed_seconds)
            question = engine.next_question(session_context(session), session["turns"], session["elapsed_seconds"])
            session["turns"].append({"id": f"turn-{len(session['turns']) + 1}", "question": question,
                                     "answer": None, "skipped": False})
            session["version"] += 1
            session.update(last_request_id=req.request_id, last_fingerprint=fingerprint(req))
            store.write(session_id, user["id"], "session", session, revision)
            return response(session)
    except sqlite3.Error as exc:
        store.unavailable(exc)


@router.post("/report")
def report(req: ReportRequest, user: dict = Depends(accounts.require_user)):
    check_account(req.expected_user_id, user)
    try:
        with store.lock(user["id"] + req.session_id):
            session, revision = store.load(req.session_id, user["id"], "session")
            if session["status"] == "active":
                validate_version(session, req.version)
                # 先冻结本轮。模型失败不撤回结束，也不重复追加最后一份回答。
                session["turns"][-1]["answer"] = req.final_answer.strip() or None
                session.update(status="ended", elapsed_seconds=max(session["elapsed_seconds"], req.elapsed_seconds),
                               end_fingerprint=fingerprint(req))
                revision = store.write(req.session_id, user["id"], "session", session, revision)
            elif session["end_fingerprint"] != fingerprint(req):
                raise HTTPException(409, "本轮已结束，请使用原结束请求重试")
            if "report" not in session:
                session["report"] = engine.evaluate_interview(session_context(session), session["turns"])
                revision = store.write(req.session_id, user["id"], "session", session, revision)
            saved, save_error = True, None
            try:
                store.persist_completed(session, user["id"])
            except HTTPException as exc:
                if exc.status_code == 410:
                    raise
                saved, save_error = False, "报告已生成，历史保存失败，请重试保存。"
            except sqlite3.Error:
                saved, save_error = False, "报告已生成，历史保存失败，请重试保存。"
            return {"ok": True, "session": public_session(session), "report": session["report"],
                    "saved": saved, "save_error": save_error, "record_id": session["id"] if saved else None}
    except sqlite3.Error as exc:
        store.unavailable(exc)
