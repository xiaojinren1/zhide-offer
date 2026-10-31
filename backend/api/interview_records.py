"""当前账户的面试练习记录存储；不生成或评判答案。"""
from __future__ import annotations

import json
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from api.workspace import check_account, encode_record, timestamp
from core import accounts

router = APIRouter(prefix="/api/interview-records", tags=["interview-records"])
MAX_INTERVIEW_BYTES = 1024 * 1024


class SaveInterviewRequest(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")
    expected_user_id: str = Field(min_length=1)
    title: str = Field(default="面试练习", max_length=200)
    jd_text: str = ""
    questions: list[dict[str, Any]] = Field(default_factory=list)
    answers: list[str] = Field(default_factory=list)
    question_scores: list[dict[str, Any]] = Field(default_factory=list)
    overall_feedback: dict[str, Any] = Field(default_factory=dict)


@router.post("")
def save_record(req: SaveInterviewRequest, user: dict = Depends(accounts.require_user)):
    check_account(req.expected_user_id, user)
    record = req.model_dump(exclude={"expected_user_id"})
    encoded = encode_record(record, MAX_INTERVIEW_BYTES)
    record_id, saved_at = uuid4().hex, timestamp()
    with accounts.connection() as db:
        db.execute(
            "INSERT INTO interview_records(id,user_id,title,saved_at,record_json) VALUES(?,?,?,?,?)",
            (record_id, user["id"], req.title, saved_at, encoded),
        )
    return {"ok": True, "id": record_id, "saved_at": saved_at}


@router.get("")
def list_records(user: dict = Depends(accounts.require_user)):
    with accounts.connection() as db:
        rows = db.execute(
            "SELECT id,title,saved_at FROM interview_records WHERE user_id=? ORDER BY rowid DESC",
            (user["id"],),
        ).fetchall()
    return {"ok": True, "records": [dict(row) for row in rows]}


@router.get("/{record_id}")
def load_record(record_id: str, user: dict = Depends(accounts.require_user)):
    with accounts.connection() as db:
        row = db.execute(
            "SELECT id,title,saved_at,record_json FROM interview_records WHERE id=? AND user_id=?",
            (record_id, user["id"]),
        ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="面试记录不存在")
    record = json.loads(row["record_json"])
    record.update(id=row["id"], title=row["title"], saved_at=row["saved_at"])
    return {"ok": True, "record": record}


@router.delete("/{record_id}")
def delete_record(record_id: str, user: dict = Depends(accounts.require_user)):
    with accounts.connection() as db:
        count = db.execute(
            "DELETE FROM interview_records WHERE id=? AND user_id=?", (record_id, user["id"])
        ).rowcount
        if not count:
            raise HTTPException(status_code=404, detail="面试记录不存在")
    return {"ok": True}
