"""REST endpoints of the AI assistant, mounted at /api/plugins/ai."""

import json
import re
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import and_, func, select

from netsync.api.deps import CurrentUser, Session, device_scope, get_device_for, require
from netsync.models import (
    AIJob,
    ChatConversation,
    ChatMessage,
    Device,
    Role,
    Service,
    StateChange,
    SyslogMessage,
)
from netsync.plugins import settings as plugin_settings
from netsync.plugins.builtin.ai import chat, ollama
from netsync.plugins.builtin.ai.service import create_job, plugin

router = APIRouter()

REUSE_MINUTES = 15
MAX_PENDING_PER_USER = 5


def job_out(j: AIJob) -> dict:
    return {
        "id": j.id, "kind": j.kind, "status": j.status, "auto": j.auto, "model": j.model,
        "result": j.result, "error": j.error, "duration": j.duration, "device_id": j.device_id,
        "service_id": j.service_id, "event_time": j.event_time, "syslog_id": j.syslog_id,
        "requested_by": j.requested_by, "created_at": j.created_at, "finished_at": j.finished_at,
    }


@router.get("/status")
async def status(user: CurrentUser, session: Session):
    enabled, cfg = await plugin_settings.get_settings(session, plugin())
    on = enabled and bool(cfg.get("base_url")) and bool(cfg.get("model"))
    return {"enabled": on, "model": cfg.get("model") or None, "chat": on and bool(cfg.get("chat_enabled", True)),
            "chat_model": cfg.get("chat_model") or cfg.get("model") or None}


class ConnIn(BaseModel):
    config: dict[str, Any] = {}


async def _effective(session, body: ConnIn) -> dict[str, Any]:
    _, current = await plugin_settings.get_settings(session, plugin())
    try:
        return plugin_settings.coerce(plugin(), body.config, current)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e


@router.post("/models", dependencies=[require(Role.ADMIN)])
async def models(body: ConnIn, session: Session):
    try:
        return await ollama.list_models(await _effective(session, body))
    except ollama.OllamaError as e:
        raise HTTPException(502, str(e)) from e


@router.post("/test", dependencies=[require(Role.ADMIN)])
async def test(body: ConnIn, session: Session):
    cfg = await _effective(session, body)
    try:
        names = [m["name"] for m in await ollama.list_models(cfg)]
    except ollama.OllamaError as e:
        raise HTTPException(502, str(e)) from e
    if not cfg.get("model"):
        return {"ok": True, "message": f"Connected. {len(names)} models available - pick one."}
    if cfg["model"] not in names:
        raise HTTPException(400, f"Connected, but model '{cfg['model']}' is not installed. Available: {', '.join(names) or 'none'}")
    cfg = {**cfg, "timeout_seconds": max(60, int(cfg.get("timeout_seconds", 180)))}
    try:
        reply = await ollama.chat(cfg, "Reply with a single short sentence.", "Say that the NETsync AI assistant is ready.")
    except ollama.OllamaError as e:
        raise HTTPException(502, str(e)) from e
    return {"ok": True, "message": f"Connected to {cfg['model']}: “{reply[:160]}”"}


class AskIn(BaseModel):
    kind: Literal["service", "event", "syslog"]
    service_id: int | None = None
    event_time: datetime | None = None
    syslog_id: int | None = None
    syslog_time: datetime | None = None
    force: bool = False


@router.post("/ask")
async def ask(body: AskIn, user: CurrentUser, session: Session):
    enabled, cfg = await plugin_settings.get_settings(session, plugin())
    if not enabled or not cfg.get("base_url") or not cfg.get("model"):
        raise HTTPException(400, "The AI assistant is not enabled or not configured")

    pending = await session.scalar(select(func.count()).select_from(AIJob).where(
        AIJob.requested_by == user.username, AIJob.status.in_(["pending", "running"])))
    if pending >= MAX_PENDING_PER_USER:
        raise HTTPException(429, "You already have several AI requests running, wait for them to finish")

    if body.kind == "syslog":
        msg = await session.scalar(select(SyslogMessage).where(and_(
            SyslogMessage.id == body.syslog_id, SyslogMessage.time == body.syslog_time)))
        if not msg:
            raise HTTPException(404, "Syslog message not found")
        if msg.device_id:
            await get_device_for(session, user, msg.device_id)
        elif user.role != Role.ADMIN:
            raise HTTPException(404, "Syslog message not found")
        target = dict(kind="syslog", device_id=msg.device_id, syslog_id=msg.id, syslog_time=msg.time)
        existing_q = select(AIJob).where(AIJob.syslog_id == msg.id, AIJob.syslog_time == msg.time)
    else:
        svc = await session.get(Service, body.service_id) if body.service_id else None
        if not svc:
            raise HTTPException(404, "Service not found")
        await get_device_for(session, user, svc.device_id)
        if body.kind == "service":
            # the event that put the service into its current (problem) state
            ev = await session.scalar(select(StateChange).where(StateChange.service_id == svc.id)
                                      .order_by(StateChange.time.desc()).limit(1))
        else:
            ev = await session.scalar(select(StateChange).where(and_(
                StateChange.service_id == svc.id, StateChange.time == body.event_time)))
        if not ev:
            raise HTTPException(404, "No event found for this service")
        target = dict(kind="event", device_id=svc.device_id, service_id=svc.id, event_time=ev.time)
        existing_q = select(AIJob).where(AIJob.service_id == svc.id, AIJob.event_time == ev.time)

    if not body.force:
        recent = await session.scalar(existing_q.where(
            AIJob.status.in_(["pending", "running", "done"]),
            AIJob.created_at >= datetime.now(UTC) - timedelta(minutes=REUSE_MINUTES),
        ).order_by(AIJob.created_at.desc()).limit(1))
        if recent:
            return job_out(recent)
    job = await create_job(session, auto=False, requested_by=user.username, **target)
    return job_out(job)


async def _job_for(session, user, job_id: int) -> AIJob:
    job = await session.get(AIJob, job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    if job.device_id:
        await get_device_for(session, user, job.device_id)
    elif user.role != Role.ADMIN:
        raise HTTPException(404, "Job not found")
    return job


@router.get("/jobs/{job_id}")
async def get_job(job_id: int, user: CurrentUser, session: Session):
    return job_out(await _job_for(session, user, job_id))


@router.get("/jobs")
async def recent_jobs(user: CurrentUser, session: Session, limit: int = 50):
    """Admin overview of recent AI activity (settings dialog)."""
    if user.role != Role.ADMIN:
        raise HTTPException(403)
    rows = await session.scalars(select(AIJob).order_by(AIJob.created_at.desc()).limit(min(limit, 200)))
    return [job_out(j) for j in rows]


def _excerpt(markdown: str, limit: int = 220) -> str:
    """The "What happened" paragraph as plain text, for cards."""
    text = markdown or ""
    m = re.search(r"what happened\**:?\**\s*(.+?)(?:\n\s*\n|\n\s*\**likely causes|$)", text, re.I | re.S)
    text = m.group(1) if m else text
    text = re.sub(r"[*_`#>]+", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text[: limit - 1] + "…" if len(text) > limit else text


@router.get("/insights")
async def insights(user: CurrentUser, session: Session, limit: int = 12):
    """Latest AI explanations of events the user can see (Home carousel)."""
    q = (
        select(AIJob, Device.hostname, Service.name, StateChange.new_state)
        .join(Device, Device.id == AIJob.device_id)
        .join(Service, Service.id == AIJob.service_id)
        .join(StateChange, and_(StateChange.service_id == AIJob.service_id, StateChange.time == AIJob.event_time))
        .where(AIJob.kind == "event", AIJob.status == "done")
        .order_by(AIJob.finished_at.desc())
        .limit(min(limit, 50) * 3)
    )
    seen, out = set(), []
    for job, hostname, service, state in await session.execute(device_scope(q, user)):
        if job.service_id in seen:
            continue  # one card per service (latest analysis)
        seen.add(job.service_id)
        out.append({"job_id": job.id, "device_id": job.device_id, "hostname": hostname, "service": service,
                    "state": state, "event_time": job.event_time, "finished_at": job.finished_at,
                    "auto": job.auto, "excerpt": _excerpt(job.result or "")})
        if len(out) >= limit:
            break
    return out


# --------------------------------------------------------------------------- AI coworker (sidebar chat)

class ChatIn(BaseModel):
    message: str = Field(min_length=1, max_length=4000)
    conversation_id: int | None = None
    page: dict[str, Any] | None = None


def conv_out(c: ChatConversation) -> dict:
    return {"id": c.id, "title": c.title, "created_at": c.created_at, "updated_at": c.updated_at}


def msg_out(m: ChatMessage) -> dict:
    return {"id": m.id, "role": m.role, "content": m.content, "tool": m.tool, "arguments": m.arguments,
            "result": m.result, "page": m.page, "model": m.model, "duration": m.duration, "created_at": m.created_at}


async def _conversation(session, user, conv_id: int) -> ChatConversation:
    conv = await session.get(ChatConversation, conv_id)
    if conv is None or conv.user_id != user.id:
        raise HTTPException(404, "Conversation not found")
    return conv


@router.get("/chat/conversations")
async def chat_conversations(user: CurrentUser, session: Session, limit: int = 50):
    rows = await session.scalars(select(ChatConversation).where(ChatConversation.user_id == user.id)
                                 .order_by(ChatConversation.updated_at.desc()).limit(min(limit, 200)))
    return [conv_out(c) for c in rows]


@router.get("/chat/conversations/{conv_id}")
async def chat_conversation(conv_id: int, user: CurrentUser, session: Session):
    conv = await _conversation(session, user, conv_id)
    rows = await session.scalars(select(ChatMessage).where(ChatMessage.conversation_id == conv.id).order_by(ChatMessage.id))
    return {**conv_out(conv), "messages": [msg_out(m) for m in rows], "busy": chat.busy(user.id)}


@router.delete("/chat/conversations/{conv_id}")
async def delete_chat(conv_id: int, user: CurrentUser, session: Session):
    await session.delete(await _conversation(session, user, conv_id))
    await session.commit()
    return {"ok": True}


@router.post("/chat")
async def chat_send(body: ChatIn, user: CurrentUser, session: Session):
    enabled, cfg = await plugin_settings.get_settings(session, plugin())
    if not enabled or not cfg.get("base_url") or not (cfg.get("chat_model") or cfg.get("model")):
        raise HTTPException(400, "The AI assistant is not enabled or has no model (Setup → AI assistant)")
    if not cfg.get("chat_enabled", True):
        raise HTTPException(400, "The AI chat is switched off in the AI assistant settings")
    if chat.busy(user.id):
        raise HTTPException(429, "Still answering your previous question")
    from netsync.tools.api import user_actor

    try:
        conv_id, msg_id, turn = await chat.start_turn(cfg, user_actor(user), user.id, body.conversation_id,
                                                      body.message.strip(), body.page)
    except LookupError as e:
        raise HTTPException(404, "Conversation not found") from e

    async def stream():
        yield _sse({"type": "start", "conversation_id": conv_id, "message_id": msg_id})
        async for ev in chat.events(turn):
            yield _sse(ev)

    return StreamingResponse(stream(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


def _sse(ev: dict) -> str:
    return f"data: {json.dumps(ev, default=str)}\n\n"
