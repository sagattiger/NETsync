import { fmtBps } from "./api";
import type { MetricDef } from "./components/MetricChart";

/** Graph presets: what a dashboard graph widget (or a device tab) can show. */
export interface Preset {
  id: string;
  label: string;
  group: string;
  kind: string | null; // component kind the preset needs (null = device-level series)
  metrics: MetricDef[];
  format: (v: number) => string;
  area?: boolean;
}

const pct = (v: number) => `${v.toFixed(v < 10 ? 1 : 0)}%`;
const rate = (v: number) => (v >= 100 ? `${v.toFixed(0)}/s` : `${v.toFixed(v < 1 ? 2 : 1)}/s`);
const ms = (v: number) => `${v.toFixed(1)} ms`;
const int = (v: number) => `${Math.round(v)}`;
const sec = (v: number) => `${v.toFixed(2)} s`;

export const PRESETS: Preset[] = [
  { id: "port_traffic", label: "Interface traffic", group: "Interfaces", kind: "port", format: fmtBps,
    metrics: [{ name: "in_bps", label: "in" }, { name: "out_bps", label: "out" }] },
  { id: "port_errors", label: "Interface errors & discards", group: "Interfaces", kind: "port", format: rate, area: false,
    metrics: [{ name: "in_errors", label: "in errors" }, { name: "out_errors", label: "out errors" },
      { name: "in_discards", label: "in discards" }, { name: "out_discards", label: "out discards" }] },

  { id: "cpu", label: "CPU utilization", group: "Health", kind: null, format: pct, metrics: [{ name: "cpu_util", label: "CPU" }] },
  { id: "memory", label: "Memory used", group: "Health", kind: "mempool", format: pct, metrics: [{ name: "used_pct", label: "used" }] },
  { id: "storage", label: "Filesystem used", group: "Health", kind: "storage", format: pct, metrics: [{ name: "used_pct", label: "used" }] },

  { id: "latency", label: "Latency", group: "Reachability", kind: null, format: ms, area: false,
    metrics: [{ name: "ping_avg", label: "avg" }, { name: "ping_min", label: "min" }, { name: "ping_max", label: "max" }] },
  { id: "loss", label: "Packet loss", group: "Reachability", kind: null, format: pct, metrics: [{ name: "ping_loss", label: "loss" }] },
  { id: "poll_time", label: "SNMP poll time", group: "Reachability", kind: null, format: sec, metrics: [{ name: "poll_duration", label: "poll" }] },

  { id: "tcp_conns", label: "TCP connections", group: "Network stack", kind: null, format: int,
    metrics: [{ name: "tcp_estab", label: "established" }] },
  { id: "tcp_segments", label: "TCP segments", group: "Network stack", kind: null, format: rate, area: false,
    metrics: [{ name: "tcp_in_segs", label: "in" }, { name: "tcp_out_segs", label: "out" }, { name: "tcp_retrans_segs", label: "retransmitted" }] },
  { id: "tcp_retrans", label: "TCP retransmit rate", group: "Network stack", kind: null, format: pct,
    metrics: [{ name: "tcp_retrans_pct", label: "retransmits" }] },
  { id: "tcp_failures", label: "TCP failures", group: "Network stack", kind: null, format: rate, area: false,
    metrics: [{ name: "tcp_attempt_fails", label: "failed opens" }, { name: "tcp_estab_resets", label: "resets" },
      { name: "tcp_out_rsts", label: "RST sent" }, { name: "tcp_in_errs", label: "errors" }] },
  { id: "tcp_opens", label: "TCP opens", group: "Network stack", kind: null, format: rate, area: false,
    metrics: [{ name: "tcp_active_opens", label: "outgoing" }, { name: "tcp_passive_opens", label: "incoming" }] },
  { id: "udp_traffic", label: "UDP datagrams", group: "Network stack", kind: null, format: rate, area: false,
    metrics: [{ name: "udp_in_datagrams", label: "in" }, { name: "udp_out_datagrams", label: "out" }] },
  { id: "udp_errors", label: "UDP errors", group: "Network stack", kind: null, format: rate, area: false,
    metrics: [{ name: "udp_in_errors", label: "receive errors" }, { name: "udp_no_ports", label: "to closed ports" }] },
  { id: "ip_errors", label: "IP errors & discards", group: "Network stack", kind: null, format: rate, area: false,
    metrics: [{ name: "ip_in_hdr_errors", label: "header errors" }, { name: "ip_in_addr_errors", label: "address errors" },
      { name: "ip_in_discards", label: "in discards" }, { name: "ip_out_discards", label: "out discards" },
      { name: "ip_out_no_routes", label: "no route" }] },
  { id: "icmp", label: "ICMP", group: "Network stack", kind: null, format: rate, area: false,
    metrics: [{ name: "icmp_in_msgs", label: "in" }, { name: "icmp_out_msgs", label: "out" },
      { name: "icmp_in_dest_unreachs", label: "unreachable in" }, { name: "icmp_in_errors", label: "errors" }] },
];

export const presetById = (id: string | null | undefined) => PRESETS.find((p) => p.id === id);

export const PRESET_GROUPS = [...new Set(PRESETS.map((p) => p.group))];
