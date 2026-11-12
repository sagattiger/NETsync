"""Housekeeping: how long NETsync keeps each kind of data, compression, and cleanup.

Graph data lives in three tiers: every poll (``metrics``), hourly and daily rollups (continuous aggregates
``metrics_hourly`` / ``metrics_daily``, see db.py). Each tier, syslog, events and probe heartbeats has its own
retention, set by an admin on the Housekeeping page. A background service in the worker:

* builds the rollups from existing data once (before raw data may expire),
* applies retention and compression policies whenever the settings change,
* removes what deleted devices, probes and components left behind, old AI jobs and old event comments,
* records table sizes and the server's free disk space for the page.
"""

from __future__ import annotations

import asyncio
import json
import logging
import shutil
import time
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import APIRouter, HTTPException
from sqlalchemy import text

from netsync.alerting import redis
from netsync.api.deps import Session, require
from netsync.db import SessionLocal, engine
from netsync.models import Role
from netsync.plugins.base import BackgroundService, Plugin
from netsync.plugins.settings import cached_settings, invalidate

log = logging.getLogger(__name__)

NAME = "housekeeping"
RUN_QUEUE = "netsync:housekeeping:run"
LAST_RUN = "netsync:housekeeping:last"
PURGE_EVERY = 6 * 3600  # seconds between automatic cleanups
CHECK_EVERY = 60  # seconds between settings checks

DEFAULTS: dict[str, Any] = {
    "metrics_raw_days": 30,
    "metrics_hourly_days": 365,
    "metrics_daily_days": 1825,
    "compress_after_days": 7,
    "syslog_days": 90,
    "events_days": 730,
    "probe_beats_days": 90,
    "probe_hourly_days": 400,
    "ai_jobs_days": 90,
    "deleted_components_days": 30,
    "disk_warn_pct": 85,
}


def _f(key: str, label: str, lo: int, hi: int, section: str, help_: str) -> dict:
    return {"key": key, "label": label, "type": "number", "min": lo, "max": hi, "section": section, "help": help_}


SETTINGS = [
    _f("metrics_raw_days", "Every poll (days)", 7, 365, "Graph data",
       "Full detail, used by graphs up to 7 days."),
    _f("metrics_hourly_days", "Hourly averages (days)", 30, 1825, "Graph data",
       "Min / average / max per hour, used by 30-day graphs."),
    _f("metrics_daily_days", "Daily averages (days)", 90, 3650, "Graph data",
       "Min / average / max per day, used by 1-year graphs."),
    _f("compress_after_days", "Compress after (days)", 1, 90, "Graph data",
       "Older detail is compressed (about a tenth of the space); must be shorter than 'every poll'."),
    _f("syslog_days", "Syslog (days)", 1, 3650, "Logs & events", "Syslog messages from devices."),
    _f("events_days", "Events (days)", 30, 3650, "Logs & events",
       "State changes (alerts and recoveries) and their comments; pinned comments are kept."),
    _f("probe_beats_days", "Probe checks (days)", 7, 730, "Logs & events", "Every probe check (heartbeat bars)."),
    _f("probe_hourly_days", "Probe uptime per hour (days)", 30, 3650, "Logs & events",
       "Used for uptime percentages over long periods."),
    _f("ai_jobs_days", "AI analyses (days)", 7, 3650, "Cleanup",
       "Finished AI jobs; the comments they wrote on events follow the event retention."),
    _f("deleted_components_days", "Removed ports, disks, sensors (days)", 1, 365, "Cleanup",
       "Components no longer found by discovery, with their graphs."),
    _f("disk_warn_pct", "Warn when the disk is fuller than (%)", 50, 99, "Disk", ""),
]

# retention target -> (setting, what it holds)
RETENTION = {
    "metrics": "metrics_raw_days",
    "metrics_hourly": "metrics_hourly_days",
    "metrics_daily": "metrics_daily_days",
    "syslog_messages": "syslog_days",
    "state_changes": "events_days",
    "probe_beats": "probe_beats_days",
    "probe_beats_hourly": "probe_hourly_days",
}
LABELS = {
    "metrics": "Graph data · every poll",
    "metrics_hourly": "Graph data · hourly",
    "metrics_daily": "Graph data · daily",
    "syslog_messages": "Syslog",
    "state_changes": "Events",
    "probe_beats": "Probe checks",
    "probe_beats_hourly": "Probe uptime · hourly",
}


def validate(config: dict[str, Any]) -> None:
    """Cross-field rules the generic min/max checks can't express."""
    c = {**DEFAULTS, **config}
    if not c["metrics_raw_days"] <= c["metrics_hourly_days"] <= c["metrics_daily_days"]:
        raise ValueError("Keep every poll ≤ hourly averages ≤ daily averages")
    if c["compress_after_days"] >= c["metrics_raw_days"]:
        raise ValueError("Compression must start before the detailed data expires")
    if c["probe_beats_days"] > c["probe_hourly_days"]:
        raise ValueError("Probe uptime per hour must be kept at least as long as the probe checks")


def interval_days(days: int) -> timedelta:
    return timedelta(days=int(days))


# --------------------------------------------------------------------------- policies


async def _retention_now(conn) -> dict[str, str]:
    rows = await conn.execute(text(
        "SELECT hypertable_name, config->>'drop_after' FROM timescaledb_information.jobs "
        "WHERE proc_name = 'policy_retention'"))
    out = {name: after for name, after in rows}
    # continuous aggregates are listed by their materialization hypertable: map back to the view name
    views = await conn.execute(text(
        "SELECT view_name, materialization_hypertable_name FROM timescaledb_information.continuous_aggregates"))
    for view, mat in views:
        if mat in out:
            out[view] = out.pop(mat)
    return out


def _days_of(drop_after: str | None) -> int | None:
    """'90 days' / '1 mon' / '1 year' -> days (only what TimescaleDB prints for our intervals)."""
    if not drop_after:
        return None
    parts = drop_after.split()
    try:
        n = int(parts[0])
    except (ValueError, IndexError):
        return None
    unit = parts[1] if len(parts) > 1 else "days"
    return n * (365 if unit.startswith("year") else 30 if unit.startswith("mon") else 1)


async def apply_policies(cfg: dict[str, Any]) -> list[str]:
    """Bring retention and compression policies in line with the settings. Returns what changed."""
    changed: list[str] = []
    async with engine.begin() as conn:
        current = await _retention_now(conn)
        for target, key in RETENTION.items():
            want = int(cfg[key])
            if _days_of(current.get(target)) == want:
                continue
            await conn.execute(text(f"SELECT remove_retention_policy('{target}', if_exists => TRUE)"))
            await conn.execute(text(f"SELECT add_retention_policy('{target}', INTERVAL '{want} days')"))
            changed.append(f"{LABELS[target]}: keep {want} days")

        compressed = await conn.scalar(text(
            "SELECT compression_enabled FROM timescaledb_information.hypertables WHERE hypertable_name = 'metrics'"))
        if not compressed:
            await conn.execute(text(
                "ALTER TABLE metrics SET (timescaledb.compress, timescaledb.compress_segmentby = 'device_id, component_id, name', "
                "timescaledb.compress_orderby = 'time DESC')"))
            changed.append("Graph data: compression enabled")
        after = await conn.scalar(text(
            "SELECT config->>'compress_after' FROM timescaledb_information.jobs "
            "WHERE proc_name = 'policy_compression' AND hypertable_name = 'metrics'"))
        want = int(cfg["compress_after_days"])
        if _days_of(after) != want:
            await conn.execute(text("SELECT remove_compression_policy('metrics', if_exists => TRUE)"))
            await conn.execute(text(f"SELECT add_compression_policy('metrics', INTERVAL '{want} days')"))
            changed.append(f"Graph data: compress after {want} days")
    return changed


async def backfill_rollups() -> list[str]:
    """Fill the rollups from the raw data that already exists (once). Runs outside a transaction, week by week,
    oldest first, so nothing is lost when the detailed retention later gets shorter."""
    done: list[str] = []
    async with engine.connect() as conn:
        conn = await conn.execution_options(isolation_level="AUTOCOMMIT")
        oldest = await conn.scalar(text("SELECT min(time) FROM metrics"))
        if oldest is None:
            return done
        for view in ("metrics_hourly", "metrics_daily"):
            mat = await _mat_table(conn, view)
            if mat is None:
                continue
            bucket = timedelta(hours=1) if view == "metrics_hourly" else timedelta(days=1)
            # Look at the stored rows (a real-time view also shows buckets computed on the fly). The refresh
            # policy fills the last days by itself, so "filled" means: the oldest raw data is covered.
            stored_from = await conn.scalar(text(f"SELECT min(bucket) FROM {mat}"))
            if stored_from is not None and stored_from <= oldest + 2 * bucket:
                continue
            start = oldest.replace(minute=0, second=0, microsecond=0)
            end = stored_from or datetime.now(UTC) - bucket
            t = start
            while end - t >= bucket:  # TimescaleDB rejects a window shorter than one bucket
                step = min(t + timedelta(days=7), end)
                await conn.execute(text(f"CALL refresh_continuous_aggregate('{view}', CAST(:a AS timestamptz), "
                                        "CAST(:b AS timestamptz))"), {"a": t, "b": step})
                t = step
            done.append(f"{view}: filled from {start:%Y-%m-%d}")
    return done


# --------------------------------------------------------------------------- cleanup


async def _mat_table(session, view: str) -> str | None:
    """Schema-qualified materialization hypertable of a continuous aggregate (where its rows are stored)."""
    row = (await session.execute(text(
        "SELECT materialization_hypertable_schema, materialization_hypertable_name "
        "FROM timescaledb_information.continuous_aggregates WHERE view_name = :v"), {"v": view})).first()
    return f'"{row[0]}"."{row[1]}"' if row else None


async def purge(cfg: dict[str, Any]) -> dict[str, int]:
    """Delete what is no longer referenced or is past its time. Returns rows removed per item."""
    out: dict[str, int] = {}
    now = datetime.now(UTC)
    async with SessionLocal() as s:
        # devices deleted from the UI (recorded by the delete endpoint) plus any older leftovers
        gone = {r[0] for r in await s.execute(text("SELECT id FROM deleted_devices"))}
        leftovers = await s.execute(text(
            "SELECT DISTINCT device_id FROM metrics_daily WHERE device_id NOT IN (SELECT id FROM devices)"))
        gone |= {r[0] for r in leftovers}
        gone -= {r[0] for r in await s.execute(text("SELECT id FROM devices WHERE id = ANY(:ids)"), {"ids": list(gone)})}
        if gone:
            ids = {"ids": list(gone)}
            n = 0
            for table in ("metrics", "syslog_messages", "state_changes"):
                n += (await s.execute(text(f"DELETE FROM {table} WHERE device_id = ANY(:ids)"), ids)).rowcount or 0
            for view in ("metrics_hourly", "metrics_daily"):
                if mat := await _mat_table(s, view):
                    n += (await s.execute(text(f"DELETE FROM {mat} WHERE device_id = ANY(:ids)"), ids)).rowcount or 0
            n += (await s.execute(text("DELETE FROM event_comments WHERE device_id = ANY(:ids)"), ids)).rowcount or 0
            await s.execute(text("DELETE FROM deleted_devices WHERE id = ANY(:ids)"), ids)
            out["deleted devices"] = n
        await s.commit()

        n = (await s.execute(text("DELETE FROM probe_beats WHERE probe_id NOT IN (SELECT id FROM probes)"))).rowcount
        out["deleted probes"] = n or 0

        cutoff = now - interval_days(cfg["deleted_components_days"])
        comps = [r[0] for r in await s.execute(text(
            "SELECT id FROM components WHERE deleted AND (last_seen IS NULL OR last_seen < :c)"), {"c": cutoff})]
        if comps:
            ids = {"ids": comps}
            n = (await s.execute(text("DELETE FROM metrics WHERE component_id = ANY(:ids)"), ids)).rowcount or 0
            await s.execute(text("UPDATE services SET component_id = NULL WHERE component_id = ANY(:ids)"), ids)
            n += (await s.execute(text("DELETE FROM components WHERE id = ANY(:ids)"), ids)).rowcount or 0
            out["removed components"] = n
        await s.commit()

        out["AI jobs"] = (await s.execute(text(
            "DELETE FROM ai_jobs WHERE status IN ('done', 'error') AND created_at < :c"),
            {"c": now - interval_days(cfg["ai_jobs_days"])})).rowcount or 0
        out["event comments"] = (await s.execute(text(
            "DELETE FROM event_comments WHERE NOT pinned AND event_time < :c"),
            {"c": now - interval_days(cfg["events_days"])})).rowcount or 0
        await s.commit()
    return {k: v for k, v in out.items() if v}


# --------------------------------------------------------------------------- status


def disk_usage(path: str = "/") -> dict[str, Any]:
    u = shutil.disk_usage(path)
    return {"total": u.total, "used": u.used, "free": u.free, "pct": round(u.used / u.total * 100, 1) if u.total else None}


async def status(session) -> dict[str, Any]:
    _, cfg = await cached_settings(plugin, ttl=0)
    cfg = {**DEFAULTS, **cfg}
    tables = []
    for target, key in RETENTION.items():
        is_view = target in ("metrics_hourly", "metrics_daily", "probe_beats_hourly")
        size_target = await _mat_table(session, target) if is_view else target
        if size_target is None:
            continue
        name = size_target.split(".")[-1].strip('"')
        size = await session.scalar(text("SELECT hypertable_size(CAST(:t AS regclass))"), {"t": size_target})
        oldest_col = "bucket" if is_view else "time"
        oldest = await session.scalar(text(f"SELECT min({oldest_col}) FROM {target}"))
        row = {"key": target, "label": LABELS[target], "days": int(cfg[key]), "size": size or 0,
               "oldest": oldest}
        if target == "metrics":
            stats = (await session.execute(text(
                "SELECT sum(before_compression_total_bytes), sum(after_compression_total_bytes) "
                "FROM hypertable_compression_stats('metrics')"))).first()
            if stats and stats[0]:
                row["compressed"] = {"before": int(stats[0]), "after": int(stats[1] or 0)}
        tables.append({**row, "hypertable": name})
    db_size = await session.scalar(text("SELECT pg_database_size(current_database())"))
    last = None
    try:
        raw = await redis().get(LAST_RUN)
        last = json.loads(raw) if raw else None
    except Exception:
        last = None
    disk = disk_usage()
    return {"settings": cfg, "tables": tables, "database_size": db_size, "disk": disk,
            "disk_warning": disk["pct"] is not None and disk["pct"] >= cfg["disk_warn_pct"], "last_run": last}


# --------------------------------------------------------------------------- service + API


async def run_once(reason: str, do_purge: bool = True) -> dict[str, Any]:
    started = time.monotonic()
    _, cfg = await cached_settings(plugin, ttl=0)
    cfg = {**DEFAULTS, **cfg}
    result: dict[str, Any] = {"time": datetime.now(UTC).isoformat(), "reason": reason}
    try:
        result["backfill"] = await backfill_rollups()  # first: rollups must exist before raw data may expire
        result["policies"] = await apply_policies(cfg)
        if do_purge:
            result["purged"] = await purge(cfg)
        result["ok"] = True
    except Exception as e:
        log.exception("housekeeping failed")
        result["ok"], result["error"] = False, str(e)[:500]
    result["seconds"] = round(time.monotonic() - started, 1)
    try:
        await redis().set(LAST_RUN, json.dumps(result))
    except Exception as e:
        log.warning("housekeeping: could not store the last run: %s", e)
    if result.get("policies") or result.get("purged") or result.get("backfill"):
        log.info("housekeeping (%s): %s", reason, result)
    return result


class HousekeepingService(BackgroundService):
    name = "housekeeping"

    async def run(self, stop: asyncio.Event) -> None:
        await asyncio.sleep(20)  # let the poller start first
        last_cfg: str | None = None
        last_purge = 0.0
        while not stop.is_set():
            enabled, cfg = await cached_settings(plugin, ttl=0)
            if not enabled:  # switched off on the Plugins page: existing policies stay as they are
                await asyncio.sleep(CHECK_EVERY)
                continue
            key = json.dumps({**DEFAULTS, **cfg}, sort_keys=True)
            requested = False
            try:
                requested = bool(await redis().blpop([RUN_QUEUE], timeout=CHECK_EVERY))
            except Exception:
                await asyncio.sleep(CHECK_EVERY)
            due = time.monotonic() - last_purge >= PURGE_EVERY
            if requested or due or key != last_cfg:
                result = await run_once("requested" if requested else "scheduled" if due else "settings changed",
                                        do_purge=requested or due)
                if result.get("ok"):  # on failure: try again at the next check (a minute later)
                    last_cfg = key
                    if requested or due:
                        last_purge = time.monotonic()


router = APIRouter()


@router.get("/status", dependencies=[require(Role.ADMIN)])
async def get_status(session: Session):
    return await status(session)


@router.post("/run", dependencies=[require(Role.ADMIN)])
async def run_now():
    try:
        await redis().rpush(RUN_QUEUE, "1")
    except Exception as e:
        raise HTTPException(503, f"Queue unavailable: {e}") from e
    invalidate(NAME)
    return {"queued": True}


plugin = Plugin(
    name=NAME,
    label="Housekeeping",
    version="1.0.0",
    description="How long graphs, logs and events are kept; compression and cleanup",
    services=[HousekeepingService()],
    router=router,
    builtin=True,
    settings=SETTINGS,
    defaults=DEFAULTS,
    validate=validate,
)
