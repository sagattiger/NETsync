"""AI job queue: hooks create jobs, the worker's background service runs them against Ollama."""

import asyncio
import json
import logging
import re
import time
from datetime import UTC, datetime, timedelta

from redis.exceptions import TimeoutError as RedisTimeoutError
from sqlalchemy import func, or_, select, update
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.orm.exc import StaleDataError

from netsync.alerting import publish, redis
from netsync.db import SessionLocal
from netsync.models import AIJob, EventComment, State
from netsync.plugins.base import BackgroundService
from netsync.plugins.builtin.ai import context, ollama
from netsync.plugins.settings import cached_settings

log = logging.getLogger(__name__)

QUEUE = "netsync:ai"
AI_AUTHOR = "NETsync AI"


def plugin():
    from netsync.plugins.builtin.ai import plugin as p

    return p


async def enqueue(job_id: int) -> None:
    await redis().rpush(QUEUE, json.dumps({"job_id": job_id}))


async def create_job(session, **fields) -> AIJob:
    job = AIJob(status="pending", **fields)
    session.add(job)
    await session.commit()
    await enqueue(job.id)
    return job


async def _auto_allowed(session, cfg, *, service_id=None, device_id=None) -> bool:
    now = datetime.now(UTC)
    hourly = await session.scalar(select(func.count()).select_from(AIJob).where(
        AIJob.auto.is_(True), AIJob.created_at >= now - timedelta(hours=1)))
    if hourly >= int(cfg.get("max_auto_per_hour", 20)):
        return False
    since = now - timedelta(minutes=int(cfg.get("cooldown_minutes", 30)))
    q = select(AIJob.id).where(AIJob.created_at >= since, AIJob.auto.is_(True))
    q = q.where(AIJob.service_id == service_id) if service_id else q.where(AIJob.kind == "syslog", AIJob.device_id == device_id)
    return (await session.scalar(q.limit(1))) is None


# --------------------------------------------------------------------------- hooks

async def on_state_change(events) -> None:
    enabled, cfg = await cached_settings(plugin())
    if not enabled or not cfg.get("auto_events"):
        return
    min_state = int(cfg.get("event_min_state", State.WARN))
    async with SessionLocal() as s:
        for service_id, ev in events:
            # WARN / CRIT only (UNKNOWN and recoveries are not analysed)
            if ev.new_state not in (State.WARN, State.CRIT) or ev.new_state < min_state:
                continue
            if await _auto_allowed(s, cfg, service_id=service_id):
                await create_job(s, kind="event", device_id=ev.device_id, service_id=service_id,
                                 event_time=ev.time, auto=True, requested_by=AI_AUTHOR)


async def on_syslog(rows) -> None:
    enabled, cfg = await cached_settings(plugin())
    if not enabled or not cfg.get("auto_syslog"):
        return
    max_sev = int(cfg.get("syslog_min_severity", 3))
    async with SessionLocal() as s:
        for row in rows:
            if row.get("id") is None or not row.get("device_id") or row["severity"] > max_sev:
                continue
            if await _auto_allowed(s, cfg, device_id=row["device_id"]):
                await create_job(s, kind="syslog", device_id=row["device_id"], syslog_id=row["id"],
                                 syslog_time=row["time"], auto=True, requested_by=AI_AUTHOR)


def mentioned(body: str, cfg: dict) -> bool:
    """Does the comment call the AI by its name (default @netwatcher)?"""
    name = re.escape((cfg.get("mention_name") or "netwatcher").strip().lstrip("@"))
    return bool(name) and re.search(rf"(^|[^\w@.])@{name}(?![\w])", body or "", re.I) is not None


# --------------------------------------------------------------------------- worker

FIRST_SECTION = re.compile(r"^\s*(?:#+\s*)?\*{0,2}What happened", re.I | re.M)


def trim_preamble(answer: str) -> str:
    """Small models like to open with "Okay, here's a breakdown..." - start at the first section."""
    m = FIRST_SECTION.search(answer)
    return answer[m.start():].lstrip() if m and m.start() > 0 else answer

DEADLOCK_RETRIES = 3


def is_deadlock(e: Exception) -> bool:
    return "deadlock detected" in str(e).lower()


async def save_result(job_id: int, fields: dict, comment: dict | None) -> bool:
    """Write a finished job (and its event comment) in a fresh session. Retried on a deadlock, which can happen
    when a restarting API runs its schema upgrade while the answer is saved. False = the device is gone."""
    for attempt in range(DEADLOCK_RETRIES):
        async with SessionLocal() as s:
            job = await s.get(AIJob, job_id)
            if not job:
                return False
            for k, v in fields.items():
                setattr(job, k, v)
            if comment:
                s.add(EventComment(**comment))
            try:
                await s.commit()
                return True
            except (StaleDataError, IntegrityError):
                await s.rollback()
                return False
            except DBAPIError as e:
                await s.rollback()
                if not is_deadlock(e) or attempt == DEADLOCK_RETRIES - 1:
                    raise
                await asyncio.sleep(1 + attempt)
    return False


async def run_job(job_id: int) -> None:
    enabled, cfg = await cached_settings(plugin(), ttl=5)
    async with SessionLocal() as s:
        job = await s.get(AIJob, job_id)
        if not job or job.status not in ("pending", "running"):
            return
        if not enabled:
            job.status, job.error, job.finished_at = "error", "The AI assistant is disabled", datetime.now(UTC)
            await s.commit()
            return
        job.status, job.model = "running", cfg.get("model")
        await s.commit()
        started = time.monotonic()
        try:
            if job.kind == "reply":
                from netsync.plugins.builtin.ai import chat

                answer = await chat.reply_in_thread(s, cfg, job)
            elif job.kind == "event":
                _, prompt = await context.event_prompt(s, job)
                answer = trim_preamble(await ollama.chat(cfg, context.system_prompt(cfg), prompt))
            else:
                _, prompt = await context.syslog_prompt(s, job)
                answer = trim_preamble(await ollama.chat(cfg, context.system_prompt(cfg), prompt))
            job.status, job.result = "done", answer
            if job.kind in ("event", "reply"):
                s.add(EventComment(device_id=job.device_id, service_id=job.service_id, event_time=job.event_time,
                                   body=answer, author=AI_AUTHOR, author_id=None, ai=True))
        except (ollama.OllamaError, LookupError) as e:
            job.status, job.error = "error", str(e)
        except Exception as e:
            log.exception("AI job %s failed", job_id)
            job.status, job.error = "error", f"Unexpected error: {e}"
        job.duration = time.monotonic() - started
        job.finished_at = datetime.now(UTC)
        try:
            await s.commit()
        except (StaleDataError, IntegrityError):
            # the device (and its jobs) was deleted while the model was answering
            await s.rollback()
            log.info("AI job %s dropped: its device was deleted meanwhile", job_id)
            return
        except DBAPIError as e:
            if not is_deadlock(e):
                raise
            # rare lock clash (e.g. an API restart upgrading the schema): save again in a new session
            fields = {k: getattr(job, k) for k in ("status", "result", "error", "model", "duration", "finished_at")}
            comment = None
            if job.kind in ("event", "reply") and job.status == "done":
                comment = {"device_id": job.device_id, "service_id": job.service_id, "event_time": job.event_time,
                           "body": job.result, "author": AI_AUTHOR, "author_id": None, "ai": True}
            device_id = job.device_id
            await s.rollback()
            if not await save_result(job_id, fields, comment):
                log.info("AI job %s dropped: its device was deleted meanwhile", job_id)
                return
            await publish("ai_job", {"job_id": job_id, "status": fields["status"], "device_id": device_id})
            return
        await publish("ai_job", {"job_id": job.id, "status": job.status, "device_id": job.device_id})


class AIService(BackgroundService):
    name = "ai_assistant"

    async def run(self, stop: asyncio.Event) -> None:
        # Jobs interrupted by a restart: put them back in the queue.
        async with SessionLocal() as s:
            stale = list(await s.scalars(select(AIJob.id).where(or_(AIJob.status == "running", AIJob.status == "pending"),
                                                               AIJob.created_at >= datetime.now(UTC) - timedelta(hours=6))))
            await s.execute(update(AIJob).where(AIJob.id.in_(stale)).values(status="pending"))
            await s.commit()
        running: set[asyncio.Task] = set()
        while not stop.is_set():
            enabled, cfg = await cached_settings(plugin())
            limit = max(1, int(cfg.get("concurrency", 1)))
            if not enabled or len(running) >= limit:
                await asyncio.sleep(2)
                continue
            try:
                item = await redis().blpop([QUEUE], timeout=5)
            except (TimeoutError, RedisTimeoutError):
                continue
            except Exception:
                log.exception("AI queue error")
                await asyncio.sleep(5)
                continue
            if not item:
                continue
            task = asyncio.create_task(run_job(int(json.loads(item[1])["job_id"])))
            running.add(task)
            task.add_done_callback(running.discard)
