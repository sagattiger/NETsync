"""Plugins in their own containers (docs/PLUGIN-PROTOCOL.md).

NETsync talks to a container plugin over HTTP with a shared secret, created when an admin registers it:

* NETsync → plugin: ``GET /manifest``, ``POST /tools/<tool>``, ``GET /health`` (Bearer <secret>)
* plugin → NETsync: ``/api/plugin-api/*`` (Bearer <secret>), limited to the permissions the admin granted

The plugin's tools appear in the hub as ``<plugin>__<tool>`` once the plugin is online and an admin has granted
its ``tools`` permission. A background service refreshes every manifest each minute.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import re
import secrets as pysecrets
import time
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlsplit

import httpx
from sqlalchemy import select

from netsync.db import SessionLocal
from netsync.models import RemotePlugin
from netsync.plugins.base import BackgroundService
from netsync.probing.secrets import decrypt
from netsync.tools.base import Tool, ToolContext, ToolError

log = logging.getLogger(__name__)

SECRET_PREFIX = "nsp_plg_"
PLUGIN_NAME = re.compile(r"^[a-z][a-z0-9_]{1,30}$")
TOOL_NAME = re.compile(r"^[a-z][a-z0-9_]{0,62}$")
# permissions a container plugin may ask for
PERMISSIONS = {
    "tools": "Offer its tools to the AI and MCP clients",
    "events": "Receive NETsync events (alerts, recoveries, syslog) as they happen",
    "call:read": "Call NETsync's read-only tools (devices, alerts, metrics, syslog)",
    "terminal": "Open SSH terminals for NETsync users (NETsync signs each session with the user's rights)",
}
TIMEOUT = httpx.Timeout(10.0, read=120.0)
_cache: tuple[float, list[Tool]] | None = None
CACHE_SECONDS = 15


def new_secret() -> str:
    return SECRET_PREFIX + pysecrets.token_urlsafe(32)


def hash_secret(secret: str) -> str:
    return hashlib.sha256(secret.encode()).hexdigest()


def secret_of(p: RemotePlugin) -> str:
    return decrypt(p.secret_enc).get("secret", "")


def valid_url(url: str) -> str:
    u = urlsplit(url.strip())
    if u.scheme not in ("http", "https") or not u.hostname or u.username or u.password:
        raise ValueError("URL must be http(s)://host[:port] (no credentials)")
    return url.strip().rstrip("/")


def parse_manifest(name: str, data: Any) -> dict[str, Any]:
    """Keep only what NETsync understands; raise ValueError on anything malformed."""
    if not isinstance(data, dict):
        raise ValueError("manifest must be a JSON object")
    if data.get("name") != name:
        raise ValueError(f"manifest name {data.get('name')!r} does not match the registered name {name!r}")
    tools = []
    for t in data.get("tools") or []:
        if not isinstance(t, dict) or not TOOL_NAME.match(str(t.get("name", ""))):
            raise ValueError(f"invalid tool name in manifest: {t.get('name') if isinstance(t, dict) else t!r}")
        schema = t.get("input_schema") or t.get("inputSchema") or {"type": "object", "properties": {}}
        if not isinstance(schema, dict) or schema.get("type") != "object":
            raise ValueError(f"tool {t['name']}: input_schema must be an object schema")
        tools.append({"name": t["name"], "description": str(t.get("description", ""))[:2000],
                      "title": t.get("title"), "input_schema": schema,
                      "risk": "write" if t.get("risk") == "write" else "read"})
    perms = [p for p in data.get("permissions") or [] if p in PERMISSIONS]
    return {"name": name, "version": str(data.get("version", ""))[:32], "description": str(data.get("description", ""))[:500],
            "tools": tools, "permissions": perms}


def tools_of(p: RemotePlugin) -> list[Tool]:
    if not p.enabled or p.status != "online" or "tools" not in (p.granted or []):
        return []
    out = []
    for t in (p.manifest or {}).get("tools", []):
        try:
            out.append(Tool(name=f"{p.name}__{t['name']}", description=t["description"], input_schema=t["input_schema"],
                            risk=t["risk"], title=t.get("title"), plugin=p.name))
        except ValueError:
            continue
    return out


async def tools() -> list[Tool]:
    global _cache
    if _cache and time.monotonic() - _cache[0] < CACHE_SECONDS:
        return _cache[1]
    async with SessionLocal() as s:
        rows = list(await s.scalars(select(RemotePlugin)))
    found = [t for p in rows for t in tools_of(p)]
    _cache = (time.monotonic(), found)
    return found


def invalidate() -> None:
    global _cache
    _cache = None


async def call(tool: Tool, ctx: ToolContext, args: dict[str, Any]) -> Any:
    async with SessionLocal() as s:
        p = await s.scalar(select(RemotePlugin).where(RemotePlugin.name == tool.plugin))
    if p is None or not tools_of(p):
        raise ToolError(f"plugin {tool.plugin} is not available")
    short = tool.name.split("__", 1)[1]
    async with httpx.AsyncClient(timeout=TIMEOUT) as c:
        r = await c.post(f"{p.url}/tools/{short}", headers={"Authorization": f"Bearer {secret_of(p)}"},
                         json={"arguments": args, "call_id": ctx.call_id, "actor": ctx.actor.label, "origin": ctx.origin})
    try:
        body = r.json()
    except ValueError:
        body = {}
    if r.status_code >= 400 or "error" in body:
        raise ToolError(str(body.get("error") or f"plugin answered HTTP {r.status_code}")[:2000])
    return body.get("result", body)


async def refresh(p: RemotePlugin) -> None:
    """Fetch the manifest and update status (call inside a session; caller commits)."""
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(5.0)) as c:
            r = await c.get(f"{p.url}/manifest", headers={"Authorization": f"Bearer {secret_of(p)}"})
        if r.status_code in (401, 403):
            raise ValueError("the plugin rejected the secret: copy the secret shown at registration into it")
        r.raise_for_status()
        p.manifest = parse_manifest(p.name, r.json())
        # permissions the plugin no longer asks for are dropped
        p.granted = [g for g in (p.granted or []) if g in p.manifest["permissions"]]
        p.status, p.status_detail, p.last_seen = "online", None, datetime.now(UTC)
    except (httpx.HTTPError, ValueError) as e:
        p.status = "error" if isinstance(e, ValueError) else "offline"
        p.status_detail = str(e)[:500] or type(e).__name__
    invalidate()


class RemotePluginService(BackgroundService):
    name = "remote_plugins"

    async def run(self, stop: asyncio.Event) -> None:
        while not stop.is_set():
            try:
                async with SessionLocal() as s:
                    for p in await s.scalars(select(RemotePlugin).where(RemotePlugin.enabled.is_(True))):
                        await refresh(p)
                    await s.commit()
            except Exception:  # noqa: BLE001
                log.exception("remote plugin refresh failed")
            try:
                await asyncio.wait_for(stop.wait(), timeout=60)
            except TimeoutError:
                pass
