import argparse
import asyncio
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
    """netsync-admin create-user <username> <password> [--role admin]"""
    parser = argparse.ArgumentParser(prog="netsync-admin")
    sub = parser.add_subparsers(dest="cmd", required=True)
    cu = sub.add_parser("create-user")
    cu.add_argument("username")
    cu.add_argument("password")
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
            from netsync.models import User
            from netsync.security import hash_password

            await init_db()
            async with SessionLocal() as s:
                s.add(User(username=args.username, role=args.role, password_hash=hash_password(args.password)))
                await s.commit()
            print(f"user {args.username} created")

    asyncio.run(main())
