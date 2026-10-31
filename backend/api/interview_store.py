"""面试专用状态；共享账户数据库和已完成记录，不改公共账户模块。"""
from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from hashlib import sha256
from threading import RLock

from fastapi import HTTPException

from api.workspace import encode_record, timestamp
from api.interview_records import MAX_INTERVIEW_BYTES
from core import accounts
from engine.interview_v2 import context_from_bank

# 有界条带锁避免请求重试重复调用模型；数据库版本比较同时保护多进程。
_LOCKS = tuple(RLock() for _ in range(64))


def lock(key: str):
    return _LOCKS[int(sha256(key.encode()).hexdigest(), 16) % len(_LOCKS)]


@contextmanager
def connection():
    with accounts.connection() as db:
        db.execute("""CREATE TABLE IF NOT EXISTS interview_artifacts (
            id TEXT NOT NULL, user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            kind TEXT NOT NULL, revision INTEGER NOT NULL, payload TEXT NOT NULL,
            updated_at TEXT NOT NULL, PRIMARY KEY(id,user_id))""")
        # 临时题库/会话仅用于当前页请求及重试，七天后清理；完成记录不受影响。
        db.execute("DELETE FROM interview_artifacts WHERE updated_at < strftime('%Y-%m-%dT%H:%M:%S','now','-7 days')")
        yield db


def load(artifact_id: str, user_id: str, kind: str) -> tuple[dict, int]:
    with connection() as db:
        row = db.execute("SELECT payload,revision FROM interview_artifacts WHERE id=? AND user_id=? AND kind=?",
                         (artifact_id, user_id, kind)).fetchone()
    if row is None:
        raise HTTPException(404, "面试内容不存在或已过期")
    return json.loads(row["payload"]), row["revision"]


def find(artifact_id: str, user_id: str, kind: str):
    try:
        return load(artifact_id, user_id, kind)
    except HTTPException as exc:
        if exc.status_code != 404:
            raise
        return None


def write(artifact_id: str, user_id: str, kind: str, payload: dict, revision: int | None) -> int:
    encoded = encode_record(payload, 2 * MAX_INTERVIEW_BYTES)
    with connection() as db:
        if revision is None:
            changed = db.execute("INSERT OR IGNORE INTO interview_artifacts VALUES(?,?,?,1,?,?)",
                                 (artifact_id, user_id, kind, encoded, timestamp())).rowcount
        else:
            changed = db.execute("UPDATE interview_artifacts SET payload=?,revision=revision+1,updated_at=? "
                                 "WHERE id=? AND user_id=? AND revision=?",
                                 (encoded, timestamp(), artifact_id, user_id, revision)).rowcount
        if not changed:
            raise HTTPException(409, "本轮内容已变化，请勿重复提交")
    return 1 if revision is None else revision + 1


def persist_completed(session: dict, user_id: str) -> None:
    """相同会话只创建一条历史；报告已在会话内留存，写入失败可重试。"""
    context = session.get("context") or context_from_bank(session["bank"], session["snapshot"])
    record = {
        "title": context["job_title"][:170] + " · 连续模拟面试",
        "jd_text": session["snapshot"]["jd_text"],
        "questions": [t["question"] for t in session["turns"]],
        "answers": [t["answer"] or "" for t in session["turns"]],
        "question_scores": [],
        "overall_feedback": {"schema_version": 3, "mode": session.get("mode", "bank"),
                             "context": context, "snapshot": session["snapshot"], "bank": session["bank"],
                             "transcript": session["turns"], "report": session["report"],
                             "elapsed_seconds": session["elapsed_seconds"]},
    }
    encoded = encode_record(record, MAX_INTERVIEW_BYTES)
    with connection() as db:
        artifact = db.execute("SELECT payload FROM interview_artifacts WHERE id=? AND user_id=? AND kind='session'",
                              (session["id"], user_id)).fetchone()
        if artifact is None:
            raise HTTPException(404, "面试内容不存在或已过期")
        state = json.loads(artifact["payload"])
        if state.get("history_saved"):
            exists = db.execute("SELECT 1 FROM interview_records WHERE id=? AND user_id=?",
                                (session["id"], user_id)).fetchone()
            if exists is None:
                raise HTTPException(410, "这条面试历史已删除，旧请求不能重新保存")
            return
        db.execute("INSERT OR IGNORE INTO interview_records(id,user_id,title,saved_at,record_json) VALUES(?,?,?,?,?)",
                   (session["id"], user_id, record["title"], timestamp(), encoded))
        # 与历史写入同一事务，避免删除之后的迟到重试重新创建记录。
        state["history_saved"] = True
        db.execute("UPDATE interview_artifacts SET payload=?,revision=revision+1,updated_at=? WHERE id=? AND user_id=?",
                   (encode_record(state, 2 * MAX_INTERVIEW_BYTES), timestamp(), session["id"], user_id))


def unavailable(exc: sqlite3.Error):
    raise HTTPException(503, "面试状态暂时无法保存，已有内容不变，请重试") from exc
