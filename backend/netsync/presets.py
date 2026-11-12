"""Graph presets: what a dashboard graph widget (or a device tab) can show.

Single source of truth for the React app (GET /api/presets) and the public dashboards API.
``unit`` tells clients how to format values: bps | pct | ms | s | rate | count | bytes | Bps | celsius | rpm |
load | duration. ``stack`` draws the series stacked; ``ruler`` names a series whose newest value is the real
capacity (RAM size, swap size, thread count): charts use it as the top of the scale instead of 0-100 %.
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
    stack: bool = False  # stacked series (parts of one whole, e.g. used + buffers + cached + free)
    ruler: str | None = None  # metric holding the capacity, e.g. mem_total; drawn as the top of the scale

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


UNITS = ("bps", "pct", "ms", "s", "rate", "count", "bytes", "Bps", "celsius", "rpm", "load", "duration")

PRESETS: tuple[Preset, ...] = (
    Preset("port_traffic", "Interface traffic", "Interfaces", "port", "bps", _s(("in_bps", "in"), ("out_bps", "out"))),
    Preset("port_errors", "Interface errors & discards", "Interfaces", "port", "rate",
           _s(("in_errors", "in errors"), ("out_errors", "out errors"), ("in_discards", "in discards"),
              ("out_discards", "out discards")), area=False),
    Preset("port_packets", "Unicast packets", "Interfaces", "port", "rate",
           _s(("in_ucast_pps", "in"), ("out_ucast_pps", "out"))),
    Preset("port_nucast", "Non-unicast packets", "Interfaces", "port", "rate",
           _s(("in_nucast_pps", "in"), ("out_nucast_pps", "out")), area=False),
    Preset("port_pkt_size", "Average packet size", "Interfaces", "port", "bytes",
           _s(("in_pkt_size", "in"), ("out_pkt_size", "out")), area=False),
    Preset("port_util", "Percent utilisation", "Interfaces", "port", "pct", _s(("util", "utilisation"))),

    Preset("availability", "Device availability", "System", None, "pct", _s(("available", "available")), daily=True),
    Preset("uptime", "Device uptime", "System", None, "duration", _s(("uptime", "uptime")), area=False),
    Preset("load", "Load averages", "System", None, "load",
           _s(("load1", "1 min"), ("load5", "5 min"), ("load15", "15 min")), area=False, ruler="cpu_count"),
    Preset("ctx_switches", "Context switches", "System", None, "rate", _s(("ctx_switches", "switches"))),
    Preset("interrupts", "System interrupts", "System", None, "rate", _s(("interrupts", "interrupts"))),
    Preset("processes", "Running processes", "System", None, "count", _s(("processes", "processes"))),
    Preset("users", "Users logged in", "System", None, "count", _s(("users", "users")), area=False),

    Preset("cpu_detail", "Detailed processor utilisation", "Processor", None, "pct",
           _s(("cpu_user", "user"), ("cpu_nice", "nice"), ("cpu_system", "system"), ("cpu_wait", "iowait"),
              ("cpu_irq", "irq"), ("cpu_softirq", "softirq"), ("cpu_steal", "steal")), stack=True),
    Preset("cpu_extended", "Extended processor utilisation", "Processor", None, "pct",
           _s(("cpu_user", "user"), ("cpu_nice", "nice"), ("cpu_system", "system"), ("cpu_wait", "iowait"),
              ("cpu_irq", "irq"), ("cpu_softirq", "softirq"), ("cpu_steal", "steal"), ("cpu_guest", "guest"),
              ("cpu_idle", "idle")), stack=True),

    Preset("mem_usage", "Memory usage", "Memory", None, "bytes",
           _s(("mem_used", "used"), ("mem_available", "available")), area=False, ruler="mem_total"),
    Preset("mem_detail", "Detailed memory", "Memory", None, "bytes",
           _s(("mem_used", "used"), ("mem_buffers", "buffers"), ("mem_cached", "cached"), ("mem_free", "free")),
           stack=True, ruler="mem_total"),
    Preset("swap_usage", "Swap usage", "Memory", None, "bytes", _s(("swap_used", "used")), ruler="swap_total"),
    Preset("swap_io", "Swap I/O activity", "Memory", None, "rate", _s(("swap_in", "in"), ("swap_out", "out"))),

    Preset("system_io", "System I/O activity", "Storage", None, "rate",
           _s(("io_received", "read blocks"), ("io_sent", "written blocks"))),
    Preset("disk_io", "Disk throughput", "Storage", "disk", "Bps", _s(("read_bps", "read"), ("write_bps", "write"))),
    Preset("disk_ops", "Disk operations", "Storage", "disk", "rate",
           _s(("read_iops", "reads"), ("write_iops", "writes")), area=False),

    Preset("temperature", "Temperature", "Sensors", "sensor", "celsius", _s(("value", "temperature")), area=False),
    Preset("fanspeed", "Fan speed", "Sensors", "sensor", "rpm", _s(("value", "speed")), area=False),

    Preset("cpu", "CPU utilization", "Health", None, "pct", _s(("cpu_util", "CPU"))),
    Preset("memory", "Memory used", "Health", "mempool", "pct", _s(("used_pct", "used"))),
    Preset("storage", "Filesystem used", "Health", "storage", "pct", _s(("used_pct", "used"))),

    Preset("latency", "Latency", "Reachability", None, "ms",
           _s(("ping_avg", "avg"), ("ping_min", "min"), ("ping_max", "max")), area=False),
    Preset("loss", "Packet loss", "Reachability", None, "pct", _s(("ping_loss", "loss"))),
    Preset("latency_avg", "Ping response", "Reachability", None, "ms", _s(("ping_avg", "avg")), area=False),
    Preset("snmp_response", "SNMP response", "Reachability", None, "ms", _s(("snmp_response_ms", "response")),
           area=False),
    Preset("poll_time", "SNMP poll time", "Reachability", None, "s", _s(("poll_duration", "poll"))),

    Preset("poller_duration", "Poller duration", "Poller", None, "s", _s(("poll_duration", "duration"))),
    Preset("poller_requests", "Poller SNMP requests", "Poller", None, "count", _s(("poll_snmp_requests", "requests")),
           area=False),
    Preset("poller_snmp_time", "Poller SNMP time", "Poller", None, "s", _s(("poll_snmp_time", "waiting")), area=False),
    Preset("poller_errors", "Poller SNMP errors", "Poller", None, "count", _s(("poll_snmp_errors", "errors")),
           area=False),

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
    Preset("icmp_info", "ICMP informational", "Network stack", None, "rate",
           _s(("icmp_in_echos", "echo in"), ("icmp_out_echo_reps", "echo reply out"), ("icmp_out_echos", "echo out"),
              ("icmp_in_echo_reps", "echo reply in"), ("icmp_in_time_excds", "time exceeded in")), area=False),
    Preset("ip_stats", "IP statistics", "IP", None, "rate",
           _s(("ip_in_receives", "received"), ("ip_in_delivers", "delivered"), ("ip_out_requests", "sent"),
              ("ip_forw_datagrams", "forwarded")), area=False),
    Preset("ip_frag", "IP fragmentation", "IP", None, "rate",
           _s(("ip_reasm_reqds", "reassembly needed"), ("ip_reasm_oks", "reassembled"),
              ("ip_reasm_fails", "reassembly failed"), ("ip_frag_oks", "fragmented"),
              ("ip_frag_fails", "fragmentation failed"), ("ip_frag_creates", "fragments created")), area=False),
    Preset("ipv4_packets", "IPv4 packets", "IP", None, "rate",
           _s(("ipv4_in_receives", "received"), ("ipv4_in_delivers", "delivered"), ("ipv4_out_requests", "sent"),
              ("ipv4_forw_datagrams", "forwarded"), ("ipv4_in_discards", "in discards"),
              ("ipv4_out_discards", "out discards")), area=False),
    Preset("ipv4_frag", "IPv4 fragmentation", "IP", None, "rate",
           _s(("ipv4_reasm_reqds", "reassembly needed"), ("ipv4_reasm_oks", "reassembled"),
              ("ipv4_reasm_fails", "reassembly failed"), ("ipv4_frag_oks", "fragmented"),
              ("ipv4_frag_fails", "fragmentation failed"), ("ipv4_frag_creates", "fragments created")), area=False),
    Preset("ipv6_packets", "IPv6 packets", "IP", None, "rate",
           _s(("ipv6_in_receives", "received"), ("ipv6_in_delivers", "delivered"), ("ipv6_out_requests", "sent"),
              ("ipv6_forw_datagrams", "forwarded"), ("ipv6_in_discards", "in discards"),
              ("ipv6_out_discards", "out discards")), area=False),
    Preset("ipv6_frag", "IPv6 fragmentation", "IP", None, "rate",
           _s(("ipv6_reasm_reqds", "reassembly needed"), ("ipv6_reasm_oks", "reassembled"),
              ("ipv6_reasm_fails", "reassembly failed"), ("ipv6_frag_oks", "fragmented"),
              ("ipv6_frag_fails", "fragmentation failed"), ("ipv6_frag_creates", "fragments created")), area=False),
    Preset("snmp_stats", "SNMP statistics", "SNMP", None, "rate",
           _s(("snmp_in_bad_community", "bad community"), ("snmp_in_bad_versions", "bad version"),
              ("snmp_in_asn_errs", "parse errors")), area=False),
    Preset("snmp_packets", "SNMP packets", "SNMP", None, "rate",
           _s(("snmp_in_pkts", "in"), ("snmp_out_pkts", "out"), ("snmp_in_get_requests", "get"),
              ("snmp_in_get_nexts", "get-next"), ("snmp_out_traps", "traps")), area=False),

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
