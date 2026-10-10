from __future__ import annotations

import argparse
import getpass

from sqlalchemy import or_, select

from app.core.database import SessionLocal
from app.core.security import hash_password
from app.models import User


def create_admin(username: str, email: str, password: str) -> User:
    if len(password) < 12:
        raise ValueError("管理员密码至少需要 12 个字符")
    with SessionLocal() as db:
        duplicate = db.scalar(
            select(User).where(or_(User.username == username, User.email == email))
        )
        if duplicate:
            raise ValueError("用户名或邮箱已存在")
        user = User(
            username=username,
            email=email,
            password_hash=hash_password(password),
            role="admin",
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        return user


def main() -> None:
    parser = argparse.ArgumentParser(description="EnterpriseMind management commands")
    subparsers = parser.add_subparsers(dest="command", required=True)
    admin_parser = subparsers.add_parser("create-admin", help="Create a production administrator")
    admin_parser.add_argument("--username", required=True)
    admin_parser.add_argument("--email", required=True)
    args = parser.parse_args()

    if args.command == "create-admin":
        password = getpass.getpass("管理员密码: ")
        confirmation = getpass.getpass("再次输入密码: ")
        if password != confirmation:
            raise SystemExit("两次输入的密码不一致")
        try:
            user = create_admin(args.username, args.email, password)
        except ValueError as exc:
            raise SystemExit(str(exc)) from exc
        print(f"管理员已创建: {user.username} ({user.email})")


if __name__ == "__main__":
    main()
