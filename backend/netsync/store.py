"""Plugin store: a catalog of container plugins that admins install with one click.

The catalog (``catalog/plugins.json`` in the NETsync repository, or any URL in NETSYNC_STORE_CATALOG_URL) lists
plugins with their GitHub source. Installing registers the plugin (secret, granted permissions) and asks the
installer container to build and start it (installer/app.py). Only the installer can use Docker.
"""

from __future__ import annotations

import hashlib
import hmac
import re
import time
from typing import Any

import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sqlalchemy import select

from netsync.api.deps import CurrentUser, Session, require
from netsync.config import get_settings
from netsync.models import RemotePlugin, Role
from netsync.probing.secrets import encrypt
from netsync.tools import remote

router = APIRouter(tags=["plugin store"])

NAME = re.compile(r"^[a-z][a-z0-9_]{1,30}$")
VERSION = re.compile(r"^[0-9A-Za-z.+-]{1,40}$")
CACHE_SECONDS = 300
_catalog: tuple[float, dict] | None = None


def installer_token() -> str:
    return hmac.new(get_settings().secret_key.encode(), b"netsync-installer", hashlib.sha256).hexdigest()


async def installer(method: str, path: str, **kw) -> Any:
    try:
        async with httpx.AsyncClient(base_url=get_settings().installer_url, timeout=30,
                                     headers={"Authorization": f"Bearer {installer_token()}"}) as c:
            r = await c.request(method, path, **kw)
    except httpx.HTTPError as e:
        raise HTTPException(502, "The installer container is not running. Start it with: docker compose up -d installer") from e
    if r.status_code >= 400:
        try:
            detail = r.json().get("detail", r.text)
        except ValueError:
            detail = r.text
        raise HTTPException(r.status_code if r.status_code < 500 else 502, f"Installer: {str(detail)[:300]}")
    return r.json()


def parse_catalog(data: Any) -> dict:
    """Keep well-formed entries only."""
    if not isinstance(data, dict) or not isinstance(data.get("plugins"), list):
        raise ValueError("catalog must be an object with a plugins list")
    out = []
    for e in data["plugins"]:
        if not isinstance(e, dict) or not NAME.match(str(e.get("name", ""))) or not VERSION.match(str(e.get("version", ""))):
            continue
        src = e.get("source") or {}
        if not isinstance(src, dict) or not src.get("repo"):
            continue
        out.append({
            "name": e["name"], "title": str(e.get("title") or e["name"])[:80], "version": str(e["version"]),
            "author": str(e.get("author") or "")[:80], "icon": str(e.get("icon") or "puzzle")[:32],
            "description": str(e.get("description") or "")[:1000],
            "permissions": [p for p in e.get("permissions") or [] if p in remote.PERMISSIONS],
            "memory_mb": int(e.get("memory_mb") or 256),
            "source": {k: str(src.get(k, d)) for k, d in (("repo", ""), ("ref", "main"), ("context", ""),
                                                         ("dockerfile", "Dockerfile"))},
            "docs": e.get("docs"),
        })
    return {"plugins": out}


async def catalog(force: bool = False) -> dict:
    global _catalog
    if _catalog and not force and time.monotonic() - _catalog[0] < CACHE_SECONDS:
        return _catalog[1]
    try:
        async with httpx.AsyncClient(timeout=15, follow_redirects=True) as c:
            r = await c.get(get_settings().store_catalog_url)
            r.raise_for_status()
            data = parse_catalog(r.json())
    except (httpx.HTTPError, ValueError) as e:
        raise HTTPException(502, f"Cannot read the plugin catalog: {e}") from e
    _catalog = (time.monotonic(), data)
    return data


def newer(a: str, b: str) -> bool:
    """Is version a newer than b (numeric parts compared)?"""
    def key(v: str) -> list:
        return [int(x) if x.isdigit() else x for x in re.split(r"[.+-]", v)]
    try:
        return key(a) > key(b)
    except TypeError:
        return a != b


@router.get("/store")
async def list_store(user: CurrentUser, session: Session, refresh: bool = False):
    cat = await catalog(force=refresh)
    rows = {p.name: p for p in await session.scalars(select(RemotePlugin))}
    containers = {}
    if user.role == Role.ADMIN:
        try:
            containers = {c["name"]: c for c in await installer("GET", "/plugins")}
        except HTTPException:
            containers = {}
    out = []
    for e in cat["plugins"]:
        p = rows.get(e["name"])
        installed = (p.store or {}).get("version") if p and p.store else None
        out.append({**e, "installed": installed, "update": bool(installed and newer(e["version"], installed)),
                    "foreign": bool(p and not p.store),  # same name registered by hand
                    "status": p.status if p else None, "status_detail": p.status_detail if p else None,
                    "container": containers.get(e["name"]), "job": (p.store or {}).get("job") if p and p.store else None})
    return {"plugins": out, "installer": bool(containers) or user.role != Role.ADMIN or await _installer_up()}


async def _installer_up() -> bool:
    try:
        async with httpx.AsyncClient(base_url=get_settings().installer_url, timeout=3) as c:
            return (await c.get("/health")).status_code == 200
    except httpx.HTTPError:
        return False


class InstallIn(BaseModel):
    accept_permissions: list[str] = []


@router.post("/store/{name}/install")
async def install(name: str, body: InstallIn, session: Session, user=require(Role.ADMIN)):
    from netsync.plugins.registry import registry

    entry = next((e for e in (await catalog(force=True))["plugins"] if e["name"] == name), None)
    if entry is None:
        raise HTTPException(404, "Not in the catalog")
    if name in registry.plugins:
        raise HTTPException(400, f"{name} is a built-in plugin name")
    if set(entry["permissions"]) - set(body.accept_permissions):
        raise HTTPException(400, "Accept the permissions the plugin asks for")
    p = await session.scalar(select(RemotePlugin).where(RemotePlugin.name == name))
    if p is not None and not p.store:
        raise HTTPException(400, f"A plugin named {name} was registered by hand; remove it first")
    if p is None:
        secret = remote.new_secret()
        p = RemotePlugin(name=name, url=f"http://netsync-plugin-{name}:8080", secret_enc=encrypt({"secret": secret}),
                         secret_hash=remote.hash_secret(secret), created_by=user.username, status="pending",
                         manifest={}, granted=entry["permissions"])
        session.add(p)
    else:
        secret = remote.secret_of(p)
        p.granted = entry["permissions"]
    job = await installer("POST", "/install", json={
        "name": name, "version": entry["version"], "source": entry["source"], "memory_mb": entry["memory_mb"],
        "env": {"NETSYNC_PLUGIN_SECRET": secret, "NETSYNC_URL": "http://api:8000", "NETSYNC_PLUGIN_NAME": name}})
    p.store = {"version": entry["version"], "title": entry["title"], "job": job["id"], "installed_by": user.username}
    remote.invalidate()
    await session.commit()
    return job


@router.get("/store/jobs/{job_id}", dependencies=[require(Role.ADMIN)])
async def job_status(job_id: str, session: Session):
    job = await installer("GET", f"/jobs/{job_id}")
    if job.get("status") == "done":
        p = await session.scalar(select(RemotePlugin).where(RemotePlugin.name == job.get("name")))
        if p is not None and p.status != "online":
            await remote.refresh(p)
            await session.commit()
        job["plugin_status"] = p.status if p else None
        job["plugin_detail"] = p.status_detail if p else None
    return job


@router.post("/store/{name}/restart", dependencies=[require(Role.ADMIN)])
async def restart(name: str):
    return await installer("POST", f"/plugins/{name}/restart")


@router.get("/store/{name}/logs", dependencies=[require(Role.ADMIN)])
async def logs(name: str, tail: int = 200):
    return await installer("GET", f"/plugins/{name}/logs", params={"tail": tail})


@router.delete("/store/{name}", dependencies=[require(Role.ADMIN)])
async def uninstall(name: str, session: Session, keep_data: bool = True):
    p = await session.scalar(select(RemotePlugin).where(RemotePlugin.name == name))
    if p is not None and not p.store:
        raise HTTPException(400, "This plugin was not installed from the store")
    await installer("DELETE", f"/plugins/{name}", params={"keep_data": str(keep_data).lower()})
    if p is not None:
        await session.delete(p)
        await session.commit()
    remote.invalidate()
    return {"ok": True}
