"""Network stack statistics ("netstat over SNMP"): TCP-MIB, UDP-MIB, IP-MIB and ICMP counters.

Answers questions like: how many TCP connections are established, are segments being
retransmitted, are connection attempts failing, are UDP datagrams being dropped or sent
to closed ports.
"""

from netsync.plugins.base import CheckResult, ComponentSpec, DeviceContext, MetricSample, Module, PollResult

TCP = "1.3.6.1.2.1.6"
UDP = "1.3.6.1.2.1.7"
IP = "1.3.6.1.2.1.4"
ICMP = "1.3.6.1.2.1.5"

GAUGES = {"tcp_estab": f"{TCP}.9.0"}  # tcpCurrEstab

COUNTERS = {
    "tcp_active_opens": f"{TCP}.5.0",
    "tcp_passive_opens": f"{TCP}.6.0",
    "tcp_attempt_fails": f"{TCP}.7.0",
    "tcp_estab_resets": f"{TCP}.8.0",
    "tcp_in_segs": f"{TCP}.10.0",
    "tcp_out_segs": f"{TCP}.11.0",
    "tcp_retrans_segs": f"{TCP}.12.0",
    "tcp_in_errs": f"{TCP}.14.0",
    "tcp_out_rsts": f"{TCP}.15.0",
    "udp_in_datagrams": f"{UDP}.1.0",
    "udp_no_ports": f"{UDP}.2.0",
    "udp_in_errors": f"{UDP}.3.0",
    "udp_out_datagrams": f"{UDP}.4.0",
    "ip_in_receives": f"{IP}.3.0",
    "ip_in_hdr_errors": f"{IP}.4.0",
    "ip_in_addr_errors": f"{IP}.5.0",
    "ip_in_discards": f"{IP}.8.0",
    "ip_out_requests": f"{IP}.10.0",
    "ip_out_discards": f"{IP}.11.0",
    "ip_out_no_routes": f"{IP}.12.0",
    "icmp_in_msgs": f"{ICMP}.1.0",
    "icmp_in_errors": f"{ICMP}.2.0",
    "icmp_in_dest_unreachs": f"{ICMP}.3.0",
    "icmp_out_msgs": f"{ICMP}.14.0",
    "icmp_out_dest_unreachs": f"{ICMP}.16.0",
}

KIND, INDEX = "netstat", "0"
MIN_SEGS_FOR_RETRANS = 10  # segments/s sent before the retransmit percentage is meaningful


def rate_fmt(v: float) -> str:
    return f"{v:.0f}/s" if v >= 10 else f"{v:.2f}/s"


class NetstatsModule(Module):
    name = "netstats"
    kinds = (KIND,)
    order = 30

    async def discover(self, ctx: DeviceContext):
        r = await ctx.snmp.get(GAUGES["tcp_estab"], COUNTERS["udp_in_datagrams"])
        if all(v is None for v in r.values()):
            return []
        return [ComponentSpec(KIND, INDEX, "Network stack", attrs={})]

    async def poll(self, ctx: DeviceContext):
        if not ctx.components(KIND):
            return PollResult()
        oids = {**GAUGES, **COUNTERS}
        raw = await ctx.snmp.get(*oids.values())
        cur = {name: raw.get(oid) for name, oid in oids.items() if raw.get(oid) is not None}

        now = ctx.now.timestamp()
        prev = ctx.previous(KIND, INDEX)
        dt = now - prev.get("ts", 0)
        rates: dict[str, float] = {}
        for name in COUNTERS:
            # skip on first poll, after long gaps, and on counter wrap/reset
            if name in cur and name in prev and 0 < dt < 3600 and cur[name] >= prev[name]:
                rates[name] = (cur[name] - prev[name]) / dt

        result = PollResult(values={(KIND, INDEX): {"ts": now, **cur, **{f"{k}_rate": v for k, v in rates.items()}}})
        # Device-level series so dashboards can graph them without picking a component.
        if "tcp_estab" in cur:
            result.metrics.append(MetricSample("tcp_estab", cur["tcp_estab"]))
        result.metrics += [MetricSample(name, value) for name, value in rates.items()]

        if not rates:
            return result

        out_segs = rates.get("tcp_out_segs", 0)
        retrans = rates.get("tcp_retrans_segs", 0)
        retrans_pct = retrans / out_segs * 100 if out_segs > 0 else 0.0
        result.metrics.append(MetricSample("tcp_retrans_pct", retrans_pct))
        # On an almost idle host a couple of retransmits are a huge percentage (e.g. 5 of 8
        # segments = 62%): only judge the rate when there is real traffic.
        judged = out_segs >= MIN_SEGS_FOR_RETRANS
        result.checks.append(CheckResult(
            "tcp_retrans", "TCP", value=retrans_pct if judged else None, unit="%",
            output=(f"{cur.get('tcp_estab', 0)} established, retransmits {retrans_pct:.2f}%"
                    f"{'' if judged else f' (low traffic, {out_segs:.1f} segs/s - not evaluated)'}, "
                    f"failed opens {rate_fmt(rates.get('tcp_attempt_fails', 0))}, "
                    f"resets {rate_fmt(rates.get('tcp_estab_resets', 0) + rates.get('tcp_out_rsts', 0))}, "
                    f"errors {rate_fmt(rates.get('tcp_in_errs', 0))}"),
            perf={"estab": cur.get("tcp_estab", 0), "retrans_pct": retrans_pct},
        ))

        udp_errors = rates.get("udp_in_errors", 0)
        result.checks.append(CheckResult(
            "udp_errors", "UDP", value=udp_errors, unit="/s",
            output=(f"in {rate_fmt(rates.get('udp_in_datagrams', 0))}, out {rate_fmt(rates.get('udp_out_datagrams', 0))}, "
                    f"errors {rate_fmt(udp_errors)}, to closed ports {rate_fmt(rates.get('udp_no_ports', 0))}"),
        ))
        return result
