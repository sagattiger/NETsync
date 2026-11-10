"""Uptime % and average response time per probe from the hourly continuous aggregate."""

from sqlalchemy import text

from netsync.probing.runner import uptime_pct

WINDOWS = {"24h": "24 hours", "7d": "7 days", "30d": "30 days", "1y": "365 days"}

_cols = ",\n".join(
    f"sum(total) FILTER (WHERE bucket >= now() - INTERVAL '{iv}') AS t_{k}, "
    f"sum(up) FILTER (WHERE bucket >= now() - INTERVAL '{iv}') AS u_{k}, "
    f"sum(ms_sum) FILTER (WHERE bucket >= now() - INTERVAL '{iv}') AS s_{k}, "
    f"sum(ms_n) FILTER (WHERE bucket >= now() - INTERVAL '{iv}') AS n_{k}"
    for k, iv in WINDOWS.items()
)
QUERY = text(
    f"SELECT probe_id, {_cols} FROM probe_beats_hourly "
    "WHERE probe_id = ANY(:ids) AND bucket >= now() - INTERVAL '366 days' GROUP BY probe_id"
)


async def uptimes(session, probe_ids: list[int]) -> dict[int, dict]:
    """{probe_id: {"uptime": {"24h": 99.9, ...}, "avg_ms": {"24h": 12.3, ...}}} (None where no data)."""
    out = {pid: {"uptime": dict.fromkeys(WINDOWS), "avg_ms": dict.fromkeys(WINDOWS)} for pid in probe_ids}
    if not probe_ids:
        return out
    for row in (await session.execute(QUERY, {"ids": probe_ids})).mappings():
        o = out[row["probe_id"]]
        for k in WINDOWS:
            o["uptime"][k] = uptime_pct(row[f"t_{k}"], row[f"u_{k}"])
            n = row[f"n_{k}"]
            o["avg_ms"][k] = round(row[f"s_{k}"] / n, 2) if n else None
    return out
