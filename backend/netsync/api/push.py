"""Push monitors: GET or POST /api/push/<token>?status=up|down&msg=...&ping=...

No login: the secret token in the URL is the credential (only its SHA-256 is stored). Rate limited per
token and per client address. Unknown, revoked or paused tokens all get 404."""

import logging
import time
from datetime import UTC, datetime
from typing import Literal

from fastapi import APIRouter, HTTPException, Query, Request
from sqlalchemy import select

from netsync.api.deps import Session
from netsync.models import Device, Probe, State
from netsync.probing.base import Result, short
from netsync.probing.checkers.push import TOKEN_PREFIX, hash_push_token
from netsync.probing.runner import record

log = logging.getLogger(__name__)
router = APIRouter(prefix="/push", tags=["push"])

PER_TOKEN_PER_MINUTE = 60
PER_IP_PER_MINUTE = 600


async def _limited(key: str, limit: int) -> bool:
    from netsync.alerting import redis

    k = f"netsync:rl:push:{key}:{int(time.time() // 60)}"
    try:
        n = await redis().incr(k)
        if n == 1:
            await redis().expire(k, 90)
        return n > limit
    except Exception:  # noqa: BLE001 - never fail a push because redis is down
        log.debug("push rate limit skipped", exc_info=True)
        return False


@router.api_route("/{token}", methods=["GET", "POST"])
async def push(token: str, request: Request, session: Session,
               status: Literal["up", "down"] = "up",
               msg: str | None = Query(None, max_length=200),
               ping: float | None = Query(None, ge=0, le=3_600_000)):
    if not token.startswith(TOKEN_PREFIX) or len(token) > 80:
        raise HTTPException(404, "Not found")
    digest = hash_push_token(token)
    client = request.client.host if request.client else "unknown"
    if await _limited(f"ip:{client}", PER_IP_PER_MINUTE) or await _limited(f"t:{digest[:16]}", PER_TOKEN_PER_MINUTE):
        raise HTTPException(429, "Too many pushes", headers={"Retry-After": "60"})
    probe = await session.scalar(select(Probe).where(Probe.push_token_hash == digest, Probe.kind == "push"))
    if not probe or not probe.enabled:
        raise HTTPException(404, "Not found")
    device = await session.get(Device, probe.device_id)
    now = datetime.now(UTC)
    up = status == "up"
    text = short(msg) if msg and msg.strip() else ("push received" if up else "push reported down")
    probe.last_push_at = now
    events = await record(session, probe, device, Result(up, ping, State.OK if up else State.CRIT, text), now)
    await session.commit()
    from netsync.alerting import dispatch

    await dispatch(events)
    return {"ok": True}
