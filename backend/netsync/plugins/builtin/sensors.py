"""LM-SENSORS-MIB (net-snmp on Linux): temperatures and fan speeds.

lm-sensors often lists the same chip reading twice, once as "Other Fan" and once prefixed with the
chip ("dell_smm-isa-00de:Other Fan"); the prefixed duplicate is skipped. CPU package/core sensors
are grouped under "CPU <package>".
"""

from __future__ import annotations

import re

from netsync.plugins.base import CheckResult, ComponentSpec, DeviceContext, MetricSample, Module, PollResult
from netsync.snmp.client import text

LM = "1.3.6.1.4.1.2021.13.16"
TABLES = {"temperature": f"{LM}.2.1", "fan": f"{LM}.3.1", "voltage": f"{LM}.4.1"}
# column 2 = name, 3 = value (temperature in milli-degrees C, fan in RPM, voltage in mV)
SCALE = {"temperature": 1000.0, "fan": 1.0, "voltage": 1000.0}
UNIT = {"temperature": "°C", "fan": " RPM", "voltage": " V"}

CORE = re.compile(r"^(?:Core|Package id) (\d+)$")


def sensor_index(cls: str, index: str) -> str:
    return f"{cls}.{index}"


def plan_sensors(cls: str, names: dict[str, str]) -> list[tuple[str, str, str]]:
    """[(index, name, group)] without chip-prefixed duplicates."""
    plain = {n for n in names.values() if ":" not in n}
    out = []
    for index, name in names.items():
        if ":" in name and name.split(":", 1)[1] in plain:
            continue
        group = "Processor" if cls == "temperature" and CORE.match(name) else "Board"
        out.append((index, name, group))
    return out


def physical_cores(names: list[str]) -> int:
    """Core temperature sensors count physical cores (hyper-threads share one)."""
    return sum(1 for n in names if n.startswith("Core "))


class SensorsModule(Module):
    name = "sensors"
    kinds = ("sensor",)
    order = 40

    async def discover(self, ctx: DeviceContext):
        specs = []
        for cls, base in TABLES.items():
            try:
                names = {i: text(v) or i for i, v in (await ctx.snmp.walk(f"{base}.2")).items()}
            except Exception:
                continue
            for index, name, group in plan_sensors(cls, names):
                specs.append(ComponentSpec("sensor", sensor_index(cls, index), name,
                                           attrs={"class": cls, "group": group, "oid_index": index}))
        return specs

    async def poll(self, ctx: DeviceContext):
        sensors = ctx.components("sensor")
        if not sensors:
            return PollResult()
        result = PollResult()
        for cls, base in TABLES.items():
            mine = [s for s in sensors if s.attrs.get("class") == cls]
            if not mine:
                continue
            values = await ctx.snmp.walk(f"{base}.3")
            for s in mine:
                raw = values.get(s.attrs.get("oid_index"))
                if raw is None:
                    continue
                v = float(raw) / SCALE[cls]
                result.values[("sensor", s.index)] = {"value": v}
                result.metrics.append(MetricSample("value", v, "sensor", s.index))
                if cls == "temperature":
                    result.checks.append(CheckResult("temperature", f"Temperature {s.name}", value=v, unit="°C",
                                                     kind="sensor", index=s.index, output=f"{v:.1f}°C"))
                elif cls == "fan":
                    result.checks.append(CheckResult("fan", f"Fan {s.name}", value=v, unit="RPM",
                                                     kind="sensor", index=s.index, output=f"{v:.0f} RPM"))
        return result
