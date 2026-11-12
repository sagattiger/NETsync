from collections.abc import AsyncIterator

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from netsync.config import get_settings

engine = create_async_engine(get_settings().database_url, pool_pre_ping=True)
SessionLocal = async_sessionmaker(engine, expire_on_commit=False)


async def get_session() -> AsyncIterator[AsyncSession]:
    async with SessionLocal() as session:
        yield session


# Time-series tables become TimescaleDB hypertables. The retention below is only the first-install
# default: the housekeeping plugin (netsync/housekeeping.py) applies the admin's settings afterwards.
HYPERTABLES = {
    "metrics": "90 days",
    "syslog_messages": "90 days",
    "state_changes": "730 days",
    "probe_beats": f"{get_settings().probe_beats_retention_days} days",
}

# Long-term metric history: hourly and daily rollups (real-time, so the newest bucket comes from the raw
# table). Graphs of 30 days read the hourly rollup, 1 year the daily one; raw data can then expire early.
METRICS_HOURLY = """
CREATE MATERIALIZED VIEW IF NOT EXISTS metrics_hourly
WITH (timescaledb.continuous, timescaledb.materialized_only = false) AS
SELECT device_id, component_id, name, time_bucket(INTERVAL '1 hour', time) AS bucket,
       avg(value) AS avg, min(value) AS mn, max(value) AS mx, count(*) AS n
FROM metrics GROUP BY device_id, component_id, name, bucket WITH NO DATA
"""
METRICS_DAILY = """
CREATE MATERIALIZED VIEW IF NOT EXISTS metrics_daily
WITH (timescaledb.continuous, timescaledb.materialized_only = false) AS
SELECT device_id, component_id, name, time_bucket(INTERVAL '1 day', bucket) AS bucket,
       sum(avg * n) / nullif(sum(n), 0) AS avg, min(mn) AS mn, max(mx) AS mx, sum(n) AS n
FROM metrics_hourly GROUP BY device_id, component_id, name, time_bucket(INTERVAL '1 day', bucket) WITH NO DATA
"""
# (view, start_offset, end_offset, schedule): the refresh window always stays inside the raw retention
ROLLUP_POLICIES = (
    ("metrics_hourly", "3 days", "1 hour", "30 minutes"),
    ("metrics_daily", "7 days", "1 day", "6 hours"),
)

# Idempotent statements run after the column additions (type widening, indexes).
SCHEMA_STATEMENTS = [
    # widen probes.target once (a no-op ALTER would still lock the table at every start)
    """DO $$ BEGIN
         IF (SELECT character_maximum_length FROM information_schema.columns
             WHERE table_schema = current_schema() AND table_name = 'probes' AND column_name = 'target') < 2048 THEN
           ALTER TABLE probes ALTER COLUMN target TYPE VARCHAR(2048);
         END IF;
       END $$""",
    "CREATE INDEX IF NOT EXISTS ix_probes_push_token_hash ON probes (push_token_hash)",
]

# Hourly uptime rollup of probe_beats. Real-time: the newest hour is read from the raw table.
PROBE_HOURLY = """
CREATE MATERIALIZED VIEW IF NOT EXISTS probe_beats_hourly
WITH (timescaledb.continuous, timescaledb.materialized_only = false) AS
SELECT probe_id, time_bucket(INTERVAL '1 hour', time) AS bucket,
       sum(CASE WHEN NOT maintenance THEN 1 ELSE 0 END) AS total,
       sum(CASE WHEN NOT maintenance AND state <> 2 THEN 1 ELSE 0 END) AS up,
       sum(CASE WHEN NOT maintenance AND state <> 2 AND response_ms IS NOT NULL THEN response_ms ELSE 0 END) AS ms_sum,
       sum(CASE WHEN NOT maintenance AND state <> 2 AND response_ms IS NOT NULL THEN 1 ELSE 0 END) AS ms_n
FROM probe_beats GROUP BY probe_id, bucket WITH NO DATA
"""


# Columns added after a table first shipped. create_all() never alters existing tables,
# so these are applied idempotently on startup until proper Alembic migrations land.
ADDED_COLUMNS = {
    "probes": [
        "port INTEGER",
        "config JSON NOT NULL DEFAULT '{}'",
        "secrets_enc TEXT",
        "timeout_s INTEGER NOT NULL DEFAULT 10",
        "retries INTEGER NOT NULL DEFAULT 1",
        "retry_interval_s INTEGER",
        "upside_down BOOLEAN NOT NULL DEFAULT false",
        "resend_every INTEGER NOT NULL DEFAULT 0",
        "tags JSON NOT NULL DEFAULT '[]'",
        "description TEXT",
        "next_run TIMESTAMPTZ",
        "fail_count INTEGER NOT NULL DEFAULT 0",
        "last_state SMALLINT",
        "last_message VARCHAR(200)",
        "last_response_ms DOUBLE PRECISION",
        "cert JSON",
        "push_token_hash VARCHAR(64)",
        "last_push_at TIMESTAMPTZ",
    ],
    "dashboards": [
        "public BOOLEAN NOT NULL DEFAULT false",
        "public_name VARCHAR(128)",
    ],
    "event_comments": [
        "ai BOOLEAN NOT NULL DEFAULT false",
    ],
    "device_groups": [
        "terminal_access VARCHAR(8) NOT NULL DEFAULT 'none'",
    ],
    "remote_plugins": [
        "store JSON",
    ],
    "terminal_sessions": [
        "via VARCHAR(8) NOT NULL DEFAULT 'web'",
    ],
    "api_tokens": [
        "kind VARCHAR(16) NOT NULL DEFAULT 'public'",  # public (dashboards API) | mcp (tool hub)
        "scopes JSON NOT NULL DEFAULT '{}'",  # mcp: {"tools": ["netsync__*"], "write": false}
    ],
    "devices": [
        "ip_addresses JSON NOT NULL DEFAULT '[]'",
        "virtualization VARCHAR(16)",
        "kernel VARCHAR(64)",
    ],
    "users": [
        "full_name VARCHAR(128)",
        "phone VARCHAR(64)",
        "job_title VARCHAR(128)",
        "timezone VARCHAR(64)",
        "preferences JSON NOT NULL DEFAULT '{}'",
        "avatar BYTEA",
        "avatar_mime VARCHAR(32)",
        "avatar_version INTEGER NOT NULL DEFAULT 0",
        "last_login TIMESTAMPTZ",
        "password_changed_at TIMESTAMPTZ",
    ],
}


async def init_db() -> None:
    """Create tables and TimescaleDB hypertables. Safe to run repeatedly."""
    from netsync.models import Base

    async with engine.begin() as conn:
        # API and worker start together; serialize schema creation.
        await conn.execute(text("SELECT pg_advisory_xact_lock(7061)"))
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS timescaledb"))
        await conn.run_sync(Base.metadata.create_all)
        # ALTER TABLE locks the table even when the column exists, which deadlocks with the other process's
        # queries at startup: only alter tables that really miss a column.
        existing = {(t, c) for t, c in (await conn.execute(text(
            "SELECT table_name, column_name FROM information_schema.columns WHERE table_schema = current_schema()"))).all()}
        for table, columns in ADDED_COLUMNS.items():
            for column in columns:
                if (table, column.split()[0]) not in existing:
                    await conn.execute(text(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {column}"))
        for stmt in SCHEMA_STATEMENTS:
            await conn.execute(text(stmt))
        for table, retention in HYPERTABLES.items():
            await conn.execute(
                text(f"SELECT create_hypertable('{table}', 'time', if_not_exists => TRUE, migrate_data => TRUE)")
            )
            await conn.execute(
                text(f"SELECT add_retention_policy('{table}', INTERVAL '{retention}', if_not_exists => TRUE)")
            )
        await conn.execute(text(PROBE_HOURLY))
        await conn.execute(text(
            "SELECT add_continuous_aggregate_policy('probe_beats_hourly', start_offset => INTERVAL '3 days', "
            "end_offset => INTERVAL '1 hour', schedule_interval => INTERVAL '30 minutes', if_not_exists => TRUE)"
        ))
        await conn.execute(text(
            "SELECT add_retention_policy('probe_beats_hourly', INTERVAL '400 days', if_not_exists => TRUE)"
        ))
        await conn.execute(text(METRICS_HOURLY))
        await conn.execute(text(METRICS_DAILY))
        for view, start, end, every in ROLLUP_POLICIES:
            await conn.execute(text(
                f"SELECT add_continuous_aggregate_policy('{view}', start_offset => INTERVAL '{start}', "
                f"end_offset => INTERVAL '{end}', schedule_interval => INTERVAL '{every}', if_not_exists => TRUE)"
            ))
        await conn.execute(text(
            "CREATE TABLE IF NOT EXISTS deleted_devices (id INTEGER PRIMARY KEY, deleted_at TIMESTAMPTZ NOT NULL DEFAULT now())"
        ))
