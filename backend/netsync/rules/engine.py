"""Threshold rules -> service states (CheckMK style).

Rules are evaluated in priority order (lowest first); the first rule matching
check + device/group + item regex wins. If none matches, built-in defaults apply.
"""

import re
import time
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from netsync.models import Device, State, ThresholdRule
from netsync.plugins.base import CheckResult


@dataclass(frozen=True)
class Levels:
    warn: float | None
    crit: float | None
    direction: str = "above"


DEFAULT_LEVELS: dict[str, Levels] = {
    "cpu_util": Levels(80, 90),
    "mem_used": Levels(80, 90),
    "storage_used": Levels(80, 90),
    "if": Levels(80, 95),  # port utilization %
    "ping_rtt": Levels(150, 300),
    "ping_loss": Levels(10, 50),
}


class RuleSet:
    def __init__(self, rules: list[ThresholdRule]):
        self.rules = sorted((r for r in rules if r.enabled), key=lambda r: r.priority)
        self._regex = {r.id: re.compile(r.item_regex) for r in self.rules if r.item_regex}

    def levels(self, check: str, device: Device, item: str) -> Levels | None:
        group_ids = {g.id for g in device.groups}
        for r in self.rules:
            if r.check != check:
                continue
            if r.device_id is not None and r.device_id != device.id:
                continue
            if r.device_group_id is not None and r.device_group_id not in group_ids:
                continue
            if r.id in self._regex and not self._regex[r.id].search(item):
                continue
            return Levels(r.warn, r.crit, r.direction or "above")
        return DEFAULT_LEVELS.get(check)

    def evaluate(self, cr: CheckResult, device: Device) -> tuple[int, str]:
        state = cr.state if cr.state is not None else State.OK
        output = cr.output
        if cr.value is None:
            return state, output
        lv = self.levels(cr.check, device, cr.name)
        if lv:
            above = lv.direction == "above"

            def breached(limit):
                return limit is not None and (cr.value >= limit if above else cr.value <= limit)

            level_state = State.CRIT if breached(lv.crit) else State.WARN if breached(lv.warn) else State.OK
            if level_state > State.OK:
                op = ">=" if above else "<="
                limit = lv.crit if level_state == State.CRIT else lv.warn
                output += f" ({op} {limit:g}{cr.unit} {State(level_state).name})"
            state = max(state, level_state)
        return state, output


_cache: tuple[float, RuleSet] | None = None


async def get_ruleset(session: AsyncSession, ttl: float = 60) -> RuleSet:
    global _cache
    if _cache and time.monotonic() - _cache[0] < ttl:
        return _cache[1]
    rules = list(await session.scalars(select(ThresholdRule)))
    rs = RuleSet(rules)
    _cache = (time.monotonic(), rs)
    return rs


def invalidate() -> None:
    global _cache
    _cache = None
