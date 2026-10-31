"""普通账户、服务端会话及用户经历库的 SQLite 边界。"""
from __future__ import annotations

import hashlib
import hmac
import secrets
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator
from uuid import uuid4

from fastapi import HTTPException, Request

from core.config import PROJECT_ROOT

DATABASE_PATH = PROJECT_ROOT / "data" / "accounts.sqlite3"
COOKIE_NAME = "zhide_session"
SESSION_SECONDS = 7 * 24 * 60 * 60
PASSWORD_ITERATIONS = 600_000

_SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id TEXT PRIMARY KEY,
    username TEXT NOT NULL UNIQUE COLLATE NOCASE,
    password_hash TEXT NOT NULL,
    avatar_blob BLOB,
    avatar_content_type TEXT,
    recovery_code_hash TEXT,
    created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS sessions (
    token_hash TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    expires_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS sessions_user ON sessions(user_id);
CREATE TABLE IF NOT EXISTS profiles (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    saved_at TEXT NOT NULL,
    experience_count INTEGER NOT NULL,
    profile_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS profiles_user ON profiles(user_id);
CREATE TABLE IF NOT EXISTS workspaces (
    user_id TEXT PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    revision INTEGER NOT NULL,
    saved_at TEXT NOT NULL,
    state_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS evidence_banks (
    user_id TEXT PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    revision INTEGER NOT NULL,
    state_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS interview_records (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    title TEXT NOT NULL,
    saved_at TEXT NOT NULL,
    record_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS interview_records_user ON interview_records(user_id);
"""


@contextmanager
def connection() -> Iterator[sqlite3.Connection]:
    """每次请求独立连接，事务成功才提交；测试可替换数据库路径。"""
    path = Path(DATABASE_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path, timeout=10)
    db.row_factory = sqlite3.Row
    try:
        db.execute("PRAGMA foreign_keys = ON")
        db.executescript(_SCHEMA)
        user_columns = {row[1] for row in db.execute("PRAGMA table_info(users)")}
        if "avatar_blob" not in user_columns:
            db.execute("ALTER TABLE users ADD COLUMN avatar_blob BLOB")
        if "avatar_content_type" not in user_columns:
            db.execute("ALTER TABLE users ADD COLUMN avatar_content_type TEXT")
        if "recovery_code_hash" not in user_columns:
            db.execute("ALTER TABLE users ADD COLUMN recovery_code_hash TEXT")
        with db:
            yield db
    finally:
        db.close()


def password_hash(password: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), bytes.fromhex(salt), PASSWORD_ITERATIONS
    ).hex()
    return f"pbkdf2_sha256${PASSWORD_ITERATIONS}${salt}${digest}"


def verify_password(password: str, encoded: str) -> bool:
    algorithm, iterations, salt, expected = encoded.split("$")
    if algorithm != "pbkdf2_sha256":
        raise ValueError("unsupported password hash algorithm")
    actual = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), bytes.fromhex(salt), int(iterations)
    ).hex()
    return hmac.compare_digest(actual, expected)


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def new_session(db: sqlite3.Connection, user_id: str) -> str:
    token = secrets.token_urlsafe(32)
    now = time.time()
    db.execute("DELETE FROM sessions WHERE expires_at <= ?", (now,))
    db.execute(
        "INSERT INTO sessions(token_hash,user_id,expires_at) VALUES(?,?,?)",
        (token_hash(token), user_id, now + SESSION_SECONDS),
    )
    return token


def register(username: str, password: str) -> tuple[dict, str, str]:
    username = username.lower()
    encoded = password_hash(password)
    recovery = secrets.token_urlsafe(12)
    user = {"id": uuid4().hex, "username": username}
    with connection() as db:
        try:
            db.execute(
                "INSERT INTO users(id,username,password_hash,recovery_code_hash,created_at) VALUES(?,?,?,?,?)",
                (user["id"], username, encoded, password_hash(recovery), time.time()),
            )
        except sqlite3.IntegrityError as exc:
            if db.execute("SELECT 1 FROM users WHERE username = ?", (username,)).fetchone():
                raise HTTPException(status_code=409, detail="用户名已存在，请更换或直接登录") from exc
            raise
        token = new_session(db, user["id"])
    return user, token, recovery


def reset_password(username: str, recovery: str, new_password: str) -> tuple[dict, str]:
    with connection() as db:
        row = db.execute(
            "SELECT id,username,recovery_code_hash FROM users WHERE username = ?",
            (username.lower(),),
        ).fetchone()
        valid = bool(row and row["recovery_code_hash"] and verify_password(recovery, row["recovery_code_hash"]))
        if not valid:
            raise HTTPException(status_code=401, detail="用户名或恢复码不正确")
        db.execute(
            "UPDATE users SET password_hash = ?, recovery_code_hash = NULL WHERE id = ?",
            (password_hash(new_password), row["id"]),
        )
        db.execute("DELETE FROM sessions WHERE user_id = ?", (row["id"],))
        token = new_session(db, row["id"])
        user = {"id": row["id"], "username": row["username"]}
    return user, token


def login(username: str, password: str) -> tuple[dict, str]:
    with connection() as db:
        row = db.execute(
            "SELECT id,username,password_hash FROM users WHERE username = ?", (username.lower(),)
        ).fetchone()
        # 不存在的用户名也执行等量哈希运算，避免明显的存在性时序差异。
        encoded = row["password_hash"] if row else (
            f"pbkdf2_sha256${PASSWORD_ITERATIONS}${'00' * 16}${'00' * 32}"
        )
        valid = verify_password(password, encoded)
        if row is None or not valid:
            raise HTTPException(status_code=401, detail="用户名或密码不正确")
        user = {"id": row["id"], "username": row["username"]}
        token = new_session(db, user["id"])
    return user, token


def require_user(request: Request) -> dict:
    token = request.cookies.get(COOKIE_NAME)
    if not token:
        raise HTTPException(status_code=401, detail="请先登录")
    with connection() as db:
        row = db.execute(
            "SELECT users.id,users.username FROM sessions JOIN users ON users.id = sessions.user_id "
            "WHERE sessions.token_hash = ? AND sessions.expires_at > ?",
            (token_hash(token), time.time()),
        ).fetchone()
    if row is None:
        raise HTTPException(status_code=401, detail="登录已失效，请重新登录")
    return {"id": row["id"], "username": row["username"]}


def profile(user_id: str) -> dict:
    with connection() as db:
        row = db.execute(
            "SELECT id,username,avatar_blob FROM users WHERE id = ?", (user_id,)
        ).fetchone()
    if row is None:
        raise HTTPException(status_code=401, detail="登录已失效，请重新登录")
    return {
        "id": row["id"],
        "username": row["username"],
        "avatar_url": "/api/auth/avatar" if row["avatar_blob"] is not None else None,
    }


def change_password(user_id: str, current_password: str, new_password: str) -> str:
    with connection() as db:
        row = db.execute(
            "SELECT password_hash FROM users WHERE id = ?", (user_id,)
        ).fetchone()
        if row is None or not verify_password(current_password, row["password_hash"]):
            raise HTTPException(status_code=401, detail="当前密码不正确")
        db.execute(
            "UPDATE users SET password_hash = ? WHERE id = ?",
            (password_hash(new_password), user_id),
        )
        db.execute("DELETE FROM sessions WHERE user_id = ?", (user_id,))
        return new_session(db, user_id)


def set_avatar(user_id: str, image: bytes, content_type: str) -> None:
    with connection() as db:
        cursor = db.execute(
            "UPDATE users SET avatar_blob = ?, avatar_content_type = ? WHERE id = ?",
            (sqlite3.Binary(image), content_type, user_id),
        )
        if cursor.rowcount != 1:
            raise HTTPException(status_code=401, detail="登录已失效，请重新登录")


def get_avatar(user_id: str) -> tuple[bytes, str]:
    with connection() as db:
        row = db.execute(
            "SELECT avatar_blob,avatar_content_type FROM users WHERE id = ?", (user_id,)
        ).fetchone()
    if row is None:
        raise HTTPException(status_code=401, detail="登录已失效，请重新登录")
    if row["avatar_blob"] is None:
        raise HTTPException(status_code=404, detail="尚未设置头像")
    return bytes(row["avatar_blob"]), row["avatar_content_type"]


def delete_avatar(user_id: str) -> None:
    with connection() as db:
        db.execute(
            "UPDATE users SET avatar_blob = NULL, avatar_content_type = NULL WHERE id = ?",
            (user_id,),
        )


def require_csrf(request: Request) -> None:
    """自定义请求头配合明确的 CORS 来源，阻止跨站表单携带会话修改状态。"""
    if request.method not in {"GET", "HEAD", "OPTIONS"}:
        if request.headers.get("X-Requested-With") != "XMLHttpRequest":
            raise HTTPException(status_code=403, detail="请求缺少安全校验头，请刷新页面后重试")


def logout(token: str | None) -> None:
    if token:
        with connection() as db:
            db.execute("DELETE FROM sessions WHERE token_hash = ?", (token_hash(token),))
