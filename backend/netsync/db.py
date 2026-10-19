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


async def init_db() -> None:
    """Create tables and TimescaleDB hypertables. Safe to run repeatedly."""
    from netsync.models import Base

    async with engine.begin() as conn:
        # API and worker start together; serialize schema creation.
        await conn.execute(text("SELECT pg_advisory_xact_lock(7061)"))
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS timescaledb"))
        await conn.run_sync(Base.metadata.create_all)
        for table, retention in HYPERTABLES.items():
            await conn.execute(
                text(f"SELECT create_hypertable('{table}', 'time', if_not_exists => TRUE, migrate_data => TRUE)")
            )
            await conn.execute(
                text(f"SELECT add_retention_policy('{table}', INTERVAL '{retention}', if_not_exists => TRUE)")
            )
