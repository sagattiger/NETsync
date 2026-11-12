"""HTTP side of the tool hub.

* ``POST /api/mcp``: MCP server (Streamable HTTP, JSON responses) for Claude Desktop, n8n and other MCP clients,
  authenticated with an MCP token (``nsm_...``).
* ``/api/tools``, ``/api/tool-calls``: tool list and policies, test calls, audit log and approvals (UI).
* ``/api/mcp-tokens``: MCP tokens and their scopes (admin).
* ``/api/remote-plugins``: container plugins (admin).
* ``/api/plugin-api``: what container plugins may call back (with their secret and granted permissions).
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import select

from netsync import __version__
from netsync.alerting import EVENTS_CHANNEL, redis
from netsync.api.deps import CurrentUser, Session, require
from netsync.api.tokens import LAST_USED_RESOLUTION, _rate_limited, hash_token, token_out, token_problem
from netsync.models import ApiToken, RemotePlugin, Role, ToolCall, ToolPolicy, User
from netsync.probing.secrets import encrypt
from netsync.tools import hub, remote
from netsync.tools.base import Actor, ToolError

log = logging.getLogger(__name__)
router = APIRouter(tags=["tool hub"])

MCP_PREFIX = "nsm_"
PROTOCOL_VERSIONS = ("2025-06-18", "2025-03-26", "2024-11-05")
INSTRUCTIONS = ("NETsync network monitoring. Use netsync__find_devices to find a hostname, netsync__list_problems for what "
                "is wrong now, netsync__alert_history for how often and how long alerts happened, netsync__search_syslog "
                "for log messages and netsync__metric_summary for graph values. Write tools may need a person's approval: "
                "then check netsync__call_result later.")


def user_actor(user: User) -> Actor:
    return Actor("user", user.username, user=user, write=user.role in (Role.ADMIN, Role.OPERATOR))


# --------------------------------------------------------------------------- MCP


async def mcp_token(request: Request, session: Session) -> ApiToken:
    scheme, _, value = request.headers.get("authorization", "").partition(" ")
    value = value.strip()
    if scheme.lower() != "bearer" or not value.startswith(MCP_PREFIX):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "MCP token required", headers={"WWW-Authenticate": "Bearer"})
    now = datetime.now(UTC)
    row = await session.scalar(select(ApiToken).where(ApiToken.token_hash == hash_token(value), ApiToken.kind == "mcp"))
    if problem := token_problem(row, now):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, problem, headers={"WWW-Authenticate": "Bearer"})
    if await _rate_limited(row.id):
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Rate limit exceeded", headers={"Retry-After": "60"})
    if row.last_used_at is None or now - row.last_used_at >= LAST_USED_RESOLUTION:
        row.last_used_at = now
        await session.commit()
    return row


def token_actor(t: ApiToken) -> Actor:
    sc = t.scopes or {}
    return Actor("token", t.name, tools=list(sc.get("tools") or ["netsync__*"]), write=bool(sc.get("write")))


def rpc_result(id_: Any, result: Any) -> dict:
    return {"jsonrpc": "2.0", "id": id_, "result": result}


def rpc_error(id_: Any, code: int, message: str) -> dict:
    return {"jsonrpc": "2.0", "id": id_, "error": {"code": code, "message": message}}


def tool_result(out: dict) -> dict:
    """Hub answer -> MCP CallToolResult."""
    if out["status"] == "pending":
        payload: Any = {"status": "pending_approval", "call_id": out["call_id"], "message": out["message"]}
        return {"content": [{"type": "text", "text": json.dumps(payload)}], "structuredContent": payload, "isError": False}
    if out["status"] == "error":
        return {"content": [{"type": "text", "text": out["error"] or "error"}], "isError": True}
    result = out["result"]
    structured = result if isinstance(result, dict) else {"result": result}
    return {"content": [{"type": "text", "text": json.dumps(result, default=str)}], "structuredContent": structured,
            "isError": False}


async def handle_rpc(msg: Any, actor: Actor) -> dict | None:
    if not isinstance(msg, dict) or msg.get("jsonrpc") != "2.0" or "method" not in msg:
        return rpc_error(msg.get("id") if isinstance(msg, dict) else None, -32600, "Invalid Request")
    method, id_, params = msg["method"], msg.get("id"), msg.get("params") or {}
    if "id" not in msg:  # notification (e.g. notifications/initialized): no answer
        return None
    try:
        if method == "initialize":
            asked = params.get("protocolVersion")
            return rpc_result(id_, {
                "protocolVersion": asked if asked in PROTOCOL_VERSIONS else PROTOCOL_VERSIONS[0],
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {"name": "netsync", "title": "NETsync", "version": __version__},
                "instructions": INSTRUCTIONS,
            })
        if method == "ping":
            return rpc_result(id_, {})
        if method == "tools/list":
            return rpc_result(id_, {"tools": [t.describe() for t in await hub.visible_tools(actor)]})
        if method == "tools/call":
            name = params.get("name")
            args = params.get("arguments") or {}
            try:
                out = await hub.call(str(name), args, actor, "mcp", reason=(params.get("_meta") or {}).get("reason"))
            except ToolError as e:
                return rpc_result(id_, {"content": [{"type": "text", "text": str(e)}], "isError": True})
            return rpc_result(id_, tool_result(out))
        if method in ("resources/list", "prompts/list"):
            return rpc_result(id_, {method.split("/")[0]: []})
        return rpc_error(id_, -32601, f"Method not found: {method}")
    except Exception as e:  # noqa: BLE001
        log.exception("MCP %s failed", method)
        return rpc_error(id_, -32603, f"Internal error: {e}")


@router.post("/mcp")
async def mcp(request: Request, token: Annotated[ApiToken, Depends(mcp_token)]):
    origin = request.headers.get("origin")
    if origin and request.headers.get("host", "") not in origin:
        raise HTTPException(403, "Cross-origin MCP requests are not allowed")  # DNS rebinding protection
    try:
        body = await request.json()
    except ValueError:
        return JSONResponse(rpc_error(None, -32700, "Parse error"), status_code=400)
    actor = token_actor(token)
    if isinstance(body, list):
        answers = [a for a in [await handle_rpc(m, actor) for m in body] if a is not None]
        return JSONResponse(answers) if answers else Response(status_code=202)
    answer = await handle_rpc(body, actor)
    return JSONResponse(answer) if answer is not None else Response(status_code=202)


@router.get("/mcp")
async def mcp_stream():
    # no server-initiated messages: clients fall back to plain request/response
    return Response(status_code=405, headers={"Allow": "POST"})


# --------------------------------------------------------------------------- tools (UI)


@router.get("/tools")
async def list_tools(user: CurrentUser):
    overrides = await hub.policies()
    tools = await hub.all_tools()
    return [{**t.describe(), "plugin": t.plugin or t.name.split("__")[0], "risk": t.risk,
             "mode": hub.mode_of(t, overrides), "default_mode": t.default_mode} for t in sorted(tools.values(), key=lambda t: t.name)]


class PolicyIn(BaseModel):
    mode: str = Field(pattern="^(auto|approve|off)$")


@router.put("/tools/{name}/policy", dependencies=[require(Role.ADMIN)])
async def set_policy(name: str, body: PolicyIn, session: Session):
    tool = (await hub.all_tools()).get(name)
    if tool is None:
        raise HTTPException(404, "Tool not found")
    row = await session.get(ToolPolicy, name)
    if body.mode == tool.default_mode:
        if row:
            await session.delete(row)
    else:
        if row is None:
            row = ToolPolicy(name=name, mode=body.mode)
            session.add(row)
        row.mode = body.mode
    await session.commit()
    return {"name": name, "mode": body.mode}


class CallIn(BaseModel):
    arguments: dict[str, Any] = {}
    reason: str | None = Field(None, max_length=2000)


@router.post("/tools/{name}/call")
async def call_tool(name: str, body: CallIn, user: CurrentUser):
    try:
        return await hub.call(name, body.arguments, user_actor(user), "ui", body.reason)
    except ToolError as e:
        raise HTTPException(400, str(e)) from e


def call_out(c: ToolCall) -> dict:
    return {"id": c.id, "created_at": c.created_at, "tool": c.tool, "risk": c.risk, "origin": c.origin, "actor": c.actor,
            "arguments": c.arguments, "status": c.status, "result": c.result, "error": c.error,
            "duration_ms": c.duration_ms, "decided_by": c.decided_by, "decided_at": c.decided_at, "reason": c.reason}


@router.get("/tool-calls", dependencies=[require(Role.OPERATOR)])
async def tool_calls(session: Session, status_: Annotated[str | None, Query(alias="status")] = None, limit: int = 100):
    q = select(ToolCall).order_by(ToolCall.created_at.desc()).limit(min(max(limit, 1), 500))
    if status_:
        q = q.where(ToolCall.status == status_)
    return [call_out(c) for c in await session.scalars(q)]


@router.post("/tool-calls/{call_id}/{decision}")
async def decide(call_id: int, decision: str, user=require(Role.OPERATOR)):
    if decision not in ("approve", "reject"):
        raise HTTPException(404, "Unknown decision")
    try:
        return await hub.decide(call_id, decision == "approve", user.username, user_actor(user))
    except ToolError as e:
        raise HTTPException(400, str(e)) from e


# --------------------------------------------------------------------------- MCP tokens (admin)


class McpTokenIn(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    tools: list[str] = Field(default_factory=lambda: ["netsync__*"], max_length=50)
    write: bool = False
    expires_at: datetime | None = None


@router.get("/mcp-tokens", dependencies=[require(Role.ADMIN)])
async def list_mcp_tokens(session: Session):
    rows = await session.scalars(select(ApiToken).where(ApiToken.kind == "mcp").order_by(ApiToken.created_at.desc()))
    return [{**token_out(t), "scopes": t.scopes} for t in rows]


@router.post("/mcp-tokens")
async def create_mcp_token(body: McpTokenIn, session: Session, user=require(Role.ADMIN)):
    import secrets as pysecrets

    expires = body.expires_at.replace(tzinfo=body.expires_at.tzinfo or UTC) if body.expires_at else None
    if expires and expires <= datetime.now(UTC):
        raise HTTPException(400, "Expiry must be in the future")
    patterns = [p.strip() for p in body.tools if p.strip()] or ["netsync__*"]
    if any(len(p) > 128 or not all(c.isalnum() or c in "_*?" for c in p) for p in patterns):
        raise HTTPException(400, "Tool patterns may only use letters, digits, _ and the wildcards * ?")
    token = MCP_PREFIX + pysecrets.token_urlsafe(30)[:40]
    row = ApiToken(name=body.name.strip(), token_hash=hash_token(token), prefix=token[:8], created_by=user.username,
                   expires_at=expires, kind="mcp", scopes={"tools": patterns, "write": body.write})
    session.add(row)
    await session.commit()
    return {**token_out(row), "scopes": row.scopes, "token": token}


@router.delete("/mcp-tokens/{token_id}", dependencies=[require(Role.ADMIN)])
async def revoke_mcp_token(token_id: int, session: Session):
    row = await session.get(ApiToken, token_id)
    if not row or row.kind != "mcp":
        raise HTTPException(404, "Token not found")
    row.revoked = True
    await session.commit()
    return token_out(row)


# --------------------------------------------------------------------------- container plugins (admin)


def plugin_out(p: RemotePlugin) -> dict:
    m = p.manifest or {}
    return {"id": p.id, "name": p.name, "url": p.url, "enabled": p.enabled, "status": p.status,
            "status_detail": p.status_detail, "last_seen": p.last_seen, "created_at": p.created_at, "created_by": p.created_by,
            "version": m.get("version"), "description": m.get("description"), "tools": m.get("tools", []),
            "requested": [{"key": k, "label": remote.PERMISSIONS[k]} for k in m.get("permissions", [])],
            "granted": p.granted or []}


class RemoteIn(BaseModel):
    name: str = Field(pattern=r"^[a-z][a-z0-9_]{1,30}$")
    url: str = Field(max_length=512)


class RemoteUpdate(BaseModel):
    url: str | None = Field(None, max_length=512)
    enabled: bool | None = None
    granted: list[str] | None = None


@router.get("/remote-plugins", dependencies=[require(Role.ADMIN)])
async def list_remote(session: Session):
    return [plugin_out(p) for p in await session.scalars(select(RemotePlugin).order_by(RemotePlugin.name))]


@router.post("/remote-plugins")
async def add_remote(body: RemoteIn, session: Session, user=require(Role.ADMIN)):
    from netsync.plugins.registry import registry

    if body.name in registry.plugins or await session.scalar(select(RemotePlugin).where(RemotePlugin.name == body.name)):
        raise HTTPException(400, f"A plugin named {body.name!r} already exists")
    try:
        url = remote.valid_url(body.url)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    secret = remote.new_secret()
    p = RemotePlugin(name=body.name, url=url, secret_enc=encrypt({"secret": secret}), secret_hash=remote.hash_secret(secret),
                     created_by=user.username, status="pending", manifest={}, granted=[])
    session.add(p)
    await session.commit()
    return {**plugin_out(p), "secret": secret}  # shown once


@router.put("/remote-plugins/{plugin_id}", dependencies=[require(Role.ADMIN)])
async def update_remote(plugin_id: int, body: RemoteUpdate, session: Session):
    p = await session.get(RemotePlugin, plugin_id)
    if p is None:
        raise HTTPException(404, "Plugin not found")
    if body.url is not None:
        try:
            p.url = remote.valid_url(body.url)
        except ValueError as e:
            raise HTTPException(400, str(e)) from e
    if body.enabled is not None:
        p.enabled = body.enabled
    if body.granted is not None:
        asked = (p.manifest or {}).get("permissions", [])
        p.granted = [g for g in body.granted if g in asked]
    await remote.refresh(p)
    await session.commit()
    return plugin_out(p)


@router.post("/remote-plugins/{plugin_id}/rotate-secret", dependencies=[require(Role.ADMIN)])
async def rotate_secret(plugin_id: int, session: Session):
    p = await session.get(RemotePlugin, plugin_id)
    if p is None:
        raise HTTPException(404, "Plugin not found")
    secret = remote.new_secret()
    p.secret_enc, p.secret_hash, p.status = encrypt({"secret": secret}), remote.hash_secret(secret), "pending"
    remote.invalidate()
    await session.commit()
    return {**plugin_out(p), "secret": secret}


@router.delete("/remote-plugins/{plugin_id}", dependencies=[require(Role.ADMIN)])
async def delete_remote(plugin_id: int, session: Session):
    p = await session.get(RemotePlugin, plugin_id)
    if p is None:
        raise HTTPException(404, "Plugin not found")
    await session.delete(p)
    await session.commit()
    remote.invalidate()
    return {"ok": True}


# --------------------------------------------------------------------------- plugin → NETsync


async def calling_plugin(request: Request, session: Session) -> RemotePlugin:
    scheme, _, value = request.headers.get("authorization", "").partition(" ")
    value = value.strip()
    if scheme.lower() != "bearer" or not value.startswith(remote.SECRET_PREFIX):
        raise HTTPException(401, "Plugin secret required")
    p = await session.scalar(select(RemotePlugin).where(RemotePlugin.secret_hash == remote.hash_secret(value)))
    if p is None or not p.enabled:
        raise HTTPException(401, "Unknown or disabled plugin")
    return p


def need(p: RemotePlugin, permission: str) -> None:
    if permission not in (p.granted or []):
        raise HTTPException(403, f"The admin has not granted '{permission}' to plugin {p.name}")


class PluginCallIn(BaseModel):
    name: str
    arguments: dict[str, Any] = {}


@router.post("/plugin-api/tools/call")
async def plugin_call(body: PluginCallIn, p: Annotated[RemotePlugin, Depends(calling_plugin)]):
    need(p, "call:read")
    tool = (await hub.all_tools()).get(body.name)
    if tool is None or tool.risk != "read" or tool.plugin == p.name:
        raise HTTPException(400, "Only other plugins' read-only tools can be called")
    try:
        return await hub.call(body.name, body.arguments, Actor("plugin", p.name), "plugin")
    except ToolError as e:
        raise HTTPException(400, str(e)) from e


@router.get("/plugin-api/events")
async def plugin_events(p: Annotated[RemotePlugin, Depends(calling_plugin)]):
    """Server-sent events: every NETsync event (alerts, recoveries, syslog, AI jobs) as JSON."""
    need(p, "events")

    async def stream():
        pubsub = redis().pubsub()
        await pubsub.subscribe(EVENTS_CHANNEL)
        try:
            yield ": connected\n\n"
            while True:
                msg = await pubsub.get_message(ignore_subscribe_messages=True, timeout=15)
                yield f"data: {msg['data']}\n\n" if msg else ": keep-alive\n\n"
                await asyncio.sleep(0)
        finally:
            await pubsub.unsubscribe(EVENTS_CHANNEL)
            await pubsub.aclose()

    return StreamingResponse(stream(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"})
