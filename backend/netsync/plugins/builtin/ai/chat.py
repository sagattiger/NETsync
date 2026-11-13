"""AI coworker: the sidebar chat.

The model is small (a 2 GB GPU runs ~1B models), so it never answers facts from memory: it calls the hub's tools
(alert history, syslog search, metric summaries...) and only phrases what they return. Each turn runs as a task
that keeps going (and saves the answer) when the browser disconnects; the API streams its events.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select

from netsync.db import SessionLocal
from netsync.models import ChatConversation, ChatMessage, Device
from netsync.plugins.builtin.ai import ollama
from netsync.tools import hub
from netsync.tools.base import Actor, Tool, ToolError

log = logging.getLogger(__name__)

MAX_ROUNDS = 5  # tool rounds per answer
HISTORY_TURNS = 4  # earlier questions (with their tools and answers) sent to the model
TOOL_CHARS = 3500  # a tool result as the model sees it
OLD_TOOL_CHARS = 1000  # ... in earlier turns
STORE_CHARS = 20_000  # a tool result as stored for the UI

PAGES = [
    (re.compile(r"^/problems"), "the Problems list"),
    (re.compile(r"^/syslog"), "the Syslog page"),
    (re.compile(r"^/probes"), "the Probes page"),
    (re.compile(r"^/devices/?$"), "the Devices list"),
    (re.compile(r"^/dashboards"), "a dashboard"),
    (re.compile(r"^/setup/ai-tools"), "the AI tools page"),
    (re.compile(r"^/?$"), "the Home page"),
]
DEVICE_PAGE = re.compile(r"^/devices/(\d+)(?:/([a-z-]+))?")

_busy: set[int] = set()  # users with an answer in progress
_tasks: set[asyncio.Task] = set()  # keeps running turns referenced


def system_prompt(cfg: dict[str, Any], now: datetime) -> str:
    """Stays the same all day, so Ollama can reuse its cache of the prompt and tool list between questions."""
    lines = [
        "You are the NETsync AI coworker, helping a network engineer with the NETsync monitoring system.",
        "Rules:",
        "- For any fact about devices, alerts, logs or graphs, call a tool first. Never guess numbers, names or times.",
        "- Answer only from tool results. If a tool returns an error or nothing, say so plainly.",
        "- Be short: a few sentences or a small list. Give counts, durations and times exactly as the tools return them.",
        "- Durations are in minutes unless a field says otherwise; times are UTC.",
        "- If a tool says it is waiting for approval, tell the user to approve it in Setup → AI tools.",
        f"- Answer in {cfg.get('language') or 'English'}.",
        f"Today is {now:%Y-%m-%d} (UTC).",
    ]
    if (cfg.get("extra_instructions") or "").strip():
        lines.append("About this network: " + cfg["extra_instructions"].strip())
    return "\n".join(lines)


async def page_note(session, actor: Actor, page: dict | None) -> tuple[str | None, str | None]:
    """What the user is looking at (so "this device" works), and the device's hostname on a device page."""
    path = str((page or {}).get("path") or "")
    m = DEVICE_PAGE.match(path)
    if m:
        dev = await session.get(Device, int(m.group(1)))
        if dev is None or not await _may_see(session, actor, dev.id):
            return None, None
        tab = f" ({m.group(2)} tab)" if m.group(2) else ""
        return (f"The user is looking at device '{dev.hostname}'{tab}. When they say 'this device', 'this host' or "
                f"don't name one, use device '{dev.hostname}'."), dev.hostname
    for pattern, label in PAGES:
        if pattern.match(path):
            return f"The user is looking at {label}.", None
    return None, None


def mentioned(value: str, text: str) -> bool:
    """Whether a device name the model chose appears in the conversation (small models invent hostnames)."""
    v = value.strip().lower()
    if not v:
        return False
    if v.isdigit() or v in text:
        return True
    short = v.split(".")[0]
    return len(short) >= 3 and short in text


def guard_device(args: dict, schema: dict, said: str, page_host: str | None) -> dict:
    """Replace or drop a 'device' argument nobody mentioned: the page's device, or no device when it's optional."""
    dev = args.get("device")
    if not isinstance(dev, str) or "device" not in (schema.get("properties") or {}):
        return args
    if mentioned(dev, said) or (page_host and mentioned(dev, page_host.lower())):
        return args
    if page_host:
        return {**args, "device": page_host}
    if "device" not in (schema.get("required") or []):
        return {k: v for k, v in args.items() if k != "device"}
    return args


async def _may_see(session, actor: Actor, device_id: int) -> bool:
    from netsync.tools.base import ToolContext
    from netsync.tools.builtin import allowed_devices

    allowed = await allowed_devices(session, ToolContext(actor))
    return allowed is None or device_id in allowed


# Shorter wording for the chat: every token of the tool list is read on each question, and small GPUs are slow at it
CHAT_HINTS = {
    "netsync__metric_summary": "Average, min, max (with time) and latest value of a device graph over 1, 7, 30 or 365 days.",
}
PARAM_HINTS = {
    ("netsync__metric_summary", "graph"): "Graph id: cpu, load, mem_usage, swap_usage, storage, temperature, fanspeed, "
                                          "latency, loss, port_traffic, port_errors, disk_io, uptime",
    ("netsync__metric_summary", "component"): "Port, disk, filesystem or sensor name (needed for those graphs)",
}


def first_sentence(text: str, limit: int = 200) -> str:
    m = re.match(r"(.+?[.!?])(\s|$)", text.strip(), re.S)
    s = m.group(1) if m else text.strip()
    return s if len(s) <= limit else s[: limit - 1] + "…"


def tool_spec(t: Tool) -> dict:
    """The tool as the chat model sees it: short descriptions, no limits or defaults (the hub checks those)."""
    props = {}
    for key, spec in (t.input_schema.get("properties") or {}).items():
        p = {k: spec[k] for k in ("type", "enum") if k in spec}
        desc = PARAM_HINTS.get((t.name, key)) or spec.get("description")
        if desc:
            p["description"] = first_sentence(desc, 120)
        props[key] = p
    params = {"type": "object", "properties": props}
    if t.input_schema.get("required"):
        params["required"] = t.input_schema["required"]
    return {"type": "function", "function": {
        "name": t.name, "description": CHAT_HINTS.get(t.name) or first_sentence(t.description), "parameters": params}}


def compact(value: Any, limit: int) -> str:
    text = json.dumps(value, default=str, separators=(",", ":"), ensure_ascii=False)
    return text if len(text) <= limit else text[:limit] + "…(cut)"


def for_model(out: dict) -> Any:
    """What the model reads back from a hub call."""
    if out.get("status") == "pending":
        return {"status": "waiting for approval", "call_id": out.get("call_id"), "message": out.get("message")}
    if out.get("status") == "error":
        return {"error": out.get("error")}
    return out.get("result")


def history_messages(rows: list[ChatMessage]) -> list[dict]:
    """Earlier turns as Ollama messages: the last HISTORY_TURNS questions with their tool calls and answers."""
    starts = [i for i, r in enumerate(rows) if r.role == "user"]
    rows = rows[starts[-HISTORY_TURNS]:] if len(starts) > HISTORY_TURNS else rows
    out: list[dict] = []
    for r in rows:
        if r.role == "user":
            out.append({"role": "user", "content": r.content})
        elif r.role == "tool":
            out.append({"role": "assistant", "content": "", "tool_calls": [
                {"function": {"name": r.tool, "arguments": r.arguments or {}}}]})
            out.append({"role": "tool", "tool_name": r.tool,
                        "content": compact(for_model(r.result or {}), OLD_TOOL_CHARS)})
        elif r.role == "assistant" and r.content:
            out.append({"role": "assistant", "content": r.content})
    return out


def parse_args(raw: Any) -> dict:
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        try:
            v = json.loads(raw)
            return v if isinstance(v, dict) else {}
        except ValueError:
            return {}
    return {}


def title_of(text: str) -> str:
    t = re.sub(r"\s+", " ", text).strip()
    return t[:77] + "…" if len(t) > 80 else t or "New chat"


class Turn:
    """One question and its answer. Events go to a queue the HTTP stream reads; the turn finishes either way."""

    def __init__(self, cfg: dict, actor: Actor, conversation_id: int, text: str, page: dict | None):
        self.cfg, self.actor, self.conversation_id, self.text, self.page = cfg, actor, conversation_id, text, page
        self.queue: asyncio.Queue[dict | None] = asyncio.Queue()
        self.model = cfg.get("chat_model") or cfg.get("model")
        self.page_host: str | None = None
        self.said = text.lower()

    def emit(self, event: dict) -> None:
        self.queue.put_nowait(event)

    async def run(self) -> None:
        started = time.monotonic()
        answer, error = "", None
        try:
            answer = await self._answer()
        except ollama.OllamaError as e:
            error = str(e)
        except Exception as e:
            log.exception("chat turn failed")
            error = f"{type(e).__name__}: {e}"
        if error:
            self.emit({"type": "error", "error": error})
        async with SessionLocal() as s:
            msg = ChatMessage(conversation_id=self.conversation_id, role="assistant",
                              content=answer or (f"⚠ {error}" if error else ""), model=self.model,
                              duration=round(time.monotonic() - started, 2))
            s.add(msg)
            conv = await s.get(ChatConversation, self.conversation_id)
            if conv:
                conv.updated_at = datetime.now(UTC)
            await s.commit()
            self.emit({"type": "done", "message_id": msg.id, "duration": msg.duration, "model": self.model})
        self.queue.put_nowait(None)

    async def _answer(self) -> str:
        async with SessionLocal() as s:
            rows = list(await s.scalars(select(ChatMessage).where(ChatMessage.conversation_id == self.conversation_id)
                                        .order_by(ChatMessage.id)))
            note, self.page_host = await page_note(s, self.actor, self.page)
        # everything said so far: device names the model uses must come from here (or the page)
        self.said = " ".join(r.content for r in rows if r.role in ("user", "assistant")).lower()
        self.said += " " + " ".join(json.dumps(r.result or {}, default=str) for r in rows if r.role == "tool").lower()
        # rows already holds this turn's question (saved before the turn started); the page and time go with it
        # rather than in the system prompt, which keeps the prompt prefix cacheable
        now = datetime.now(UTC)
        history = history_messages(rows)
        if history and history[-1]["role"] == "user":
            context = f"[{now:%H:%M} UTC. {note}]" if note else f"[{now:%H:%M} UTC]"
            history[-1] = {**history[-1], "content": context + "\n" + history[-1]["content"]}
        messages = [{"role": "system", "content": system_prompt(self.cfg, now)}, *history]
        tools = await hub.visible_tools(self.actor)
        specs = [tool_spec(t) for t in tools if t.name != "netsync__call_result"]
        known = {t.name: t for t in tools}
        seen_calls: set[str] = set()

        for round_ in range(MAX_ROUNDS):
            think = ollama.ThinkFilter()
            text, calls = "", []
            # in the last round no tools are offered, so the model has to answer
            async for chunk in ollama.chat_stream(self.cfg, messages, specs if round_ < MAX_ROUNDS - 1 else None,
                                                  model=self.model):
                m = chunk.get("message") or {}
                if m.get("tool_calls"):
                    calls.extend(m["tool_calls"])
                piece = think.feed(m.get("content") or "")
                if piece:
                    text += piece
                    self.emit({"type": "delta", "text": piece})
            tail = think.flush()
            if tail:
                text += tail
                self.emit({"type": "delta", "text": tail})
            if not calls:
                return text.strip()
            messages.append({"role": "assistant", "content": text, "tool_calls": calls})
            if text.strip():
                self.emit({"type": "reset"})  # text before a tool call was thinking aloud, not the answer
            for c in calls:
                fn = c.get("function") or {}
                name, args = str(fn.get("name") or ""), parse_args(fn.get("arguments"))
                key = name + json.dumps(args, sort_keys=True, default=str)
                if key in seen_calls:  # small models loop on the same call: give them the hint to answer
                    out = {"status": "error", "error": "already called with these arguments; answer from the result above"}
                else:
                    seen_calls.add(key)
                    out = await self._call(name, args, known)
                messages.append({"role": "tool", "tool_name": name, "content": compact(for_model(out), TOOL_CHARS)})
        return ""

    async def _call(self, name: str, args: dict, known: dict[str, Tool]) -> dict:
        if name in known:
            args = guard_device(args, known[name].input_schema, self.said, self.page_host)
        self.emit({"type": "tool", "tool": name, "arguments": args})
        if name not in known:
            out = {"status": "error", "error": f"unknown tool {name}. Available: {', '.join(sorted(known))}"}
        else:
            try:
                out = await hub.call(name, args, self.actor, "chat", reason=f"AI chat: {self.text[:300]}")
            except ToolError as e:
                out = {"status": "error", "error": str(e)}
        stored = {"status": out.get("status"), "call_id": out.get("call_id"), "error": out.get("error"),
                  "message": out.get("message")}
        if out.get("result") is not None:
            text = json.dumps(out["result"], default=str)
            stored["result"] = out["result"] if len(text) <= STORE_CHARS else {"truncated": True, "text": text[:STORE_CHARS]}
        async with SessionLocal() as s:
            msg = ChatMessage(conversation_id=self.conversation_id, role="tool", tool=name[:128], arguments=args,
                              result=stored)
            s.add(msg)
            await s.commit()
            self.emit({"type": "tool_result", "id": msg.id, "tool": name, "arguments": args, "result": stored})
        return out


async def start_turn(cfg: dict, actor: Actor, user_id: int, conversation_id: int | None, text: str,
                     page: dict | None) -> tuple[int, int, Turn]:
    """Save the question (creating the conversation if needed) and start answering it."""
    async with SessionLocal() as s:
        conv = await s.get(ChatConversation, conversation_id) if conversation_id else None
        if conversation_id and (conv is None or conv.user_id != user_id):
            raise LookupError("conversation not found")
        if conv is None:
            conv = ChatConversation(user_id=user_id, title=title_of(text))
            s.add(conv)
            await s.flush()
        conv.updated_at = datetime.now(UTC)
        msg = ChatMessage(conversation_id=conv.id, role="user", content=text,
                          page={k: str(v)[:200] for k, v in (page or {}).items() if k in ("path", "title")} or None)
        s.add(msg)
        await s.commit()
        conv_id, msg_id = conv.id, msg.id
    turn = Turn(cfg, actor, conv_id, text, page)
    _busy.add(user_id)

    async def runner() -> None:
        try:
            await turn.run()
        finally:
            _busy.discard(user_id)

    task = asyncio.create_task(runner())
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)
    return conv_id, msg_id, turn


def busy(user_id: int) -> bool:
    return user_id in _busy


async def events(turn: Turn, keepalive: float = 15) -> AsyncIterator[dict]:
    """The turn's events; a ping when it is quiet (a slow model) so proxies don't close the stream."""
    while True:
        try:
            ev = await asyncio.wait_for(turn.queue.get(), keepalive)
        except TimeoutError:
            yield {"type": "ping"}
            continue
        if ev is None:
            return
        yield ev


# --------------------------------------------------------------------------- @mentions in event threads

async def answer_with_tools(cfg: dict, actor: Actor, messages: list[dict]) -> str:
    """The same tool loop as the chat, without streaming or saving: returns the final answer."""
    tools = [t for t in await hub.visible_tools(actor) if t.risk == "read"]
    specs = [tool_spec(t) for t in tools if t.name != "netsync__call_result"]
    known = {t.name: t for t in tools}
    model = cfg.get("chat_model") or cfg.get("model")
    seen: set[str] = set()
    for round_ in range(MAX_ROUNDS):
        think = ollama.ThinkFilter()
        text, calls = "", []
        async for chunk in ollama.chat_stream(cfg, messages, specs if round_ < MAX_ROUNDS - 1 else None, model=model):
            m = chunk.get("message") or {}
            calls.extend(m.get("tool_calls") or [])
            text += think.feed(m.get("content") or "")
        text += think.flush()
        if not calls:
            return text.strip()
        messages.append({"role": "assistant", "content": text, "tool_calls": calls})
        for c in calls:
            fn = c.get("function") or {}
            name, args = str(fn.get("name") or ""), parse_args(fn.get("arguments"))
            key = name + json.dumps(args, sort_keys=True, default=str)
            if name not in known:
                out = {"status": "error", "error": f"unknown tool {name}"}
            elif key in seen:
                out = {"status": "error", "error": "already called with these arguments; answer from the result above"}
            else:
                seen.add(key)
                try:
                    out = await hub.call(name, args, actor, "chat", reason="@mention in an event thread")
                except ToolError as e:
                    out = {"status": "error", "error": str(e)}
            messages.append({"role": "tool", "tool_name": name, "content": compact(for_model(out), TOOL_CHARS)})
    return ""


async def reply_in_thread(session, cfg: dict, job) -> str:
    """Answer an @mention in an event's comment thread: the event, the thread so far, and the question."""
    from netsync.models import EventComment, User
    from netsync.plugins.builtin.ai import context
    from netsync.tools.api import user_actor

    user = await session.scalar(select(User).where(User.username == job.requested_by))
    if user is None or not user.is_active:
        raise LookupError("The user who asked no longer exists")
    _, event_text = await context.event_prompt(session, job)
    thread = list(await session.scalars(select(EventComment).where(
        EventComment.device_id == job.device_id, EventComment.service_id == job.service_id,
        EventComment.event_time == job.event_time).order_by(EventComment.created_at)))
    question = next((c for c in thread if c.id == job.comment_id), None)
    if question is None:
        raise LookupError("The comment was deleted")
    name = (cfg.get("mention_name") or "netwatcher").strip().lstrip("@")
    lines = [f"- {'AI' if c.ai else c.author}: {c.body.strip()[:800]}" for c in thread if c.id != question.id][-8:]
    system = system_prompt(cfg, datetime.now(UTC)) + (
        f"\nYou are @{name}, replying in the comment thread of a monitoring alert. Answer the last comment directly, "
        "in two to four sentences. Start from the current state. Use the tools for history, logs and graphs. "
        "Don't repeat the whole analysis and don't invent numbers.")
    from netsync.models import Service, State

    from netsync.models import Device, StateChange

    # a small model latches onto whatever number it reads first: give it a few labelled facts, current state first
    # (the full analysis context in event_text is too long for that)
    del event_text
    svc = await session.get(Service, job.service_id)
    device = await session.get(Device, job.device_id)
    ev = await session.scalar(select(StateChange).where(StateChange.service_id == job.service_id,
                                                        StateChange.time == job.event_time))
    facts = [f"- Device: {device.hostname if device else '?'}", f"- Service: {svc.name if svc else '?'}"]
    if svc:
        facts.append(f"- NOW: {State(svc.state).name}, {svc.output}")
    if ev:
        facts.append(f"- When the alert started ({ev.time:%Y-%m-%d %H:%M} UTC): {State(ev.new_state).name}, {ev.output}")
    user_msg = ("## Facts\n" + "\n".join(facts) + "\n\n## Comments so far\n" + ("\n".join(lines) or "(none)")
                + f"\n\n## {question.author} writes\n{question.body.strip()}\n\n"
                "Reply to that comment. Base it on the NOW line; use the tools if you need history or logs.")
    answer = await answer_with_tools(cfg, user_actor(user), [{"role": "system", "content": system},
                                                             {"role": "user", "content": user_msg}])
    if not answer:
        raise LookupError("The model gave no answer")
    return f"@{question.author} {answer}"
