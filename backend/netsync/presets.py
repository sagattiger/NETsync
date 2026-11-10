"""Graph presets: what a dashboard graph widget (or a device tab) can show.

Single source of truth for the React app (GET /api/presets) and the public dashboards API.
``unit`` tells clients how to format values: bps | pct | ms | s | rate | count.
"""

from dataclasses import asdict, dataclass, field


@dataclass(frozen=True)
class SeriesDef:
    name: str  # metric name in the metrics table
    label: str


@dataclass(frozen=True)
class Preset:
    id: str
    label: str
    group: str
    kind: str | None  # component kind the preset needs (None = device-level series)
    unit: str
    metrics: tuple[SeriesDef, ...] = field(default_factory=tuple)
    area: bool = True
    source: str = "device"  # "device" (device_id/component_id) or "probe" (probe_id)
    daily: bool = False  # long ranges (7d+) use one point per day, e.g. uptime %

    def bucket(self, range_: str):
        """time_bucket override for this preset and range (None = the range's default)."""
        from datetime import timedelta

        return timedelta(days=1) if self.daily and range_ in ("7d", "30d", "1y") else None

    def as_dict(self) -> dict:
        d = asdict(self)
        d["metrics"] = [asdict(m) for m in self.metrics]
        return d


def _s(*pairs: tuple[str, str]) -> tuple[SeriesDef, ...]:
    return tuple(SeriesDef(n, label) for n, label in pairs)


UNITS = ("bps", "pct", "ms", "s", "rate", "count")

PRESETS: tuple[Preset, ...] = (
    Preset("port_traffic", "Interface traffic", "Interfaces", "port", "bps", _s(("in_bps", "in"), ("out_bps", "out"))),
    Preset("port_errors", "Interface errors & discards", "Interfaces", "port", "rate",
           _s(("in_errors", "in errors"), ("out_errors", "out errors"), ("in_discards", "in discards"),
              ("out_discards", "out discards")), area=False),

    Preset("cpu", "CPU utilization", "Health", None, "pct", _s(("cpu_util", "CPU"))),
    Preset("memory", "Memory used", "Health", "mempool", "pct", _s(("used_pct", "used"))),
    Preset("storage", "Filesystem used", "Health", "storage", "pct", _s(("used_pct", "used"))),

    Preset("latency", "Latency", "Reachability", None, "ms",
           _s(("ping_avg", "avg"), ("ping_min", "min"), ("ping_max", "max")), area=False),
    Preset("loss", "Packet loss", "Reachability", None, "pct", _s(("ping_loss", "loss"))),
    Preset("poll_time", "SNMP poll time", "Reachability", None, "s", _s(("poll_duration", "poll"))),

    Preset("tcp_conns", "TCP connections", "Network stack", None, "count", _s(("tcp_estab", "established"))),
    Preset("tcp_segments", "TCP segments", "Network stack", None, "rate",
           _s(("tcp_in_segs", "in"), ("tcp_out_segs", "out"), ("tcp_retrans_segs", "retransmitted")), area=False),
    Preset("tcp_retrans", "TCP retransmit rate", "Network stack", None, "pct", _s(("tcp_retrans_pct", "retransmits"))),
    Preset("tcp_failures", "TCP failures", "Network stack", None, "rate",
           _s(("tcp_attempt_fails", "failed opens"), ("tcp_estab_resets", "resets"), ("tcp_out_rsts", "RST sent"),
              ("tcp_in_errs", "errors")), area=False),
    Preset("tcp_opens", "TCP opens", "Network stack", None, "rate",
           _s(("tcp_active_opens", "outgoing"), ("tcp_passive_opens", "incoming")), area=False),
    Preset("udp_traffic", "UDP datagrams", "Network stack", None, "rate",
           _s(("udp_in_datagrams", "in"), ("udp_out_datagrams", "out")), area=False),
    Preset("udp_errors", "UDP errors", "Network stack", None, "rate",
           _s(("udp_in_errors", "receive errors"), ("udp_no_ports", "to closed ports")), area=False),
    Preset("ip_errors", "IP errors & discards", "Network stack", None, "rate",
           _s(("ip_in_hdr_errors", "header errors"), ("ip_in_addr_errors", "address errors"),
              ("ip_in_discards", "in discards"), ("ip_out_discards", "out discards"), ("ip_out_no_routes", "no route")),
           area=False),
    Preset("icmp", "ICMP", "Network stack", None, "rate",
           _s(("icmp_in_msgs", "in"), ("icmp_out_msgs", "out"), ("icmp_in_dest_unreachs", "unreachable in"),
              ("icmp_in_errors", "errors")), area=False),

    # Probes (ping any IP/FQDN): widgets point at probe_id instead of device_id/component_id.
    Preset("probe_latency", "Ping latency", "Probes", None, "ms", _s(("ping_avg", "avg")), area=False, source="probe"),
    Preset("probe_loss", "Ping packet loss", "Probes", None, "pct", _s(("ping_loss", "loss")), source="probe"),
    Preset("probe_response", "Response time", "Probes", None, "ms", _s(("response_ms", "response")), area=False,
           source="probe"),
    Preset("probe_uptime", "Uptime", "Probes", None, "pct", _s(("up_pct", "uptime")), source="probe", daily=True),
    Preset("tls_days_left", "Certificate days left", "Probes", None, "count", _s(("tls_days_left", "days left")),
           area=False, source="probe"),
    Preset("dns_query", "DNS query time", "Probes", None, "ms", _s(("dns_query_ms", "query")), area=False,
           source="probe"),
    Preset("http_status", "HTTP status code", "Probes", None, "count", _s(("status_code", "status")), area=False,
           source="probe"),
)

BY_ID: dict[str, Preset] = {p.id: p for p in PRESETS}
