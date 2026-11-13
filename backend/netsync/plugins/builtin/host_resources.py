"""HOST-RESOURCES-MIB: processors, memory and storage (Linux, Windows, many appliances)."""

import re

from netsync.plugins.base import (
    CheckResult,
    ComponentSpec,
    DeviceContext,
    MetricSample,
    Module,
    PollResult,
)
from netsync.snmp.client import text

HR_PROCESSOR_LOAD = "1.3.6.1.2.1.25.3.3.1.2"
HR_DEVICE_DESCR = "1.3.6.1.2.1.25.3.2.1.3"  # same index as hrProcessorTable
HR_DEVICE_TYPE = "1.3.6.1.2.1.25.3.2.1.2"
HR_DEVICE_PROCESSOR = "1.3.6.1.2.1.25.3.1.3"
HR_STORAGE = "1.3.6.1.2.1.25.2.3.1"
STORAGE_COLS = {
    "type": f"{HR_STORAGE}.2",
    "descr": f"{HR_STORAGE}.3",
    "units": f"{HR_STORAGE}.4",
    "size": f"{HR_STORAGE}.5",
    "used": f"{HR_STORAGE}.6",
}
HR_TYPE = "1.3.6.1.2.1.25.2.1"
TYPE_RAM = f"{HR_TYPE}.2"
TYPE_FIXED_DISK = f"{HR_TYPE}.4"
TYPE_NETWORK_DISK = f"{HR_TYPE}.10"

# Pseudo filesystems that just add noise.
SKIP_MOUNTS = ("/proc", "/sys", "/dev", "/run", "/snap")


def cpu_model(descr: str | None) -> str | None:
    """'GenuineIntel: Intel(R) Xeon(R) CPU E5-2697 v2 @ 2.70GHz' -> 'Intel Xeon E5-2697 v2 @ 2.70GHz'."""
    if not descr:
        return None
    s = re.sub(r"^(GenuineIntel|AuthenticAMD|CentaurHauls|HygonGenuine):\s*", "", descr.strip())
    s = re.sub(r"\((?:R|TM|tm)\)", "", s)
    s = re.sub(r"\bCPU\b\s*", "", s)
    s = re.sub(r"\s+(?:\d+-Core|Processor)\b", "", s)
    return re.sub(r"\s{2,}", " ", s).strip() or None


def human_bytes(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024:
            return f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} PB"


async def linux_memory(snmp) -> dict[str, float] | None:
    """RAM from UCD-SNMP-MIB in bytes, with mem_used = total - free - buffers - cache (None without the MIB)."""
    from netsync.plugins.builtin.ucd import MEM, MEMORY, as_float, memory_bytes

    want = ("mem_total", "mem_free", "mem_buffers", "mem_cached")
    oids = {}
    for name in want:
        x, legacy = MEMORY[name]
        oids[name], oids[name + "#32"] = f"{MEM}.{x}.0", f"{MEM}.{legacy}.0"
    try:
        got = await snmp.get(*oids.values())
    except Exception:  # noqa: BLE001 - agents without UCD
        return None
    kb = {n: as_float(got.get(oids[n])) if as_float(got.get(oids[n])) is not None else as_float(got.get(oids[n + "#32"]))
          for n in want}
    if not kb.get("mem_total") or kb.get("mem_free") is None:
        return None
    mem = memory_bytes(kb)
    return mem if mem.get("mem_total") and "mem_used" in mem else None


class HostResourcesModule(Module):
    name = "host_resources"
    kinds = ("processor", "storage", "mempool")
    order = 20

    async def discover(self, ctx: DeviceContext):
        specs = []
        loads = await ctx.snmp.walk(HR_PROCESSOR_LOAD)
        try:
            types = await ctx.snmp.walk(HR_DEVICE_TYPE)
            descrs = await ctx.snmp.walk(HR_DEVICE_DESCR)
        except Exception:
            types, descrs = {}, {}
        # net-snmp leaves hrProcessorLoad empty for about a minute after it starts: the device table lists the
        # processors straight away, so use it (and the load table as a fallback for agents without it)
        cpu_indexes = [i for i, t in types.items() if str(t).strip(".") == HR_DEVICE_PROCESSOR] or list(loads)
        cpu_indexes.sort(key=lambda i: int(i) if str(i).isdigit() else 0)
        for index in cpu_indexes:
            model = cpu_model(text(descrs.get(index)))
            specs.append(ComponentSpec("processor", index, f"CPU {len(specs)}", descr=model,
                                       attrs={"model": model} if model else {}))

        rows = [(index, r, text(r.get("descr")) or index) for index, r in (await ctx.snmp.table(STORAGE_COLS)).items()]
        # Shortest mount path first, so "/" wins over bind mounts of the same filesystem.
        rows.sort(key=lambda x: len(x[2]))
        seen_fs: set[tuple[int, int]] = set()
        for index, r, descr in rows:
            if not r.get("size"):
                continue
            if r.get("type") == TYPE_RAM:
                specs.append(ComponentSpec("mempool", index, "Memory", attrs={"units": r.get("units", 1)}))
            elif r.get("type") in (TYPE_FIXED_DISK, TYPE_NETWORK_DISK) and not descr.startswith(SKIP_MOUNTS):
                # Bind mounts (chroot jails, container volumes) report the exact same size/used
                # as the filesystem they come from - monitor that filesystem only once.
                fs_key = (r["size"] * r.get("units", 1), r.get("used", 0) * r.get("units", 1))
                if fs_key in seen_fs:
                    continue
                seen_fs.add(fs_key)
                specs.append(ComponentSpec("storage", index, descr, attrs={"units": r.get("units", 1)}))
        return specs

    async def poll(self, ctx: DeviceContext):
        result = PollResult()

        cpus = ctx.components("processor")
        if cpus:
            loads = await ctx.snmp.walk(HR_PROCESSOR_LOAD)
            values = []
            for cpu in cpus:
                if (load := loads.get(cpu.index)) is not None:
                    values.append(load)
                    result.metrics.append(MetricSample("load", load, "processor", cpu.index))
                    result.values[("processor", cpu.index)] = {"load": load}
            if values:
                avg = sum(values) / len(values)
                result.metrics += [MetricSample("cpu_util", avg), MetricSample("cpu_count", len(values))]
                result.checks.append(
                    CheckResult("cpu_util", "CPU utilization", value=avg, unit="%",
                                output=f"{avg:.1f}% average over {len(values)} cores")
                )

        storages = ctx.components("storage") + ctx.components("mempool")
        if storages:
            rows = await ctx.snmp.table({"size": STORAGE_COLS["size"], "used": STORAGE_COLS["used"]})
            # hrStorage counts the page cache and buffers as used RAM; Linux hands them back whenever a program
            # needs memory, so the memory check uses what free(1) calls used (UCD-SNMP-MIB) when it can
            real = await linux_memory(ctx.snmp) if ctx.components("mempool") else None
            for comp in storages:
                r = rows.get(comp.index)
                if not r or not r.get("size"):
                    continue
                units = comp.attrs.get("units", 1)
                size, used = r["size"] * units, r.get("used", 0) * units
                extra = ""
                if comp.kind == "mempool" and real:
                    size, used = real["mem_total"], real["mem_used"]
                    cache = real.get("mem_buffers", 0) + real.get("mem_cached", 0)
                    extra = f"; {human_bytes(cache)} cache and buffers not counted" if cache else ""
                pct = used / size * 100
                result.values[(comp.kind, comp.index)] = {"size": size, "used": used, "pct": pct}
                result.metrics += [
                    MetricSample("used_pct", pct, comp.kind, comp.index),
                    MetricSample("used_bytes", used, comp.kind, comp.index),
                ]
                check = "mem_used" if comp.kind == "mempool" else "storage_used"
                name = "Memory" if comp.kind == "mempool" else f"Filesystem {comp.name}"
                result.checks.append(
                    CheckResult(check, name, value=pct, unit="%", kind=comp.kind, index=comp.index,
                                output=f"{pct:.1f}% used ({human_bytes(used)} of {human_bytes(size)}{extra})")
                )
        return result
