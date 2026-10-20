"""Per-plugin settings stored in the plugin_settings table, merged over the plugin's defaults."""

import time
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from netsync.db import SessionLocal
from netsync.models import PluginSetting
from netsync.plugins.base import Plugin

MASK = "********"

_cache: dict[str, tuple[float, bool, dict]] = {}


async def get_settings(session: AsyncSession, plugin: Plugin) -> tuple[bool, dict[str, Any]]:
    row = await session.get(PluginSetting, plugin.name)
    enabled = row.enabled if row else plugin.enabled_by_default
    return enabled, {**plugin.defaults, **((row.config if row else None) or {})}


async def cached_settings(plugin: Plugin, ttl: float = 15) -> tuple[bool, dict[str, Any]]:
    """For hot paths (hooks, worker loops): read at most every ``ttl`` seconds."""
    hit = _cache.get(plugin.name)
    if hit and time.monotonic() - hit[0] < ttl:
        return hit[1], hit[2]
    async with SessionLocal() as s:
        enabled, config = await get_settings(s, plugin)
    _cache[plugin.name] = (time.monotonic(), enabled, config)
    return enabled, config


def invalidate(name: str) -> None:
    _cache.pop(name, None)


def coerce(plugin: Plugin, incoming: dict[str, Any], current: dict[str, Any]) -> dict[str, Any]:
    """Validate/convert submitted values by field type; masked secrets keep their stored value."""
    out = dict(current)
    for f in plugin.settings:
        key, kind = f["key"], f.get("type", "text")
        if key not in incoming:
            continue
        value = incoming[key]
        if kind == "secret" and value == MASK:
            continue
        if kind == "bool":
            value = bool(value)
        elif kind == "number":
            try:
                value = float(value)
            except (TypeError, ValueError) as e:
                raise ValueError(f"{f['label']} must be a number") from e
            if "min" in f and value < f["min"] or "max" in f and value > f["max"]:
                raise ValueError(f"{f['label']} must be between {f.get('min')} and {f.get('max')}")
            value = int(value) if value.is_integer() and not f.get("float") else value
        elif kind == "select":
            allowed = [str(o[0]) for o in f.get("options", [])]
            if str(value) not in allowed:
                raise ValueError(f"Invalid value for {f['label']}")
            value = str(value)
        else:
            value = "" if value is None else str(value)
        out[key] = value
    return out


def masked(plugin: Plugin, config: dict[str, Any]) -> dict[str, Any]:
    secrets = {f["key"] for f in plugin.settings if f.get("type") == "secret"}
    return {k: (MASK if k in secrets and v else v) for k, v in config.items()}
