"""Per-account usage reported by model providers."""
import logging
import sqlite3
from contextvars import ContextVar
from datetime import datetime, timezone

from fastapi import Depends

from core import accounts

_user_id: ContextVar[str | None] = ContextVar("model_usage_user", default=None)
_logger = logging.getLogger(__name__)
PAGE_SIZE = 20


async def bind(user: dict = Depends(accounts.require_user)):
    token = _user_id.set(None if user.get("guest") else user["id"])
    try:
        yield
    finally:
        _user_id.reset(token)


def _count(value):
    return value if type(value) is int and 0 <= value <= 2**53 - 1 else None


def record(requested_model: str, data: dict) -> None:
    user_id = _user_id.get()
    if user_id is None:
        return
    model = data.get("model")
    if not isinstance(model, str) or not model.strip():
        model = requested_model
    usage = data.get("usage")
    usage = usage if isinstance(usage, dict) else {}
    input_tokens = _count(usage.get("prompt_tokens"))
    output_tokens = _count(usage.get("completion_tokens"))
    total_tokens = _count(usage.get("total_tokens"))
    if total_tokens is None and input_tokens is not None and output_tokens is not None:
        total_tokens = input_tokens + output_tokens
    try:
        with accounts.connection() as db:
            db.execute(
                """INSERT INTO model_usage(user_id, model, used_at, input_tokens, output_tokens, total_tokens)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (user_id, model[:256], datetime.now(timezone.utc).isoformat(),
                 input_tokens, output_tokens, total_tokens),
            )
    except (sqlite3.Error, OSError):
        _logger.warning("Could not persist model usage")


def report(user_id: str, before: int | None, start: str | None = None, end: str | None = None) -> dict:
    where = "user_id = ?"
    params: tuple = (user_id,)
    if start is not None:
        where += " AND used_at >= ?"
        params += (start,)
    if end is not None:
        where += " AND used_at < ?"
        params += (end,)
    with accounts.connection() as db:
        models = [dict(row) for row in db.execute(
            f"""SELECT model, COUNT(*) AS calls, COUNT(*) - COUNT(total_tokens) AS unknown_calls,
                      SUM(input_tokens) AS input_tokens, SUM(output_tokens) AS output_tokens,
                      SUM(total_tokens) AS total_tokens
               FROM model_usage WHERE {where} GROUP BY model
               ORDER BY total_tokens DESC, calls DESC, model""",
            params,
        )]
        query = f"""SELECT id, model, used_at, input_tokens, output_tokens, total_tokens
                    FROM model_usage WHERE {where}"""
        if before is not None:
            query += " AND id < ?"
            params += (before,)
        rows = db.execute(query + " ORDER BY id DESC LIMIT ?", (*params, PAGE_SIZE + 1)).fetchall()
    return {
        "models": models,
        "records": [dict(row) for row in rows[:PAGE_SIZE]],
        "next_before": rows[PAGE_SIZE - 1]["id"] if len(rows) > PAGE_SIZE else None,
    }
