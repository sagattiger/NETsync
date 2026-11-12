"""UCD-DISKIO-MIB: read/write throughput and operations of whole disks (partitions, loop and
device-mapper devices are left out). Disk models and the swap location come from the optional
``netsync-disks`` extend (see plugins/builtin/ucd.py)."""

from __future__ import annotations

import re

from netsync.plugins.base import ComponentSpec, DeviceContext, MetricSample, Module, PollResult
from netsync.plugins.builtin.ucd import OPTANE, read_disks_extend
from netsync.snmp.client import text

DISKIO = "1.3.6.1.4.1.2021.13.15.1.1"
COLS = {"read_bytes": 12, "write_bytes": 13, "reads": 5, "writes": 6}  # NReadX, NWrittenX (64-bit), Reads, Writes
COLS_32 = {"read_bytes": 3, "write_bytes": 4}
WHOLE_DISK = re.compile(r"^(?:(?:s|v|xv|h)d[a-z]+|nvme\d+n\d+|mmcblk\d+)$")
COUNTER32 = 2**32


class DiskIoModule(Module):
    name = "diskio"
    kinds = ("disk",)
    order = 45

    async def discover(self, ctx: DeviceContext):
        names = {i: text(v) or i for i, v in (await ctx.snmp.walk(f"{DISKIO}.2")).items()}
        if not names:
            return []
        models, swaps = await read_disks_extend(ctx.snmp) or ({}, [])
        swap_disks = {s["disk"] for s in swaps}
        specs = []
        for index, name in names.items():
            if not WHOLE_DISK.match(name):
                continue
            model = (models.get(name) or {}).get("model")
            specs.append(ComponentSpec("disk", index, name, descr=model, attrs={
                "model": model, "size": (models.get(name) or {}).get("size"),
                "swap": name in swap_disks, "optane": bool(model and OPTANE.search(model)),
            }))
        return specs

    async def poll(self, ctx: DeviceContext):
        disks = ctx.components("disk")
        if not disks:
            return PollResult()
        cols = {k: f"{DISKIO}.{n}" for k, n in COLS.items()}
        rows = await ctx.snmp.table(cols)
        wide = any("read_bytes" in r for r in rows.values())
        if not wide:
            for idx, r in (await ctx.snmp.table({k: f"{DISKIO}.{n}" for k, n in COLS_32.items()})).items():
                rows.setdefault(idx, {}).update(r)
        now = ctx.now.timestamp()
        result = PollResult()
        for d in disks:
            r = rows.get(d.index)
            if not r:
                continue
            prev = ctx.previous("disk", d.index)
            dt = now - prev.get("ts", 0)
            values = {"ts": now, **{k: r[k] for k in COLS if k in r}}
            if 0 < dt < 3600:
                for k, metric in (("read_bytes", "read_bps"), ("write_bytes", "write_bps"),
                                  ("reads", "read_iops"), ("writes", "write_iops")):
                    if k in r and k in prev:
                        delta = r[k] - prev[k]
                        if delta < 0 and (k in ("reads", "writes") or not wide):
                            delta += COUNTER32  # 32-bit wrap
                        if delta >= 0:
                            values[metric] = delta / dt
                            result.metrics.append(MetricSample(metric, delta / dt, "disk", d.index))
            result.values[("disk", d.index)] = values
        return result
