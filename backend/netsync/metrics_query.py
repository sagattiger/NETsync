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
                          range_: str) -> dict[str, list]:
    """{name: [[iso_time, avg, min, max], ...]} - every requested name is present, possibly empty."""
    span, bucket = RANGES.get(range_, RANGES["24h"])
    since = datetime.now(UTC) - span
    rows = await session.execute(QUERY, {"bucket": bucket, "d": device_id, "c": component_id,
                                         "names": names, "since": since})
    out: dict[str, list] = {n: [] for n in names}
    for n, t, avg, mn, mx in rows:
        out[n].append([t.isoformat(), avg, mn, mx])
    return out
