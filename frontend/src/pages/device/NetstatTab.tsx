import { Component } from "../../api";
import { AddToDashboard } from "../../components/AddToDashboard";
import { MetricChart } from "../../components/MetricChart";
import { Card, Empty } from "../../components/ui";
import { presetById } from "../../presets";

const GRAPHS = ["tcp_conns", "tcp_retrans", "tcp_segments", "tcp_failures", "tcp_opens", "udp_traffic", "udp_errors", "ip_errors", "icmp"];

function Stat({ label, value, warn }: { label: string; value: string; warn?: boolean }) {
  return (
    <div className="card px-4 py-3">
      <div className="text-xs text-muted">{label}</div>
      <div className={`text-xl font-semibold tabular-nums mt-0.5 ${warn ? "text-warn" : "text-strong"}`}>{value}</div>
    </div>
  );
}

const r = (v: number | undefined) => (v == null ? "-" : v >= 100 ? `${v.toFixed(0)}/s` : `${v.toFixed(2)}/s`);

export default function NetstatTab({ deviceId, component, range }: { deviceId: number; component?: Component; range: string }) {
  if (!component) return <Card><Empty>This device does not expose TCP-MIB / UDP-MIB statistics over SNMP.</Empty></Card>;
  const v = component.values;
  const out = v.tcp_out_segs_rate ?? 0;
  const retransPct = out > 0 ? ((v.tcp_retrans_segs_rate ?? 0) / out) * 100 : 0;

  return (
    <>
      <div className="grid grid-cols-2 md:grid-cols-4 xl:grid-cols-8 gap-3">
        <Stat label="TCP established" value={v.tcp_estab != null ? String(v.tcp_estab) : "-"} />
        <Stat label="TCP retransmits" value={`${retransPct.toFixed(2)}%`} warn={retransPct >= 5} />
        <Stat label="Failed opens" value={r(v.tcp_attempt_fails_rate)} warn={(v.tcp_attempt_fails_rate ?? 0) > 1} />
        <Stat label="TCP resets" value={r((v.tcp_estab_resets_rate ?? 0) + (v.tcp_out_rsts_rate ?? 0))} />
        <Stat label="UDP in" value={r(v.udp_in_datagrams_rate)} />
        <Stat label="UDP out" value={r(v.udp_out_datagrams_rate)} />
        <Stat label="UDP errors" value={r(v.udp_in_errors_rate)} warn={(v.udp_in_errors_rate ?? 0) >= 5} />
        <Stat label="UDP to closed ports" value={r(v.udp_no_ports_rate)} />
      </div>
      <div className="grid lg:grid-cols-2 gap-4">
        {GRAPHS.map((id) => {
          const p = presetById(id)!;
          return (
            <Card key={id} title={p.label} actions={<AddToDashboard deviceId={deviceId} preset={id} label="" />}>
              <div className="p-3">
                <MetricChart deviceId={deviceId} range={range} metrics={p.metrics} format={p.format} area={p.area ?? true} />
              </div>
            </Card>
          );
        })}
      </div>
      <p className="text-xs text-muted">
        Counters come from TCP-MIB, UDP-MIB, IP-MIB and ICMP over SNMP and are shown as rates per second. Threshold checks:
        TCP retransmit rate (warn 5%, crit 10%) and UDP receive errors (warn 5/s, crit 50/s), adjustable in Threshold rules.
      </p>
    </>
  );
}
