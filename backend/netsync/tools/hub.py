"""The tool hub: one place where every tool is listed, allowed, approved, run and audited."""

from __future__ import annotations

import json
import logging
import time
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select

from netsync.alerting import publish
from netsync.db import SessionLocal
from netsync.models import ToolCall, ToolPolicy
from netsync.plugins.registry import registry
from netsync.tools import remote
from netsync.tools.base import Actor, Mode, Tool, ToolContext, ToolError, redact, validate_args

log = logging.getLogger(__name__)

MAX_RESULT_CHARS = 60_000  # stored and returned; longer results are cut


async def all_tools() -> dict[str, Tool]:
    """In-process plugin tools plus tools of approved, online container plugins."""
    tools = {t.name: t for p in registry.plugins.values() for t in getattr(p, "tools", []) or []}
    for t in await remote.tools():
        tools.setdefault(t.name, t)
    return tools


async def policies() -> dict[str, Mode]:
    async with SessionLocal() as s:
        return {p.name: p.mode for p in await s.scalars(select(ToolPolicy))}  # type: ignore[misc]


def mode_of(tool: Tool, overrides: dict[str, Mode]) -> Mode:
    mode = overrides.get(tool.name, tool.default_mode)
    # a write tool can be switched off or need approval, but "auto" for writes must be chosen explicitly
    return mode if mode in ("auto", "approve", "off") else tool.default_mode


async def visible_tools(actor: Actor) -> list[Tool]:
    """What this actor may see in tools/list."""
    overrides = await policies()
    out = []
    for t in (await all_tools()).values():
        if mode_of(t, overrides) == "off" or not actor.may_use(t.name):
            continue
        if t.risk == "write" and not actor.write:
            continue
        out.append(t)
    return sorted(out, key=lambda t: t.name)


def _cut(result: Any) -> Any:
    text = json.dumps(result, default=str)
    if len(text) <= MAX_RESULT_CHARS:
        return json.loads(text)
    return {"truncated": True, "text": text[:MAX_RESULT_CHARS]}


async def _execute(tool: Tool, ctx: ToolContext, args: dict[str, Any]) -> Any:
    if tool.handler is not None:
        return await tool.handler(ctx, args)
    return await remote.call(tool, ctx, args)


async def call(name: str, args: dict[str, Any] | None, actor: Actor, origin: str, reason: str | None = None) -> dict:
    """Run a tool (or file an approval request). Returns {"status": "done"|"pending"|"error", ...}."""
    tools = await all_tools()
    tool = tools.get(name)
    if tool is None or not actor.may_use(name):
        raise ToolError(f"unknown tool: {name}")
    mode = mode_of(tool, await policies())
    if mode == "off":
        raise ToolError(f"tool {name} is switched off")
    if tool.risk == "write" and not actor.write:
        raise ToolError(f"{actor.label} may not use write tools")
    args = validate_args(tool.input_schema, args or {})

    async with SessionLocal() as s:
        row = ToolCall(tool=name, risk=tool.risk, origin=origin, actor=actor.label[:128], arguments=redact(args),
                       status="pending" if tool.risk == "write" and mode == "approve" else "running",
                       reason=(reason or "")[:2000] or None)
        s.add(row)
        await s.commit()
        call_id = row.id
    if row.status == "pending":
        await publish("tool_approval", {"call_id": call_id, "tool": name, "actor": actor.label})
        return {"status": "pending", "call_id": call_id,
                "message": f"Waiting for approval in NETsync (Setup → AI tools, request #{call_id})."}
    return await _run(call_id, tool, ToolContext(actor, call_id, origin), args)


async def _run(call_id: int, tool: Tool, ctx: ToolContext, args: dict[str, Any]) -> dict:
    started = time.monotonic()
    status, result, error = "done", None, None
    try:
        result = _cut(await _execute(tool, ctx, args))
    except ToolError as e:
        status, error = "error", str(e)
    except Exception as e:  # noqa: BLE001 - a broken tool must not break the hub
        log.exception("tool %s failed", tool.name)
        status, error = "error", f"{type(e).__name__}: {e}"[:2000]
    async with SessionLocal() as s:
        row = await s.get(ToolCall, call_id)
        if row:
            row.status, row.result, row.error = status, result, error
            row.duration_ms = int((time.monotonic() - started) * 1000)
            await s.commit()
    return {"status": status, "call_id": call_id, "result": result, "error": error}


async def decide(call_id: int, approve: bool, by: str, actor_for_run: Actor) -> dict:
    """Approve (and run) or reject a pending write call."""
    async with SessionLocal() as s:
        row = await s.get(ToolCall, call_id)
        if row is None:
            raise ToolError("request not found")
        if row.status != "pending":
            raise ToolError(f"request is already {row.status}")
        row.decided_by, row.decided_at = by, datetime.now(UTC)
        if not approve:
            row.status = "rejected"
            await s.commit()
            return {"status": "rejected", "call_id": call_id}
        row.status = "running"
        await s.commit()
        name, args = row.tool, row.arguments
    tool = (await all_tools()).get(name)
    if tool is None:
        return await _fail(call_id, "the tool is no longer available")
    # redacted values can't be replayed: such tools must take secrets from their own vault, not arguments
    if "********" in json.dumps(args):
        return await _fail(call_id, "arguments contained secrets and can't be replayed after approval")
    return await _run(call_id, tool, ToolContext(actor_for_run, call_id, "approval"), args)


async def _fail(call_id: int, error: str) -> dict:
    async with SessionLocal() as s:
        row = await s.get(ToolCall, call_id)
        if row:
            row.status, row.error = "error", error
            await s.commit()
    return {"status": "error", "call_id": call_id, "error": error}


async def result_of(call_id: int, actor: Actor) -> dict:
    async with SessionLocal() as s:
        row = await s.get(ToolCall, call_id)
        if row is None or (row.actor != actor.label and actor.kind != "user"):
            raise ToolError("request not found")
        return {"status": row.status, "call_id": row.id, "tool": row.tool, "result": row.result, "error": row.error,
                "decided_by": row.decided_by}
