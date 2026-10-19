"""HOST-RESOURCES-MIB: processors, memory and storage (Linux, Windows, many appliances)."""

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


def human_bytes(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024:
            return f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} PB"


class HostResourcesModule(Module):
    name = "host_resources"
    kinds = ("processor", "storage", "mempool")
    order = 20

    async def discover(self, ctx: DeviceContext):
        specs = []
        for index in await ctx.snmp.walk(HR_PROCESSOR_LOAD):
            specs.append(ComponentSpec("processor", index, f"CPU {len(specs)}"))

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
                result.metrics.append(MetricSample("cpu_util", avg))
                result.checks.append(
                    CheckResult("cpu_util", "CPU utilization", value=avg, unit="%",
                                output=f"{avg:.1f}% average over {len(values)} cores")
                )

        storages = ctx.components("storage") + ctx.components("mempool")
        if storages:
            rows = await ctx.snmp.table({"size": STORAGE_COLS["size"], "used": STORAGE_COLS["used"]})
            for comp in storages:
                r = rows.get(comp.index)
                if not r or not r.get("size"):
                    continue
                units = comp.attrs.get("units", 1)
                size, used = r["size"] * units, r.get("used", 0) * units
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
                                output=f"{pct:.1f}% used ({human_bytes(used)} of {human_bytes(size)})")
                )
        return result
