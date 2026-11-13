"""System information for the About page: versions, database usage and record counts."""

import ipaddress
import os
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
    AIJob, Component, Dashboard, Device, DeviceNote, EventComment, Node, Probe, RemotePlugin, Service, StateChange,
    SyslogMessage, TerminalSession, User,
)
from netsync.plugins.registry import registry

router = APIRouter(tags=["about"])

STARTED = time.time()
REPO = "https://github.com/sagattiger/NETsync"
PACKAGES = ["fastapi", "uvicorn", "sqlalchemy", "asyncpg", "pydantic", "pysnmp", "redis", "icmplib", "httpx", "argon2-cffi", "pyjwt"]


def os_release() -> str | None:
    """The container's distribution (the host kernel comes from platform)."""
    try:
        for line in open("/etc/os-release", encoding="utf-8"):
            if line.startswith("PRETTY_NAME="):
                return line.split("=", 1)[1].strip().strip('"')
    except OSError:
        pass
    return None


def in_container() -> str | None:
    if os.path.exists("/.dockerenv"):
        return "Docker container"
    try:
        if "lxc" in open("/proc/1/environ", "rb").read().decode(errors="ignore"):
            return "LXC container"
    except OSError:
        pass
    return None


async def address_stats(session) -> dict[str, int]:
    """IPv4/IPv6 addresses and networks found on ports (link-local IPv6 not counted)."""
    v4, v6, n4, n6 = set(), set(), set(), set()
    rows = await session.execute(select(Component.attrs).where(Component.kind == "port", Component.deleted.is_(False)))
    for (attrs,) in rows:
        for a in (attrs or {}).get("ipv4") or []:
            try:
                iface = ipaddress.ip_interface(a if "/" in a else f"{a}/32")
            except ValueError:
                continue
            v4.add(str(iface.ip))
            if "/" in a:
                n4.add(str(iface.network))
        for a in (attrs or {}).get("ipv6") or []:
            try:
                ip = ipaddress.ip_address(a.split("/")[0])
            except ValueError:
                continue
            if not ip.is_link_local:
                v6.add(str(ip))
                n6.add(str(ipaddress.ip_network(f"{ip}/64", strict=False)))
    return {"ipv4_addresses": len(v4), "ipv4_networks": len(n4), "ipv6_addresses": len(v6), "ipv6_networks": len(n6)}


async def ollama_version(session) -> str | None:
    from netsync.plugins import settings as plugin_settings
    from netsync.plugins.builtin.ai.service import plugin as ai_plugin

    try:
        enabled, cfg = await plugin_settings.get_settings(session, ai_plugin())
        if not enabled or not cfg.get("base_url"):
            return None
        import httpx

        async with httpx.AsyncClient(timeout=2) as c:
            r = await c.get(cfg["base_url"].rstrip("/") + "/api/version")
            return f"{r.json().get('version')} · model {cfg.get('model') or '-'}"
    except Exception:  # noqa: BLE001 - unreachable Ollama must not break the page
        return None


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
            "kernel": platform.release(),
            "arch": platform.machine(),
            "os": os_release(),
            "container": in_container(),
            "timezone": time.strftime("%z"),
            "db_timezone": await scalar(session, "SHOW timezone"),
            "ollama": await ollama_version(session),
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
            "processors": await count(Component, Component.kind == "processor", Component.deleted.is_(False)),
            "mempools": await count(Component, Component.kind == "mempool", Component.deleted.is_(False)),
            "storage": await count(Component, Component.kind == "storage", Component.deleted.is_(False)),
            "disks": await count(Component, Component.kind == "disk", Component.deleted.is_(False)),
            "sensors": await count(Component, Component.kind == "sensor", Component.deleted.is_(False)),
            "probes": await count(Probe),
            "terminal_sessions": await count(TerminalSession),
            "ai_answers": await count(AIJob, AIJob.status == "done"),
            "container_plugins": await count(RemotePlugin),
            "metrics_size": await scalar(session, "SELECT hypertable_size('metrics')"),
            **await address_stats(session),
        },
        "plugins": [{"name": p.name, "version": p.version, "builtin": p.builtin} for p in registry.plugins.values()],
        "nodes": nodes,
    }
