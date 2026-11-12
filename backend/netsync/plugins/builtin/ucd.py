"""Linux/Unix host details from UCD-SNMP-MIB (net-snmp) and the HOST-RESOURCES system group.

Load averages, detailed memory (used, buffers, cached, shared, available, swap), the CPU time split
(user, system, iowait, irq, steal...), context switches, interrupts, swap and block I/O, running
processes and logged-in users. Everything is a device-level series; one pseudo component keeps the
raw counters between polls so they can be turned into rates.

Optional: a net-snmp ``extend`` named ``netsync-disks`` that prints ``lsblk -dno NAME,MODEL,SIZE``,
a ``---`` line, then ``/proc/swaps``. With it NETsync knows disk models and which disk holds swap
(e.g. an Intel Optane module). See docs/HOST-METRICS.md.
"""

from __future__ import annotations

import re

from netsync.plugins.base import ComponentSpec, DeviceContext, MetricSample, Module, PollResult
from netsync.snmp.client import text

UCD = "1.3.6.1.4.1.2021"
MEM = f"{UCD}.4"
LOAD = f"{UCD}.10.1.3"  # laLoad.1/.2/.3 = 1, 5, 15 minutes (strings)
SS = f"{UCD}.11"
HR_SYSTEM_USERS = "1.3.6.1.2.1.25.1.5.0"
HR_SYSTEM_PROCESSES = "1.3.6.1.2.1.25.1.6.0"
EXTEND_OUTPUT = "1.3.6.1.4.1.8072.1.3.2.3.1.2"  # nsExtendOutputFull, indexed by the extend name
DISKS_EXTEND = "netsync-disks"

KIND, INDEX = "system_stats", "0"

# memory in KB; the X (64-bit) column is preferred, the 32-bit one is the fallback
MEMORY = {
    "swap_total": (18, 3), "swap_avail": (19, 4), "mem_total": (20, 5), "mem_free": (21, 6),
    "mem_shared": (24, 13), "mem_buffers": (25, 14), "mem_cached": (26, 15), "mem_available": (27, None),
}
# raw CPU ticks (ssCpuRaw*) -> share of all ticks between two polls
CPU_RAW = {
    "cpu_user": 50, "cpu_nice": 51, "cpu_system": 52, "cpu_idle": 53, "cpu_wait": 54,
    "cpu_irq": 56, "cpu_softirq": 61, "cpu_steal": 64, "cpu_guest": 65,
}
# counters -> per-second rates
RATES = {
    "interrupts": 59, "ctx_switches": 60, "swap_in": 62, "swap_out": 63,
    "io_sent": 57, "io_received": 58,
}
COUNTER32 = 2**32

OPTANE = re.compile(r"optane|MEMPEK1[JW]|SSDPEK1[AW]|SSDPE[D2]1D|SSDPE21K|SSDPEL1K|SSDPF21Q", re.IGNORECASE)
PARTITION = re.compile(r"^(nvme\d+n\d+|mmcblk\d+)p\d+$|^((?:s|v|xv|h)d[a-z]+)\d+$")


def base_disk(dev: str) -> str:
    """'/dev/nvme0n1p1' -> 'nvme0n1', '/dev/sda2' -> 'sda', 'dm-3' stays 'dm-3'."""
    name = dev.rsplit("/", 1)[-1]
    m = PARTITION.match(name)
    return (m.group(1) or m.group(2)) if m else name


def parse_disks_extend(output: str) -> tuple[dict[str, dict], list[dict]]:
    """Output of the netsync-disks extend -> ({disk: {model, size}}, [{device, disk, kind, size_kb, used_kb}])."""
    disks: dict[str, dict] = {}
    swaps: list[dict] = []
    head, _, tail = (output or "").partition("---")
    for line in head.splitlines():
        parts = line.split()
        if len(parts) >= 2:
            name, size = parts[0], parts[-1] if re.match(r"^[\d.,]+[KMGTP]?$", parts[-1]) else None
            model = " ".join(parts[1:-1] if size else parts[1:]).strip() or None
            disks[name] = {"model": model, "size": size}
    for line in tail.splitlines():
        parts = line.split()
        if len(parts) >= 4 and parts[0].startswith("/") and parts[2].isdigit():
            swaps.append({"device": parts[0], "disk": base_disk(parts[0]), "kind": parts[1],
                          "size_kb": int(parts[2]), "used_kb": int(parts[3]) if parts[3].isdigit() else None})
    return disks, swaps


def swap_summary(disks: dict[str, dict], swaps: list[dict]) -> list[dict]:
    """Swap areas with the model of the disk they live on and an Optane flag."""
    out = []
    for s in swaps:
        model = (disks.get(s["disk"]) or {}).get("model")
        out.append({**s, "model": model, "optane": bool(model and OPTANE.search(model))})
    return out


def as_float(v) -> float | None:
    try:
        return float(text(v) if isinstance(v, bytes) else v)
    except (TypeError, ValueError):
        return None


def counter_delta(cur: float, prev: float) -> float | None:
    """Delta of a Counter32 that may have wrapped once; None on reset."""
    d = cur - prev
    if d >= 0:
        return d
    d += COUNTER32
    return d if 0 <= d < COUNTER32 / 2 else None


def cpu_shares(cur: dict[str, float], prev: dict[str, float]) -> dict[str, float]:
    """Percent of all CPU ticks spent in each state between two polls."""
    deltas = {}
    for k in CPU_RAW:
        if k in cur and k in prev and (d := counter_delta(cur[k], prev[k])) is not None:
            deltas[k] = d
    # guest time is already counted in user time on Linux; don't count it twice
    total = sum(v for k, v in deltas.items() if k != "cpu_guest")
    if total <= 0:
        return {}
    return {k: v / total * 100 for k, v in deltas.items()}


def memory_bytes(raw: dict[str, float]) -> dict[str, float]:
    """KB values -> bytes, plus used (= total - free - buffers - cached, like free(1)) and swap used."""
    kb = {k: v for k, v in raw.items() if v is not None}
    out = {k: v * 1024 for k, v in kb.items() if k != "swap_avail"}
    if {"mem_total", "mem_free"} <= kb.keys():
        used = kb["mem_total"] - kb["mem_free"] - kb.get("mem_buffers", 0) - kb.get("mem_cached", 0)
        out["mem_used"] = max(0.0, used) * 1024
    if {"swap_total", "swap_avail"} <= kb.keys():
        out["swap_used"] = max(0.0, kb["swap_total"] - kb["swap_avail"]) * 1024
    return out


async def read_disks_extend(snmp) -> tuple[dict[str, dict], list[dict]] | None:
    """Disk models and swap areas from the netsync-disks extend, or None when it isn't configured."""
    try:
        ext = await snmp.walk(EXTEND_OUTPUT)
    except Exception:
        return None
    key = ".".join(str(b) for b in [len(DISKS_EXTEND), *DISKS_EXTEND.encode()])
    if key not in ext:
        return None
    disks, swaps = parse_disks_extend(text(ext[key]) or "")
    return disks, swap_summary(disks, swaps)


class UcdModule(Module):
    name = "ucd"
    kinds = (KIND,)
    order = 25

    async def discover(self, ctx: DeviceContext):
        r = await ctx.snmp.get(f"{MEM}.5.0", f"{SS}.50.0", f"{LOAD}.1")
        if all(v is None for v in r.values()):
            return []
        found = await read_disks_extend(ctx.snmp)
        attrs = {"disks": found[0], "swaps": found[1], "extend": True} if found else {"extend": False}
        return [ComponentSpec(KIND, INDEX, "System statistics", attrs=attrs)]

    async def poll(self, ctx: DeviceContext):
        if not ctx.components(KIND):
            return PollResult()
        oids: dict[str, str] = {}
        for name, (x, legacy) in MEMORY.items():
            oids[name] = f"{MEM}.{x}.0"
            if legacy:
                oids[f"{name}#32"] = f"{MEM}.{legacy}.0"
        oids |= {f"load{n}": f"{LOAD}.{i}" for i, n in ((1, 1), (2, 5), (3, 15))}
        oids |= {k: f"{SS}.{n}.0" for k, n in {**CPU_RAW, **RATES}.items()}
        oids |= {"users": HR_SYSTEM_USERS, "processes": HR_SYSTEM_PROCESSES}
        names = list(oids)
        raw: dict = {}
        for i in range(0, len(names), 20):  # keep each GET small
            chunk = names[i:i + 20]
            got = await ctx.snmp.get(*(oids[n] for n in chunk))
            raw |= {n: got.get(oids[n]) for n in chunk}

        mem_kb = {}
        for name in MEMORY:
            v = as_float(raw.get(name))
            if v is None:
                v = as_float(raw.get(f"{name}#32"))
            mem_kb[name] = v
        mem = memory_bytes(mem_kb)

        now = ctx.now.timestamp()
        prev = ctx.previous(KIND, INDEX)
        dt = now - prev.get("ts", 0)
        counters = {k: as_float(raw.get(k)) for k in {**CPU_RAW, **RATES}}
        counters = {k: v for k, v in counters.items() if v is not None}
        fresh = 0 < dt < 3600
        shares = cpu_shares(counters, prev.get("raw", {})) if fresh else {}
        rates = {}
        if fresh:
            for k in RATES:
                if (k in counters and k in prev.get("raw", {})
                        and (d := counter_delta(counters[k], prev["raw"][k])) is not None):
                    rates[k] = d / dt

        gauges = {k: as_float(raw.get(k)) for k in ("load1", "load5", "load15", "users", "processes")}
        gauges = {k: v for k, v in gauges.items() if v is not None}
        result = PollResult()
        result.metrics += [MetricSample(k, v) for k, v in {**mem, **gauges, **shares, **rates}.items()]
        result.values[(KIND, INDEX)] = {"ts": now, "raw": counters, **mem, **gauges,
                                        **{f"{k}_pct": v for k, v in shares.items()},
                                        **{f"{k}_rate": v for k, v in rates.items()}}
        return result
