"""SSH terminal: who may open a terminal on which device, with which rights, and the session audit.

Rights come from device groups: each group has a terminal access level (none, read, write, full) that its
members get on its devices. Admins have full access everywhere; viewers never more than read. The terminal itself
runs in a container plugin with the ``terminal`` permission (plugins/ssh); NETsync signs a one-minute ticket with
that plugin's secret, the browser hands it to the plugin's socket.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import re
import time
import uuid
from datetime import UTC, datetime
from typing import Annotated, Any

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select

from netsync.alerting import publish
from netsync.api.deps import CurrentUser, Session, get_device_for, require
from netsync.models import Device, RemotePlugin, Role, TerminalSession, User
from netsync.tools import remote

router = APIRouter(tags=["terminal"])

LEVELS = ["none", "read", "write", "full"]
LEVEL_LABELS = {"none": "No terminal", "read": "Read-only", "write": "Read and write", "full": "Full (admin)"}
TICKET_SECONDS = 60


def account_name(username: str) -> str:
    """NETsync user → Linux account: ns-<user> (lowercase, letters/digits/-/_ , at most 31 characters)."""
    s = re.sub(r"[^a-z0-9_-]+", "-", username.lower()).strip("-_") or "user"
    return ("ns-" + s)[:31].rstrip("-_")


def level_for(user: User, device: Device) -> str:
    if user.role == Role.ADMIN:
        return "full"
    mine = {g.id for g in user.groups}
    best = max((LEVELS.index(g.terminal_access) for g in device.groups
                if g.id in mine and g.terminal_access in LEVELS), default=0)
    if user.role == Role.VIEWER:
        best = min(best, LEVELS.index("read"))
    return LEVELS[best]


def b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def sign(payload: dict, secret: str) -> str:
    body = b64(json.dumps(payload, separators=(",", ":")).encode())
    return f"{body}.{b64(hmac.new(secret.encode(), body.encode(), hashlib.sha256).digest())}"


async def terminal_plugin(session) -> RemotePlugin | None:
    rows = await session.scalars(select(RemotePlugin).where(RemotePlugin.enabled.is_(True)).order_by(RemotePlugin.id))
    return next((p for p in rows if "terminal" in (p.granted or [])), None)


async def plugin_request(p: RemotePlugin, method: str, path: str, **kw) -> Any:
    try:
        async with httpx.AsyncClient(timeout=90) as c:
            r = await c.request(method, f"{p.url}{path}", headers={"Authorization": f"Bearer {remote.secret_of(p)}"}, **kw)
            r.raise_for_status()
            return r.json()
    except httpx.HTTPError as e:
        raise HTTPException(502, f"The terminal plugin did not answer: {e}") from e


def session_out(t: TerminalSession) -> dict:
    return {k: getattr(t, k) for k in ("id", "created_at", "username", "account", "device_id", "hostname", "level", "via",
                                       "status", "reason", "client_ip", "connected_at", "ended_at", "bytes_in", "bytes_out")}


# --------------------------------------------------------------------------- users

@router.get("/terminal/status")
async def status(user: CurrentUser, session: Session):
    p = await terminal_plugin(session)
    return {"available": bool(p and p.status == "online"), "plugin": p.name if p else None,
            "plugin_status": p.status if p else None, "account": account_name(user.username),
            "levels": [{"key": k, "label": LEVEL_LABELS[k]} for k in LEVELS]}


@router.get("/terminal/access/{device_id}")
async def access(device_id: int, user: CurrentUser, session: Session):
    device = await get_device_for(session, user, device_id)
    p = await terminal_plugin(session)
    return {"level": level_for(user, device), "account": account_name(user.username),
            "available": bool(p and p.status == "online")}


class OpenIn(BaseModel):
    device_id: int


@router.post("/terminal/sessions")
async def open_session(body: OpenIn, request: Request, user: CurrentUser, session: Session):
    device = await get_device_for(session, user, body.device_id)
    level = level_for(user, device)
    if level == "none":
        raise HTTPException(403, "Your groups don't give you terminal access to this device")
    p = await terminal_plugin(session)
    if p is None or p.status != "online":
        raise HTTPException(503, "The SSH terminal plugin is not installed or not running (Setup → Plugin store)")
    host = device.ip or device.hostname
    sid = uuid.uuid4().hex
    t = TerminalSession(id=sid, user_id=user.id, username=user.username, account=account_name(user.username),
                        device_id=device.id, hostname=device.hostname, level=level, status="issued",
                        client_ip=(request.headers.get("x-forwarded-for") or (request.client.host if request.client else ""))[:64])
    session.add(t)
    await session.commit()
    ticket = sign({"sid": sid, "username": user.username, "account": t.account, "level": level,
                   "device_id": device.id, "hostname": device.hostname, "host": host, "port": 22,
                   "exp": int(time.time()) + TICKET_SECONDS}, remote.secret_of(p))
    return {"session_id": sid, "ticket": ticket, "socket": f"/plugins/{p.name}/public/ws", "account": t.account,
            "level": level, "level_label": LEVEL_LABELS[level], "hostname": device.hostname}


@router.get("/terminal/sessions")
async def sessions(user: CurrentUser, session: Session, limit: int = 100, device_id: int | None = None):
    q = select(TerminalSession).order_by(TerminalSession.created_at.desc()).limit(min(limit, 500))
    if user.role != Role.ADMIN:
        q = q.where(TerminalSession.user_id == user.id)
    if device_id:
        q = q.where(TerminalSession.device_id == device_id)
    return [session_out(t) for t in await session.scalars(q)]


# --------------------------------------------------------------------------- admin

async def _plugin_or_503(session) -> RemotePlugin:
    p = await terminal_plugin(session)
    if p is None:
        raise HTTPException(503, "Install the SSH terminal plugin first (Setup → Plugin store)")
    return p


@router.get("/terminal/admin", dependencies=[require(Role.ADMIN)])
async def admin_info(session: Session):
    p = await _plugin_or_503(session)
    return {"plugin": p.name, "plugin_status": p.status, **await plugin_request(p, "GET", "/admin/info")}


class SetupIn(BaseModel):
    source: str = Field(max_length=64)


@router.post("/terminal/admin/setup", dependencies=[require(Role.ADMIN)])
async def setup_script(body: SetupIn, session: Session):
    out = await plugin_request(await _plugin_or_503(session), "POST", "/admin/setup", json={"source": body.source.strip()})
    if out.get("error"):
        raise HTTPException(400, out["error"])
    return out


class CheckIn(BaseModel):
    device_id: int


@router.post("/terminal/admin/check")
async def check_device(body: CheckIn, session: Session, user=require(Role.ADMIN)):
    device = await get_device_for(session, user, body.device_id)
    return await plugin_request(await _plugin_or_503(session), "POST", "/admin/check",
                                json={"host": device.ip or device.hostname, "port": 22})


class TargetIn(BaseModel):
    target: str = Field(max_length=300)


@router.post("/terminal/admin/forget-host", dependencies=[require(Role.ADMIN)])
async def forget_host(body: TargetIn, session: Session):
    return await plugin_request(await _plugin_or_503(session), "POST", "/admin/forget-host", json={"target": body.target})


class RemoveIn(BaseModel):
    account: str = Field(pattern=r"^ns-[a-z0-9][a-z0-9_-]{0,28}$")


@router.post("/terminal/admin/remove-account", dependencies=[require(Role.ADMIN)])
async def remove_account(body: RemoveIn, session: Session):
    return await plugin_request(await _plugin_or_503(session), "POST", "/admin/remove", json={"account": body.account})


async def user_gone(user: User) -> None:
    """A user was deleted or disabled: the terminal plugin removes their accounts from every server."""
    await publish("terminal_account_removed", {"account": account_name(user.username), "username": user.username})


# --------------------------------------------------------------------------- plugin → NETsync

async def _terminal_caller(request: Request, session: Session) -> RemotePlugin:
    from netsync.tools.api import calling_plugin, need

    p = await calling_plugin(request, session)
    need(p, "terminal")
    return p


class SessionReport(BaseModel):
    status: str = Field(pattern="^(connected|ended|failed)$")
    account: str | None = None
    reason: str | None = Field(None, max_length=2000)
    bytes_in: int | None = None
    bytes_out: int | None = None
    seconds: float | None = None


@router.patch("/plugin-api/terminal/sessions/{sid}")
async def report_session(sid: str, body: SessionReport, session: Session,
                         p: Annotated[RemotePlugin, Depends(_terminal_caller)]):
    t = await session.get(TerminalSession, sid)
    if t is None:
        raise HTTPException(404, "Unknown session")
    now = datetime.now(UTC)
    t.status = body.status
    if body.status == "connected":
        t.connected_at = now
    else:
        t.ended_at, t.reason = now, body.reason
        t.bytes_in, t.bytes_out = body.bytes_in, body.bytes_out
    await session.commit()
    return {"ok": True}


# --------------------------------------------------------------------------- bastion (desktop SSH clients)

MAX_FAILURES = 5
FAILURE_WINDOW = 300
_failures: dict[tuple[str, str], list[float]] = {}


def _limited(key: tuple[str, str], now: float) -> bool:
    recent = [t for t in _failures.get(key, []) if now - t < FAILURE_WINDOW]
    _failures[key] = recent
    return len(recent) >= MAX_FAILURES


class BastionIn(BaseModel):
    username: str = Field(max_length=64)
    password: str = Field(max_length=256)
    target: str = Field(max_length=255)
    client_ip: str = Field("", max_length=64)


async def find_device(session, user: User, ref: str) -> Device:
    """A server by IP, id or (part of a) hostname, among the devices the user may see."""
    from netsync.api.deps import device_scope
    from netsync.tools.base import Actor, ToolContext, ToolError
    from netsync.tools.builtin import resolve_device

    by_ip = list(await session.scalars(device_scope(select(Device).where(Device.ip == ref), user)))
    if len(by_ip) == 1:
        return by_ip[0]
    try:
        return await resolve_device(session, ToolContext(Actor("user", user.username, user=user)), ref)
    except ToolError as e:
        raise HTTPException(404, str(e)) from e


@router.post("/plugin-api/terminal/bastion")
async def bastion_login(body: BastionIn, session: Session, p: Annotated[RemotePlugin, Depends(_terminal_caller)]):
    """A desktop SSH client logs in through the plugin's bastion: check the NETsync password and the user's
    rights on the server, open an audited session and tell the plugin where to connect and as whom."""
    from netsync.security import verify_password

    now = time.time()
    key = (body.username.lower(), body.client_ip)
    if _limited(key, now):
        raise HTTPException(429, "Too many failed logins, wait a few minutes")
    user = await session.scalar(select(User).where(User.username == body.username))
    if user is None or not user.is_active or not verify_password(body.password, user.password_hash):
        _failures.setdefault(key, []).append(now)
        raise HTTPException(401, "Wrong user name or password")
    _failures.pop(key, None)
    device = await find_device(session, user, body.target.strip())
    level = level_for(user, device)
    if level == "none":
        raise HTTPException(403, f"Your groups don't give you terminal access to {device.hostname}")
    sid = uuid.uuid4().hex
    t = TerminalSession(id=sid, user_id=user.id, username=user.username, account=account_name(user.username),
                        device_id=device.id, hostname=device.hostname, level=level, status="issued", via="ssh",
                        client_ip=body.client_ip[:64])
    session.add(t)
    await session.commit()
    return {"sid": sid, "account": t.account, "level": level, "level_label": LEVEL_LABELS[level], "device_id": device.id,
            "hostname": device.hostname, "host": device.ip or device.hostname, "port": 22}


@router.get("/terminal/bastion")
async def bastion_info(user: CurrentUser, session: Session):
    """How to connect with a desktop SSH client (port and host key fingerprint)."""
    p = await terminal_plugin(session)
    if p is None or p.status != "online":
        raise HTTPException(503, "The SSH terminal plugin is not running")
    info = await plugin_request(p, "GET", "/admin/bastion")
    return {**info, "user": user.username}


@router.get("/plugin-api/terminal/accounts")
async def active_accounts(session: Session, p: Annotated[RemotePlugin, Depends(_terminal_caller)]):
    """Accounts that may exist on servers: one per active NETsync user. The plugin removes the others."""
    users = await session.scalars(select(User).where(User.is_active.is_(True)))
    return {"accounts": sorted({account_name(u.username) for u in users})}
