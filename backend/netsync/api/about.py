"""System information for the About page: versions, database usage and record counts."""

import platform
import sys
import time
from datetime import UTC, datetime, timedelta
from importlib.metadata import PackageNotFoundError, version

from fastapi import APIRouter
from sqlalchemy import func, select, text

from netsync import __version__
from netsync.alerting import redis
from netsync.api.deps import CurrentUser, Session
from netsync.config import get_settings
from netsync.db import HYPERTABLES
from netsync.models import (
    Component, Dashboard, Device, DeviceNote, EventComment, Node, Service, StateChange, SyslogMessage, User,
)
from netsync.plugins.registry import registry

router = APIRouter(tags=["about"])

STARTED = time.time()
REPO = "https://github.com/sagattiger/NETsync"
PACKAGES = ["fastapi", "uvicorn", "sqlalchemy", "asyncpg", "pydantic", "pysnmp", "redis", "icmplib", "httpx", "argon2-cffi", "pyjwt"]


def pkg_version(name: str) -> str | None:
    try:
        return version(name)
    except PackageNotFoundError:
        return None


async def scalar(session, sql: str, **params):
    try:
        return (await session.execute(text(sql), params)).scalar()
    except Exception:
        await session.rollback()
        return None


@router.get("/about")
async def about(user: CurrentUser, session: Session):
    day_ago = datetime.now(UTC) - timedelta(days=1)

    async def count(model, *where):
        return await session.scalar(select(func.count()).select_from(model).where(*where))

    tables = []
    for table, retention in HYPERTABLES.items():
        tables.append({
            "name": table,
            "retention": retention,
            "size": await scalar(session, f"SELECT hypertable_size('{table}')"),
            "rows": await scalar(session, f"SELECT approximate_row_count('{table}')"),
            "chunks": await scalar(session, f"SELECT count(*) FROM timescaledb_information.chunks WHERE hypertable_name = '{table}'"),
        })

    redis_info = {}
    try:
        info = await redis().info()
        redis_info = {"version": info.get("redis_version"), "memory": info.get("used_memory_human"),
                      "uptime_seconds": info.get("uptime_in_seconds")}
    except Exception:
        pass

    nodes = [
        {"name": n.name, "is_local": n.is_local, "version": n.version, "last_seen": n.last_seen}
        for n in await session.scalars(select(Node).order_by(Node.name))
    ]

    return {
        "product": "NETsync",
        "version": __version__,
        "links": {
            "github": REPO,
            "docs": f"{REPO}#readme",
            "plugins": f"{REPO}/blob/main/docs/PLUGINS.md",
            "deploy": f"{REPO}/blob/main/docs/DEPLOY-LXC.md",
            "issues": f"{REPO}/issues",
            "api": "/api/docs",
        },
        "runtime": {
            "python": sys.version.split()[0],
            "platform": platform.platform(terse=True),
            "api_uptime_seconds": int(time.time() - STARTED),
            "node_name": get_settings().node_name,
            "poll_interval": get_settings().poll_interval,
            "discovery_interval": get_settings().discovery_interval,
        },
        "packages": {name: pkg_version(name) for name in PACKAGES},
        "database": {
            "postgres": await scalar(session, "SHOW server_version"),
            "timescaledb": await scalar(session, "SELECT extversion FROM pg_extension WHERE extname = 'timescaledb'"),
            "size": await scalar(session, "SELECT pg_database_size(current_database())"),
            "tables": tables,
        },
        "redis": redis_info,
        "counts": {
            "devices": await count(Device),
            "devices_down": await count(Device, Device.status == 2),
            "components": await count(Component, Component.deleted.is_(False)),
            "ports": await count(Component, Component.kind == "port", Component.deleted.is_(False)),
            "services": await count(Service),
            "services_problems": await count(Service, Service.state > 0),
            "events": await count(StateChange),
            "events_24h": await count(StateChange, StateChange.time >= day_ago),
            "syslog": await count(SyslogMessage),
            "syslog_24h": await count(SyslogMessage, SyslogMessage.time >= day_ago),
            "comments": await count(EventComment),
            "pinned": await count(EventComment, EventComment.pinned.is_(True)),
            "notes": await count(DeviceNote),
            "dashboards": await count(Dashboard),
            "users": await count(User),
        },
        "plugins": [{"name": p.name, "version": p.version, "builtin": p.builtin} for p in registry.plugins.values()],
        "nodes": nodes,
    }
