"""Time-bucketed metric series, shared by /devices/{id}/metrics and the public dashboards API."""

from datetime import UTC, datetime, timedelta

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

# range -> (span, time_bucket width). asyncpg needs timedelta objects for interval parameters.
RANGES: dict[str, tuple[timedelta, timedelta]] = {
    "1h": (timedelta(hours=1), timedelta(minutes=1)),
    "6h": (timedelta(hours=6), timedelta(minutes=2)),
    "24h": (timedelta(hours=24), timedelta(minutes=5)),
    "7d": (timedelta(days=7), timedelta(minutes=30)),
    "30d": (timedelta(days=30), timedelta(hours=2)),
    "1y": (timedelta(days=365), timedelta(days=1)),
}

QUERY = text(
    "SELECT name, time_bucket(CAST(:bucket AS interval), time) AS t, avg(value), min(value), max(value) "
    "FROM metrics WHERE device_id = :d AND component_id = :c AND name = ANY(:names) AND time >= :since "
    "GROUP BY name, t ORDER BY t"
)


async def bucketed_series(session: AsyncSession, device_id: int, component_id: int, names: list[str],
                          range_: str, bucket: timedelta | None = None) -> dict[str, list]:
    """{name: [[iso_time, avg, min, max], ...]} - every requested name is present, possibly empty.
    ``bucket`` overrides the range's default bucket width (e.g. one point per day for uptime)."""
    span, default_bucket = RANGES.get(range_, RANGES["24h"])
    bucket = bucket or default_bucket
    since = datetime.now(UTC) - span
    rows = await session.execute(QUERY, {"bucket": bucket, "d": device_id, "c": component_id,
                                         "names": names, "since": since})
    out: dict[str, list] = {n: [] for n in names}
    for n, t, avg, mn, mx in rows:
        out[n].append([t.isoformat(), avg, mn, mx])
    return out


LATEST = text(
    "SELECT DISTINCT ON (component_id, name) component_id, name, value FROM metrics "
    "WHERE device_id = :d AND name = ANY(:names) AND time >= :since "
    "ORDER BY component_id, name, time DESC"
)


async def latest_values(session: AsyncSession, device_id: int, names: list[str],
                        max_age: timedelta = timedelta(minutes=30)) -> dict[int, dict[str, float]]:
    """{component_id: {name: last value}} of a device's recent samples (top-N bar widgets)."""
    rows = await session.execute(LATEST, {"d": device_id, "names": names, "since": datetime.now(UTC) - max_age})
    out: dict[int, dict[str, float]] = {}
    for comp, name, value in rows:
        out.setdefault(comp, {})[name] = value
    return out
