/** Every device-level graph, grouped like Observium (System, Processor, Memory, Storage, Network, Poller).
 *  Graphs without data on this device are hidden. */
import { useState } from "react";
import { Card, Empty } from "../../components/ui";
import { Preset, usePresets } from "../../presets";
import { PresetCard, presetHasData, useMetricNames } from "./charts";

const SECTIONS: [string, string, string[]][] = [
  ["system", "System", ["availability", "uptime", "load", "ctx_switches", "interrupts", "processes", "users"]],
  ["processor", "Processor", ["cpu", "cpu_detail", "cpu_extended"]],
  ["memory", "Memory", ["mem_usage", "mem_detail", "swap_usage"]],
  ["storage", "Storage", ["swap_io", "system_io"]],
  ["netstats", "Network stack", ["ip_stats", "ip_frag", "icmp", "icmp_info", "tcp_conns", "tcp_segments", "tcp_retrans",
    "tcp_failures", "tcp_opens", "udp_traffic", "udp_errors", "ip_errors", "snmp_stats", "snmp_packets",
    "ipv4_packets", "ipv4_frag", "ipv6_packets", "ipv6_frag"]],
  ["poller", "Poller", ["latency_avg", "latency", "snmp_response", "poller_duration", "poller_requests",
    "poller_snmp_time", "poller_errors"]],
];

export default function GraphsTab({ deviceId, range }: { deviceId: number; range: string }) {
  const { byId } = usePresets();
  const names = useMetricNames(deviceId);
  const sections = SECTIONS.map(([key, label, ids]) => [key, label,
    ids.map((id) => byId(id)).filter((p): p is Preset => !!p && presetHasData(p, names))] as [string, string, Preset[]])
    .filter(([, , ps]) => ps.length);
  const [active, setActive] = useState("all");
  if (names && !sections.length) return <Card><Empty>No graphs yet: data shows up after a couple of polls.</Empty></Card>;
  const shown = active === "all" ? sections : sections.filter(([k]) => k === active);

  return (
    <div className="space-y-5">
      <div className="flex gap-1 overflow-x-auto no-scrollbar">
        {[["all", "All"] as [string, string], ...sections.map(([k, l]) => [k, l] as [string, string])].map(([k, l]) => (
          <button key={k} onClick={() => setActive(k)}
            className={`px-3 py-1.5 rounded-lg text-xs whitespace-nowrap transition-colors ${active === k ? "bg-seg-active text-on-seg-active" : "text-muted hover:text-fg hover:bg-inset"}`}>
            {l}
          </button>
        ))}
      </div>
      {shown.map(([key, label, presets]) => (
        <section key={key} className="space-y-3">
          <h2 className="text-sm font-semibold text-strong">{label}</h2>
          <div className="grid lg:grid-cols-2 gap-4">
            {presets.map((p) => <PresetCard key={p.id} deviceId={deviceId} preset={p} range={range} />)}
          </div>
        </section>
      ))}
    </div>
  );
}
