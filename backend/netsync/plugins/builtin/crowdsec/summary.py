"""Totals over one or more CrowdSec sources: for the CrowdSec page and the public ``crowdsec`` dashboard widget.

``public_widget`` is the allow-list: totals, scenario keys, per-day counts and times. Never addresses (not even
masked), source names, LAPI URLs or error texts.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import text

from netsync.models import CrowdSecSource, State
from netsync.plugins.builtin.crowdsec import logic

DAYS = 7
STALE_INTERVALS = 3  # a source not read for 3 intervals is "stale" (pages say "data unavailable")

_DAY_QUERY = text(
    "SELECT time_bucket(CAST('1 day' AS interval), time, CAST(:tz AS text)) AS d, min(value), max(value) "
    "FROM metrics WHERE device_id = :dev AND component_id = 0 AND name = 'cs_new_total' AND time >= :since "
    "GROUP BY d ORDER BY d"
)
_BEFORE_QUERY = text(
    "SELECT value FROM metrics WHERE device_id = :dev AND component_id = 0 AND name = 'cs_new_total' "
    "AND time < :since AND time >= :floor ORDER BY time DESC LIMIT 1"
)
_WINDOW_QUERY = text(
    "SELECT min(value), max(value) FROM metrics WHERE device_id = :dev AND component_id = 0 "
    "AND name = 'cs_new_total' AND time >= :since"
)


def zone(name: str | None) -> ZoneInfo:
    try:
        return ZoneInfo(name or "UTC")
    except (KeyError, ValueError):
        return ZoneInfo("UTC")


def day_starts(now: datetime, tz: ZoneInfo, days: int = DAYS) -> list[datetime]:
    """Local midnights of the last ``days`` days, oldest first (today last)."""
    today = now.astimezone(tz).replace(hour=0, minute=0, second=0, microsecond=0)
    return [today - timedelta(days=i) for i in range(days - 1, -1, -1)]


async def new_bans(session, device_id: int, now: datetime, tz: ZoneInfo) -> dict:
    """{"days": [(date, n | None) x7], "24h": n | None, "7d": n | None} from the running count cs_new_total."""
    starts = day_starts(now, tz)
    since = starts[0]
    rows = (await session.execute(_DAY_QUERY, {"tz": tz.key, "dev": device_id, "since": since})).all()
    by_day = {r[0].astimezone(tz).date(): (float(r[1]), float(r[2])) for r in rows if r[1] is not None}
    before = await session.scalar(_BEFORE_QUERY, {"dev": device_id, "since": since, "floor": since - timedelta(days=2)})
    counts = logic.daily_new([by_day.get(d.date()) for d in starts], before)
    out = {"days": [(d.date().isoformat(), n) for d, n in zip(starts, counts, strict=True)]}
    for label, span in (("24h", timedelta(hours=24)), ("7d", timedelta(days=7))):
        mn, mx = (await session.execute(_WINDOW_QUERY, {"dev": device_id, "since": now - span})).one()
        prev = await session.scalar(_BEFORE_QUERY, {"dev": device_id, "since": now - span,
                                                    "floor": now - span - timedelta(days=2)})
        out[label] = None if mx is None else max(0, round(float(mx) - float(prev if prev is not None else mn)))
    return out


def add(a: int | None, b: int | None) -> int | None:
    return b if a is None else a if b is None else a + b


async def combined(session, sources: list[CrowdSecSource], services: dict[int, list], cfg: dict,
                   now: datetime | None = None) -> dict:
    """Totals of the given sources. ``services``: device id -> its Service rows (for the state)."""
    now = now or datetime.now(UTC)
    tz = zone(cfg.get("timezone"))
    interval = int(cfg.get("interval_s") or 300)
    local = community = total = other = 0
    scen: list[dict] = []
    days: list[int | None] = [None] * DAYS
    labels: list[str] = [d.date().isoformat() for d in day_starts(now, tz)]
    n24 = n7 = None
    last_ok: datetime | None = None
    since: float | None = None
    states: list[int] = []
    for src in sources:
        st = src.state or {}
        stats = st.get("stats") or {}
        if stats:
            local += int(stats.get("local", 0))
            community += int(stats.get("community", 0))
            total += int(stats.get("total", 0))
            other += int(stats.get("other", 0))
            scen.append(stats.get("scenarios") or {})
        tr = st.get("tracking") or {}
        if tr.get("since"):
            since = min(since or tr["since"], tr["since"])
        if src.last_ok and (last_ok is None or src.last_ok > last_ok):
            last_ok = src.last_ok
        states += [s.state for s in services.get(src.device_id, [])]
        nb = await new_bans(session, src.device_id, now, tz)
        days = [add(a, b) for a, b in zip(days, [n for _, n in nb["days"]], strict=True)]
        n24, n7 = add(n24, nb["24h"]), add(n7, nb["7d"])
    if last_ok is None:
        status = "none"
    elif (now - last_ok).total_seconds() > interval * STALE_INTERVALS:
        status = "stale"
    else:
        status = "ok"
    order = {State.OK: 0, State.UNKNOWN: 1, State.WARN: 2, State.CRIT: 3}
    worst = max(states, key=lambda s: order.get(s, 1)) if states else State.UNKNOWN
    return {
        "status": status, "state": State(worst).name, "updated_at": last_ok,
        "active": local, "community": community, "total": total, "other": other,
        "new_24h": n24, "new_7d": n7, "days": [[d, n] for d, n in zip(labels, days, strict=True)],
        "scenarios": logic.merge_scenarios(scen, limit=10),
        "since": datetime.fromtimestamp(since, UTC) if since else None,
    }


EMPTY = {"status": "none", "state": "UNKNOWN", "updated_at": None, "since": None, "active": 0, "community": 0,
         "total": 0, "other": 0, "new_24h": None, "new_7d": None, "days": [], "scenarios": []}


async def for_widgets(session, widgets: list[dict]) -> dict[str, dict]:
    """Widget id -> combined totals of its sources (``crowdsec_ids``, or every enabled source)."""
    from sqlalchemy import select

    from netsync.models import Service
    from netsync.plugins.builtin.crowdsec import plugin
    from netsync.plugins.settings import get_settings

    _, cfg = await get_settings(session, plugin)
    sources = list(await session.scalars(select(CrowdSecSource).where(CrowdSecSource.enabled.is_(True))))
    devs = [s.device_id for s in sources]
    services: dict[int, list] = {}
    if devs:
        for svc in await session.scalars(select(Service).where(Service.device_id.in_(devs))):
            services.setdefault(svc.device_id, []).append(svc)
    out = {}
    for w in widgets:
        wanted = set(w.get("crowdsec_ids") or [])
        mine = [s for s in sources if not wanted or s.id in wanted]
        out[w.get("id")] = await combined(session, mine, services, cfg) if mine else EMPTY
    return out


def public_widget(base: dict, w: dict, summary: dict) -> dict:
    """The public form of a ``crowdsec`` widget (allow-list only)."""
    limit = max(1, min(10, int(w.get("limit") or 5)))
    return {
        **base,
        "title": w.get("public_title") or "Threat protection",
        "state": summary["state"],
        "status": summary["status"],
        "updated_at": summary["updated_at"],
        "since": summary["since"],
        "active": summary["active"],
        "community": summary["community"],
        "total": summary["total"],
        "new_24h": summary["new_24h"],
        "new_7d": summary["new_7d"],
        "days": summary["days"],
        "scenarios": summary["scenarios"][:limit],
    }
