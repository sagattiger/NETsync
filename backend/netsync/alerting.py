"""State change handling: downtimes, acknowledgements, notification dispatch, live events."""

import json
import logging
from datetime import datetime

import redis.asyncio as aioredis
from sqlalchemy import and_, select

from netsync.config import get_settings
from netsync.db import SessionLocal
from netsync.models import Device, Downtime, NotificationRule, Service, State
from netsync.plugins.base import AlertEvent
from netsync.plugins.registry import registry

log = logging.getLogger(__name__)

EVENTS_CHANNEL = "netsync:events"

_redis: aioredis.Redis | None = None


def redis() -> aioredis.Redis:
    global _redis
    if _redis is None:
        # socket_timeout must exceed the BLPOP wait used by the worker's job listener.
        _redis = aioredis.from_url(
            get_settings().redis_url, decode_responses=True, socket_timeout=30, health_check_interval=30
        )
    return _redis


async def publish(kind: str, data: dict) -> None:
    try:
        await redis().publish(EVENTS_CHANNEL, json.dumps({"type": kind, **data}, default=str))
    except Exception:
        log.debug("redis publish failed", exc_info=True)


async def in_downtime(session, device_id: int, service_id: int | None, at: datetime) -> bool:
    q = select(Downtime.id).where(
        Downtime.device_id == device_id,
        Downtime.start <= at,
        Downtime.end >= at,
        (Downtime.service_id.is_(None)) | (Downtime.service_id == service_id),
    )
    return (await session.scalar(q.limit(1))) is not None


async def dispatch(events: list[tuple[int, AlertEvent]]) -> None:
    """Send notifications for (service_id, event) pairs after they were committed."""
    if not events:
        return
    channels = registry.channels
    async with SessionLocal() as s:
        rules = list(await s.scalars(select(NotificationRule).where(NotificationRule.enabled.is_(True))))
        for service_id, ev in events:
            await publish("state_change", ev.__dict__)
            if await in_downtime(s, ev.device_id, service_id, ev.time):
                continue
            svc = await s.get(Service, service_id)
            if svc and svc.acknowledged and ev.new_state != State.OK:
                continue
            device = await s.get(Device, ev.device_id)
            group_ids = {g.id for g in device.groups} if device else set()
            recovery = ev.new_state == State.OK
            for rule in rules:
                if rule.device_group_id and rule.device_group_id not in group_ids:
                    continue
                if recovery:
                    if not rule.notify_recovery or ev.old_state < rule.min_state:
                        continue
                elif ev.new_state < rule.min_state:
                    continue
                channel = channels.get(rule.channel)
                if not channel:
                    log.warning("notification rule %s uses unknown channel %s", rule.name, rule.channel)
                    continue
                try:
                    await channel.send(ev, rule.config)
                except Exception:
                    log.exception("notification %s via %s failed", rule.name, rule.channel)


async def active_downtime_device_ids(session, at: datetime) -> set[int]:
    q = select(Downtime.device_id).where(and_(Downtime.start <= at, Downtime.end >= at, Downtime.service_id.is_(None)))
    return set(await session.scalars(q))
