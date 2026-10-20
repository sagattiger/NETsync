from collections.abc import AsyncIterator

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from netsync.config import get_settings

engine = create_async_engine(get_settings().database_url, pool_pre_ping=True)
SessionLocal = async_sessionmaker(engine, expire_on_commit=False)


async def get_session() -> AsyncIterator[AsyncSession]:
    async with SessionLocal() as session:
        yield session


# Time-series tables become TimescaleDB hypertables with retention policies.
HYPERTABLES = {
    "metrics": "90 days",
    "syslog_messages": "30 days",
    "state_changes": "365 days",
}


# Columns added after a table first shipped. create_all() never alters existing tables,
# so these are applied idempotently on startup until proper Alembic migrations land.
ADDED_COLUMNS = {
    "event_comments": [
        "ai BOOLEAN NOT NULL DEFAULT false",
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
        for table, columns in ADDED_COLUMNS.items():
            for column in columns:
                await conn.execute(text(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {column}"))
        for table, retention in HYPERTABLES.items():
            await conn.execute(
                text(f"SELECT create_hypertable('{table}', 'time', if_not_exists => TRUE, migrate_data => TRUE)")
            )
            await conn.execute(
                text(f"SELECT add_retention_policy('{table}', INTERVAL '{retention}', if_not_exists => TRUE)")
            )
