import argparse
import asyncio
import getpass
import logging
import os

from netsync.config import get_settings


def _logging() -> None:
    logging.basicConfig(
        level=os.environ.get("NETSYNC_LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
    )


def run_api() -> None:
    import uvicorn

    _logging()
    uvicorn.run("netsync.api.app:app", host="0.0.0.0", port=int(os.environ.get("PORT", 8000)), proxy_headers=True)


def run_worker() -> None:
    from netsync.poller.worker import Worker

    _logging()
    asyncio.run(Worker().main())


def admin() -> None:
    """netsync-admin create-user <username> [--role admin]   (prompts for the password)"""
    parser = argparse.ArgumentParser(prog="netsync-admin")
    sub = parser.add_subparsers(dest="cmd", required=True)
    cu = sub.add_parser("create-user", help="create a user, or reset the password of an existing one")
    cu.add_argument("username")
    cu.add_argument("password", nargs="?", help="omit to be prompted (keeps it out of shell history)")
    cu.add_argument("--role", default="admin", choices=["admin", "operator", "viewer"])
    sub.add_parser("init-db")
    sub.add_parser("settings")
    args = parser.parse_args()

    async def main():
        from netsync.db import SessionLocal, init_db

        if args.cmd == "init-db":
            await init_db()
        elif args.cmd == "settings":
            for k, v in get_settings().model_dump().items():
                print(f"{k} = {'***' if 'password' in k or 'secret' in k else v}")
        elif args.cmd == "create-user":
            from sqlalchemy import select

            from netsync.models import User
            from netsync.security import hash_password

            password = args.password
            if not password:
                password = getpass.getpass("Password: ")
                if password != getpass.getpass("Repeat password: "):
                    raise SystemExit("passwords do not match")
            if len(password) < 8:
                raise SystemExit("password must be at least 8 characters")

            await init_db()
            async with SessionLocal() as s:
                user = await s.scalar(select(User).where(User.username == args.username))
                if user:
                    user.password_hash, user.role, user.is_active = hash_password(password), args.role, True
                    action = "updated"
                else:
                    s.add(User(username=args.username, role=args.role, password_hash=hash_password(password)))
                    action = "created"
                await s.commit()
            print(f"user {args.username} {action} (role {args.role})")

    asyncio.run(main())
