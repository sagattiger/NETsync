"""IF-MIB / IF-MIB ifXTable: ports, traffic, errors, link state; IP-MIB: the addresses on each port."""

import ipaddress
import logging

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

log = logging.getLogger(__name__)

IF = "1.3.6.1.2.1.2.2.1"
IP_ADDRESS_IFINDEX = "1.3.6.1.2.1.4.34.1.3"  # IP-MIB ipAddressIfIndex (IPv4 and IPv6)
IP_AD_ENT_IFINDEX = "1.3.6.1.2.1.4.20.1.2"  # older ipAddrTable (IPv4 only)
IP_AD_ENT_NETMASK = "1.3.6.1.2.1.4.20.1.3"
IFX = "1.3.6.1.2.1.31.1.1.1"

DISCOVER_COLS = {
    "descr": f"{IF}.2",
    "type": f"{IF}.3",
    "mtu": f"{IF}.4",
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
    "in_ucast": f"{IFX}.7",  # ifHCInUcastPkts
    "in_mcast": f"{IFX}.8",
    "in_bcast": f"{IFX}.9",
    "out_ucast": f"{IFX}.11",
    "out_mcast": f"{IFX}.12",
    "out_bcast": f"{IFX}.13",
}
POLL_COLS_32 = {"in_octets": f"{IF}.10", "out_octets": f"{IF}.16"}

OPER_STATUS = {1: "up", 2: "down", 3: "testing", 4: "unknown", 5: "dormant", 6: "notPresent", 7: "lowerLayerDown"}

# ifTypes we skip by default (loopbacks, null, sub-layers that are noise).
SKIP_TYPES = {24, 1}  # softwareLoopback, other

COUNTERS = ("in_octets", "out_octets", "in_errors", "out_errors", "in_discards", "out_discards",
            "in_ucast", "in_mcast", "in_bcast", "out_ucast", "out_mcast", "out_bcast")


def packet_metrics(rates: dict[str, float]) -> dict[str, float]:
    """Unicast / non-unicast packets per second and the average packet size (bytes) per direction."""
    out: dict[str, float] = {}
    for d in ("in", "out"):
        if f"{d}_ucast" not in rates:
            continue
        ucast = rates[f"{d}_ucast"]
        nucast = rates.get(f"{d}_mcast", 0.0) + rates.get(f"{d}_bcast", 0.0)
        out[f"{d}_ucast_pps"] = ucast
        out[f"{d}_nucast_pps"] = nucast
        if (pkts := ucast + nucast) > 0 and f"{d}_octets" in rates:
            out[f"{d}_pkt_size"] = rates[f"{d}_octets"] / pkts
    return out


def parse_ip_index(suffix: str) -> str | None:
    """ipAddressTable index "<type>.<len>.<octets>" (1 = IPv4, 2 = IPv6, 3/4 = with zone) to an address."""
    parts = suffix.split(".")
    try:
        kind, length = int(parts[0]), int(parts[1])
        octets = bytes(int(x) for x in parts[2:2 + length])
    except (ValueError, IndexError):
        return None
    if kind in (1, 3) and len(octets) >= 4:
        return str(ipaddress.IPv4Address(octets[:4]))
    if kind in (2, 4) and len(octets) >= 16:
        return str(ipaddress.IPv6Address(octets[:16]))
    return None


async def port_addresses(snmp) -> dict[str, dict[str, list[str]]]:
    """{ifIndex: {"ipv4": ["10.0.0.1/24"], "ipv6": ["2001:db8::1"]}} from IP-MIB."""
    out: dict[str, dict[str, list[str]]] = {}

    def add(if_index, family: str, addr: str) -> None:
        bucket = out.setdefault(str(if_index), {"ipv4": [], "ipv6": []})[family]
        if addr not in bucket:
            bucket.append(addr)

    try:
        for suffix, if_index in (await snmp.walk(IP_ADDRESS_IFINDEX)).items():
            addr = parse_ip_index(suffix)
            if addr:
                add(if_index, "ipv6" if ":" in addr else "ipv4", addr)
    except Exception as e:  # noqa: BLE001 - old agents without the table
        log.debug("ipAddressTable: %s", e)
    try:
        masks = await snmp.walk(IP_AD_ENT_NETMASK)
        for ip, if_index in (await snmp.walk(IP_AD_ENT_IFINDEX)).items():
            try:
                prefix = ipaddress.IPv4Network(f"0.0.0.0/{masks.get(ip)}").prefixlen if masks.get(ip) else None
            except ValueError:
                prefix = None
            cidr = f"{ip}/{prefix}" if prefix is not None else ip
            bucket = out.setdefault(str(if_index), {"ipv4": [], "ipv6": []})["ipv4"]
            if ip in bucket:
                bucket[bucket.index(ip)] = cidr  # same address from the newer table, now with its prefix
            elif cidr not in bucket:
                bucket.append(cidr)
    except Exception as e:  # noqa: BLE001
        log.debug("ipAddrTable: %s", e)
    return out


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
        addresses = await port_addresses(ctx.snmp)
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
                        "mtu": r.get("mtu"),
                        "ipv4": (addresses.get(str(index)) or {}).get("ipv4", []),
                        "ipv6": (addresses.get(str(index)) or {}).get("ipv6", []),
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
            values.update(in_bps=in_bps, out_bps=out_bps, util=util,
                          in_util=in_bps / speed * 100 if speed else None, out_util=out_bps / speed * 100 if speed else None)
            # errors and discards per second for the port list (the counters themselves stay in values too)
            values.update({f"{c}_rate": rates[c] for c in ("in_errors", "out_errors", "in_discards", "out_discards") if c in rates})
            result.values[("port", port.index)] = values

            if "in_octets" in rates:
                result.metrics += [
                    MetricSample("in_bps", in_bps, "port", port.index),
                    MetricSample("out_bps", out_bps, "port", port.index),
                ]
                for c in ("in_errors", "out_errors", "in_discards", "out_discards"):
                    if c in rates:
                        result.metrics.append(MetricSample(c, rates[c], "port", port.index))
                if util is not None:
                    result.metrics.append(MetricSample("util", util, "port", port.index))
                packets = packet_metrics(rates)
                values.update(packets)
                for d in ("in", "out"):
                    if f"{d}_ucast_pps" in packets:
                        values[f"{d}_pps"] = packets[f"{d}_ucast_pps"] + packets.get(f"{d}_nucast_pps", 0.0)
                result.metrics += [MetricSample(k, v, "port", port.index) for k, v in packets.items()]

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
