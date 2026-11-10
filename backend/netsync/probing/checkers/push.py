"""Push (heartbeat / passive) monitors: a job calls a secret URL; DOWN when no push arrives within
interval + grace. The pushes themselves are recorded by /api/push/<token> (netsync/api/push.py)."""

import hashlib
import secrets
from datetime import UTC, datetime

from pydantic import Field

from netsync.models import State
from netsync.probing.base import Checker, KindConfig, ProbeSpec, Result, register

TOKEN_PREFIX = "nsp_"


def new_push_token() -> str:
    return TOKEN_PREFIX + secrets.token_urlsafe(24)


def hash_push_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


class PushConfig(KindConfig):
    grace_s: int = Field(30, ge=0, le=3600)  # extra time after the interval before the monitor is DOWN


def overdue(last_push_at: datetime | None, interval_s: int, grace_s: int, now: datetime | None = None,
            since: datetime | None = None) -> bool:
    """No push within interval + grace (counted from the last push, or from ``since`` before the first one)."""
    now = now or datetime.now(UTC)
    ref = last_push_at or since
    if ref is None:
        return False
    return (now - ref).total_seconds() > interval_s + grace_s


@register
class PushChecker(Checker):
    kind = "push"
    label = "Push (heartbeat)"
    Config = PushConfig
    concurrency = 200
    target_label = ""

    def validate_target(self, target: str) -> str:
        return ""  # no target: the job calls NETsync

    async def check(self, spec: ProbeSpec) -> Result | None:
        cfg = PushConfig(**spec.config)
        if not overdue(spec.last_push_at, spec.interval_s, cfg.grace_s, since=spec.created_at):
            return None  # heartbeats arrive in time; each push records its own beat
        return Result(False, None, State.CRIT, "no push received")
