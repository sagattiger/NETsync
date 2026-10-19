"""IF-MIB / IF-MIB ifXTable: ports, traffic, errors, link state."""

from netsync.models import State
from netsync.plugins.base import (
    CheckResult,
    ComponentSpec,
    DeviceContext,
    MetricSample,
    Module,
    PollResult,
)
from netsync.snmp.client import mac, text

IF = "1.3.6.1.2.1.2.2.1"
IFX = "1.3.6.1.2.1.31.1.1.1"

DISCOVER_COLS = {
    "descr": f"{IF}.2",
    "type": f"{IF}.3",
    "speed": f"{IF}.5",
    "mac": f"{IF}.6",
    "admin": f"{IF}.7",
    "oper": f"{IF}.8",
    "name": f"{IFX}.1",
    "high_speed": f"{IFX}.15",
    "alias": f"{IFX}.18",
}

POLL_COLS = {
    "admin": f"{IF}.7",
    "oper": f"{IF}.8",
    "in_octets": f"{IFX}.6",  # ifHCInOctets
    "out_octets": f"{IFX}.10",  # ifHCOutOctets
    "in_errors": f"{IF}.14",
    "out_errors": f"{IF}.20",
    "in_discards": f"{IF}.13",
    "out_discards": f"{IF}.19",
}
POLL_COLS_32 = {"in_octets": f"{IF}.10", "out_octets": f"{IF}.16"}

OPER_STATUS = {1: "up", 2: "down", 3: "testing", 4: "unknown", 5: "dormant", 6: "notPresent", 7: "lowerLayerDown"}

# ifTypes we skip by default (loopbacks, null, sub-layers that are noise).
SKIP_TYPES = {24, 1}  # softwareLoopback, other

COUNTERS = ("in_octets", "out_octets", "in_errors", "out_errors", "in_discards", "out_discards")


def human_bps(bps: float) -> str:
    for unit in ("bps", "Kbps", "Mbps", "Gbps", "Tbps"):
        if bps < 1000:
            return f"{bps:.1f} {unit}"
        bps /= 1000
    return f"{bps:.1f} Pbps"


class InterfacesModule(Module):
    name = "interfaces"
    kinds = ("port",)
    order = 10

    async def discover(self, ctx: DeviceContext):
        rows = await ctx.snmp.table(DISCOVER_COLS)
        specs = []
        for index, r in rows.items():
            if r.get("type") in SKIP_TYPES:
                continue
            speed = (r.get("high_speed") or 0) * 1_000_000 or r.get("speed") or 0
            name = text(r.get("name")) or text(r.get("descr")) or f"if{index}"
            specs.append(
                ComponentSpec(
                    kind="port",
                    index=index,
                    name=name,
                    descr=text(r.get("alias")) or None,
                    attrs={
                        "if_descr": text(r.get("descr")),
                        "if_type": r.get("type"),
                        "speed": speed,
                        "mac": mac(r.get("mac")),
                        # Like CheckMK: only ports that are up at discovery get a service.
                        "monitor": r.get("oper") == 1,
                    },
                )
            )
        return specs

    async def poll(self, ctx: DeviceContext):
        ports = ctx.components("port")
        if not ports:
            return PollResult()
        rows = await ctx.snmp.table(POLL_COLS)
        if not any("in_octets" in r for r in rows.values()):
            rows32 = await ctx.snmp.table(POLL_COLS_32)
            for idx, r in rows32.items():
                rows.setdefault(idx, {}).update(r)

        now = ctx.now.timestamp()
        result = PollResult()
        for port in ports:
            r = rows.get(port.index)
            if not r:
                continue
            prev = ctx.previous("port", port.index)
            dt = now - prev.get("ts", 0)
            values: dict = {"ts": now, "admin": r.get("admin"), "oper": r.get("oper")}
            rates: dict[str, float] = {}
            for c in COUNTERS:
                if c not in r:
                    continue
                values[c] = r[c]
                if c in prev and 0 < dt < 3600 and r[c] >= prev[c]:
                    rates[c] = (r[c] - prev[c]) / dt
            in_bps = rates.get("in_octets", 0) * 8
            out_bps = rates.get("out_octets", 0) * 8
            speed = port.attrs.get("speed") or 0
            util = max(in_bps, out_bps) / speed * 100 if speed else None
            values.update(in_bps=in_bps, out_bps=out_bps, util=util)
            result.values[("port", port.index)] = values

            if "in_octets" in rates:
                result.metrics += [
                    MetricSample("in_bps", in_bps, "port", port.index),
                    MetricSample("out_bps", out_bps, "port", port.index),
                ]
                for c in ("in_errors", "out_errors", "in_discards", "out_discards"):
                    if c in rates:
                        result.metrics.append(MetricSample(c, rates[c], "port", port.index))

            if not port.attrs.get("monitor"):
                continue
            admin, oper = r.get("admin"), r.get("oper")
            if admin == 2:
                state, status = State.OK, "admin down"
            elif oper == 1:
                state, status = State.OK, "up"
            else:
                state, status = State.CRIT, OPER_STATUS.get(oper, str(oper))
            output = f"{status}, in {human_bps(in_bps)}, out {human_bps(out_bps)}"
            if speed:
                output += f", speed {human_bps(speed)}"
            result.checks.append(
                CheckResult(
                    check="if",
                    name=f"Interface {port.name}",
                    state=state,
                    value=util,
                    unit="%",
                    output=output,
                    kind="port",
                    index=port.index,
                    perf={"in_bps": in_bps, "out_bps": out_bps},
                )
            )
        return result
