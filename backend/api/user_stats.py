import os
from datetime import datetime, timedelta, timezone
from threading import Lock
from time import time

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from pydantic import BaseModel, Field

from core import accounts, event_log, events

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


def _has_role(db, user_id: str) -> bool:
    return db.execute("SELECT 1 FROM user_roles WHERE user_id = ? AND role = 'admin'", (user_id,)).fetchone() is not None


def is_admin(user: dict) -> bool:
    if user.get("guest"):
        return False
    with accounts.connection() as db:
        if not db.execute("SELECT 1 FROM role_migrations WHERE name = 'legacy_admins'").fetchone():
            names = [name.strip().lower() for name in os.getenv("JOBAGENT_ADMIN_USERNAMES", "").split(",") if name.strip()]
            if names:
                db.execute("BEGIN IMMEDIATE")
                if not db.execute("SELECT 1 FROM role_migrations WHERE name = 'legacy_admins'").fetchone():
                    placeholders = ",".join("?" for _ in names)
                    cursor = db.execute(
                        f"""INSERT OR IGNORE INTO user_roles(user_id, role)
                            SELECT id, 'admin' FROM users WHERE guest_until IS NULL AND LOWER(username) IN ({placeholders})""",
                        names,
                    )
                    if cursor.rowcount:
                        db.execute("INSERT INTO role_migrations VALUES ('legacy_admins')")
        return _has_role(db, user["id"])


class RoleChange(BaseModel):
    username: str = Field(min_length=3, max_length=32, pattern=r"^[A-Za-z0-9_]+$")
    admin: bool


class ContactChange(BaseModel):
    qq: str = Field(max_length=12, pattern=r"^([1-9][0-9]{4,11})?$")


@router.put("/contact")
def change_contact(body: ContactChange, user: dict = Depends(accounts.require_user)):
    if not is_admin(user):
        raise HTTPException(403, "没有修改联系方式的权限")
    with accounts.connection() as db:
        db.execute("BEGIN IMMEDIATE")
        if not _has_role(db, user["id"]):
            raise HTTPException(403, "没有修改联系方式的权限")
        if body.qq:
            db.execute("INSERT OR REPLACE INTO site_settings VALUES ('contact_qq', ?)", (body.qq,))
        else:
            db.execute("DELETE FROM site_settings WHERE name = 'contact_qq'")
    return {"ok": True}


@router.get("/admins")
def list_admins(response: Response, user: dict = Depends(accounts.require_user)):
    if not is_admin(user):
        raise HTTPException(403, "没有管理角色的权限")
    response.headers["Cache-Control"] = "no-store"
    with accounts.connection() as db:
        rows = db.execute("""SELECT username FROM users JOIN user_roles ON users.id = user_roles.user_id
                             WHERE role = 'admin' ORDER BY username""").fetchall()
    return {"admins": [row["username"] for row in rows]}


@router.put("/admins")
def change_role(body: RoleChange, user: dict = Depends(accounts.require_user)):
    if not is_admin(user):
        raise HTTPException(403, "没有管理角色的权限")
    with accounts.connection() as db:
        db.execute("BEGIN IMMEDIATE")
        if not _has_role(db, user["id"]):
            raise HTTPException(403, "没有管理角色的权限")
        target = db.execute("SELECT id FROM users WHERE username = ? AND guest_until IS NULL",
                            (body.username,)).fetchone()
        if target is None:
            raise HTTPException(404, "找不到该正式账号")
        if body.admin:
            db.execute("INSERT OR IGNORE INTO user_roles VALUES (?, 'admin')", (target["id"],))
        elif target["id"] == user["id"]:
            raise HTTPException(409, "不能撤销自己的管理员角色")
        else:
            db.execute("DELETE FROM user_roles WHERE user_id = ? AND role = 'admin'", (target["id"],))
    return {"ok": True}


@router.get("")
def overview(response: Response, user: dict = Depends(accounts.require_user)):
    response.headers["Cache-Control"] = "no-store"
    if not is_admin(user):
        return None
    now = time()
    today = datetime.fromtimestamp(now, _CHINA)
    monday = (today - timedelta(days=today.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
    start = (today - timedelta(days=13)).replace(hour=0, minute=0, second=0, microsecond=0)
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
        registrations = dict(db.execute(
            """SELECT date(created_at, 'unixepoch', '+8 hours'), COUNT(*)
               FROM users WHERE guest_until IS NULL AND created_at >= ? GROUP BY 1""", (start.timestamp(),)
        ).fetchall())
        tokens = dict(db.execute(
            """SELECT date(used_at, '+8 hours'), SUM(total_tokens)
               FROM model_usage WHERE used_at >= ? AND total_tokens IS NOT NULL GROUP BY 1""",
            (start.astimezone(timezone.utc).isoformat(),),
        ).fetchall())
    dates = [(start + timedelta(days=offset)).date().isoformat() for offset in range(14)]
    return {"online": online, "registered": registered, "new_this_week": new_this_week,
            "trend": [{"date": day, "registrations": registrations.get(day, 0), "tokens": tokens.get(day, 0)}
                      for day in dates]}


@router.get("/bootstrap")
def bootstrap(response: Response, user: dict = Depends(accounts.require_user)):
    """站点还没有管理员时，允许首个正式账号自助领取管理员角色。

    为什么要有这个入口：公开部署时如果忘了配 `JOBAGENT_ADMIN_USERNAMES`、也没人上服务器跑
    CLI，站点就永远没有管理员，而「管理后台」只有管理员能进——死锁。
    安全边界：
    - 只能领取一次：库里一旦有管理员，`claimable` 永远是 false；
    - 只接受正式账号（试用账号不行）；
    - 领取动作写事件流，便于事后核对是谁第一个接手的。
    """
    response.headers["Cache-Control"] = "no-store"
    if user.get("guest"):
        return {"claimable": False, "reason": "试用账号不能领取管理员角色"}
    with accounts.connection() as db:
        exists = db.execute("SELECT 1 FROM user_roles WHERE role = 'admin' LIMIT 1").fetchone()
    return {"claimable": exists is None, "reason": "" if exists is None else "站点已有管理员"}


@router.post("/bootstrap")
def claim_bootstrap(response: Response, user: dict = Depends(accounts.require_user)):
    """领取首个管理员角色；已存在管理员时返回 409，不做任何变更。"""
    response.headers["Cache-Control"] = "no-store"
    if user.get("guest"):
        raise HTTPException(403, "试用账号不能领取管理员角色")
    with accounts.connection() as db:
        # 事务内再查一次，避免两个人同时点「领取」都成功
        if db.execute("SELECT 1 FROM user_roles WHERE role = 'admin' LIMIT 1").fetchone():
            raise HTTPException(409, "站点已有管理员，这个入口已关闭；需要新增管理员请在「管理后台 → 管理员角色」操作")
        db.execute("INSERT OR IGNORE INTO user_roles(user_id, role) VALUES(?, 'admin')", (user["id"],))
    events.emit("admin_bootstrap_claimed", user_id=user["id"])
    return {"ok": True, "username": user["username"]}


@router.get("/errors")
def error_trend(response: Response, days: int = Query(7, ge=1, le=30),
                limit: int = Query(30, ge=1, le=200),
                user: dict = Depends(accounts.require_user)):
    """错误趋势：近 24 小时与近 N 天的分类/功能聚合 + 脱敏明细。

    只给管理员。明细里没有原始错误文本、上游响应、材料内容或密钥——
    事件文件里可能有这些，但对外只保留时间、功能、分类和排查编号。
    """
    response.headers["Cache-Control"] = "no-store"
    if not is_admin(user):
        raise HTTPException(status_code=403, detail="只有管理员可以查看错误统计")
    summary = event_log.summarize(days=days, sample_limit=limit)
    summary["recent"] = event_log.recent_errors(limit=limit)
    return summary
