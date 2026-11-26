"""IP Book health: the last ping state of every (row, IP), kept in one Redis hash shared by the ping service (writes)
and the API (reads, and the Ping button)."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

HASH = "netsync:ipbook:health"
DOWN_AFTER = 3  # missed pings in a row


def key(row_id: int, ip: str) -> str:
    return f"{row_id}:{ip}"


def next_state(prev: dict | None, answered: bool, rtt: float | None, now: datetime) -> dict[str, Any]:
    """Down after 3 missed pings in a row; up on the first answer; unknown until then."""
    prev = prev or {"misses": 0, "state": "unknown"}
    if answered:
        return {"misses": 0, "state": "up", "rtt": round(rtt, 2) if rtt is not None else None, "at": now.isoformat()}
    misses = int(prev.get("misses", 0)) + 1
    state = "down" if misses >= DOWN_AFTER else prev.get("state", "unknown")
    return {"misses": misses, "state": state, "rtt": None, "at": now.isoformat()}


async def read(redis) -> dict[str, dict]:
    try:
        raw = await redis.hgetall(HASH)
    except Exception:  # noqa: BLE001 - no Redis: no health shown, the list still works
        return {}
    out = {}
    for k, v in (raw or {}).items():
        try:
            out[k] = json.loads(v)
        except ValueError:
            continue
    return out


async def write(redis, states: dict[str, dict], drop: set[str] | None = None) -> None:
    if states:
        await redis.hset(HASH, mapping={k: json.dumps(v) for k, v in states.items()})
    if drop:
        await redis.hdel(HASH, *drop)


async def ping(ips: list[str], count: int = 2, timeout: float = 2) -> dict[str, tuple[bool, float | None]]:
    """Ping each address once (count echo requests); {ip: (answered, avg rtt ms)}."""
    if not ips:
        return {}
    from icmplib import async_multiping

    hosts = await async_multiping(ips, count=count, timeout=timeout, privileged=False, concurrent_tasks=100)
    return {h.address: (h.is_alive, h.avg_rtt if h.is_alive else None) for h in hosts}
