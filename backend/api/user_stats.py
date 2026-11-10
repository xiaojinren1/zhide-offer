import os
from datetime import datetime, timedelta, timezone
from threading import Lock
from time import time

from fastapi import APIRouter, Depends, Request

from core import accounts

router = APIRouter(prefix="/api/user-stats")
_presence: dict[str, float] = {}
_lock = Lock()
_CHINA = timezone(timedelta(hours=8))


def _prune(now: float) -> None:
    for session, seen in list(_presence.items()):
        if seen <= now - 300:
            del _presence[session]


@router.post("/heartbeat")
def heartbeat(request: Request, user: dict = Depends(accounts.require_user)):
    if user.get("guest"):
        return {"ok": True}
    with _lock:
        now = time()
        _prune(now)
        _presence[accounts.token_hash(request.cookies[accounts.COOKIE_NAME])] = now
    return {"ok": True}


@router.get("")
def overview(user: dict = Depends(accounts.require_user)):
    admins = {name.strip().lower() for name in os.getenv("JOBAGENT_ADMIN_USERNAMES", "").split(",")}
    if user["username"].lower() not in admins:
        return None
    now = time()
    today = datetime.fromtimestamp(now, _CHINA)
    monday = (today - timedelta(days=today.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
    with _lock:
        _prune(now)
        active = set(_presence)
    with accounts.connection() as db:
        rows = db.execute("SELECT user_id, token_hash FROM sessions JOIN users ON users.id = sessions.user_id WHERE expires_at > ? AND guest_until IS NULL", (now,))
        online = len({row["user_id"] for row in rows if row["token_hash"] in active})
        registered, new_this_week = db.execute(
            "SELECT COUNT(*), COUNT(CASE WHEN created_at BETWEEN ? AND ? THEN 1 END) FROM users WHERE guest_until IS NULL",
            (monday.timestamp(), now),
        ).fetchone()
    return {"online": online, "registered": registered, "new_this_week": new_this_week}
