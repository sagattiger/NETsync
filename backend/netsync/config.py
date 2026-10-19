from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="NETSYNC_", env_file=".env", extra="ignore")

    database_url: str = "postgresql+asyncpg://netsync:netsync@localhost:5432/netsync"
    redis_url: str = "redis://localhost:6379/0"

    secret_key: str = "change-me"
    token_ttl_minutes: int = 60 * 12

    # Cluster: every poller is a node. In single-node mode the panel and the
    # node run together and node_name identifies this instance.
    node_name: str = "local"

    poll_interval: int = 300  # seconds
    discovery_interval: int = 6 * 3600
    poll_concurrency: int = 64
    snmp_timeout: float = 2.0
    snmp_retries: int = 1

    syslog_host: str = "0.0.0.0"
    syslog_port: int = 514

    # Comma separated list of plugin names to disable.
    disabled_plugins: str = ""

    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from: str = "netsync@localhost"

    public_url: str = "http://localhost:8080"


@lru_cache
def get_settings() -> Settings:
    return Settings()
