"""运维命令行：服务器上开通/回收管理员、查看现有管理员。

为什么需要它：部署时如果忘了设 `JOBAGENT_ADMIN_USERNAMES`，站上就一个管理员都没有，
而「管理后台」只有管理员能打开——没有入口可进，只能改数据库。这个脚本是那条备用入口，
只在本机/服务器终端执行，不开 HTTP 接口，也不做成网页按钮（后台提权不该暴露在公网）。

用法（在项目根目录）：

    .venv/bin/python backend/manage.py admin list
    .venv/bin/python backend/manage.py admin grant zhangsan
    .venv/bin/python backend/manage.py admin revoke zhangsan
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from core import accounts  # noqa: E402


def _find_user(db, username: str):
    row = db.execute(
        "SELECT id, username, guest_until FROM users WHERE LOWER(username) = ?",
        (username.strip().lower(),),
    ).fetchone()
    return row


def _admin_count(db) -> int:
    return db.execute("SELECT COUNT(*) FROM user_roles WHERE role = 'admin'").fetchone()[0]


def list_admins() -> int:
    with accounts.connection() as db:
        rows = db.execute(
            "SELECT u.username, u.created_at FROM user_roles r JOIN users u ON u.id = r.user_id"
            " WHERE r.role = 'admin' ORDER BY u.username"
        ).fetchall()
    if not rows:
        print("当前没有任何管理员账号。用 `admin grant <用户名>` 开通（需先注册该账号）。")
        return 0
    print(f"共 {len(rows)} 个管理员：")
    for row in rows:
        print(f"  - {row['username']}")
    return 0


def grant_admin(username: str) -> int:
    with accounts.connection() as db:
        user = _find_user(db, username)
        if user is None:
            print(f"找不到账号 {username.strip()}：请先在网站上注册该账号，再执行本条命令。", file=sys.stderr)
            return 1
        if user["guest_until"]:
            print("试用账号不能设为管理员，请用正式账号。", file=sys.stderr)
            return 1
        changed = db.execute(
            "INSERT OR IGNORE INTO user_roles(user_id, role) VALUES (?, 'admin')", (user["id"],)
        ).rowcount
    if changed:
        print(f"已把 {user['username']} 设为管理员，重新登录后左侧会出现「管理后台」。")
    else:
        print(f"{user['username']} 已经是管理员，无需重复操作。")
    return 0


def revoke_admin(username: str) -> int:
    with accounts.connection() as db:
        user = _find_user(db, username)
        if user is None:
            print(f"找不到账号 {username.strip()}。", file=sys.stderr)
            return 1
        is_admin = db.execute(
            "SELECT 1 FROM user_roles WHERE user_id = ? AND role = 'admin'", (user["id"],)
        ).fetchone()
        if not is_admin:
            print(f"{user['username']} 不是管理员，无需操作。")
            return 0
        if _admin_count(db) <= 1:
            print("这是最后一个管理员，撤销后就没有人能进管理后台了。先 grant 另一个账号再撤销。",
                  file=sys.stderr)
            return 1
        db.execute("DELETE FROM user_roles WHERE user_id = ? AND role = 'admin'", (user["id"],))
    print(f"已撤销 {user['username']} 的管理员角色。")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="职得offer 运维命令")
    sub = parser.add_subparsers(dest="group", required=True)
    admin = sub.add_parser("admin", help="管理员角色")
    actions = admin.add_subparsers(dest="action", required=True)
    actions.add_parser("list", help="列出所有管理员")
    grant = actions.add_parser("grant", help="把已注册账号设为管理员")
    grant.add_argument("username")
    revoke = actions.add_parser("revoke", help="撤销管理员角色（保留最后一个）")
    revoke.add_argument("username")
    args = parser.parse_args(argv)

    print(f"数据库：{accounts.DATABASE_PATH}")
    if args.action == "list":
        return list_admins()
    if args.action == "grant":
        return grant_admin(args.username)
    return revoke_admin(args.username)


if __name__ == "__main__":
    raise SystemExit(main())
