import { useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api, fmtAgo, prefs, Probe } from "../api";
import { AddToDashboard } from "../components/AddToDashboard";
import { Icon } from "../components/Icon";
import { Page, PageHeader } from "../components/Layout";
import { MetricChart } from "../components/MetricChart";
import { Card, Empty, Segmented, StateBadge, Tile } from "../components/ui";
import { FORMATS } from "../presets";
import { fmtLoss, fmtMs, ProbeForm, toggleProbe, useMe } from "./Probes";

const RANGES: [string, string][] = [["1h", "1h"], ["6h", "6h"], ["24h", "24h"], ["7d", "7d"], ["30d", "30d"], ["1y", "1y"]];

export default function ProbePage() {
  const id = Number(useParams().id);
  const nav = useNavigate();
  const qc = useQueryClient();
  const me = useMe();
  const canEdit = me?.role !== "viewer";
  const [range, setRange] = useState(() => prefs.get().default_range ?? "24h");
  const [editing, setEditing] = useState(false);
  const { data: p, error } = useQuery({ queryKey: ["probe", id], queryFn: () => api<Probe>(`/probes/${id}`), refetchInterval: prefs.refreshMs(30_000) });

  if (error) return <Page><Card><Empty>Probe not found</Empty></Card></Page>;
  if (!p) return <Empty>Loading…</Empty>;

  async function toggle() {
    await toggleProbe(p!);
    qc.invalidateQueries({ queryKey: ["probe", id] });
    qc.invalidateQueries({ queryKey: ["probes"] });
  }
  async function remove() {
    if (!confirm(`Delete probe "${p!.name}" and its history?`)) return;
    await api(`/probes/${id}`, { method: "DELETE" });
    qc.invalidateQueries({ queryKey: ["probes"] });
    nav("/probes");
  }
  const jitter = p.services.find((s) => s.name === "Ping RTT");

  return (
    <>
      <PageHeader
        title={<span className="flex items-center gap-3">{p.name} {p.enabled ? <StateBadge state={p.state} small /> : <span className="text-xxs font-semibold uppercase px-2 py-0.5 rounded-full bg-chip text-muted">paused</span>}</span>}
        sub={<><span className="font-mono">{p.target}</span> · ICMP, {p.count} pings every {p.interval_s}s · {p.last_run ? `last run ${fmtAgo(p.last_run)}` : "not run yet"}</>}
        actions={<>
          <Segmented value={range} onChange={setRange} options={RANGES} />
          {canEdit && <>
            <button className="btn" onClick={toggle}><Icon name={p.enabled ? "pause" : "play"} className="w-3.5 h-3.5" /> {p.enabled ? "Pause" : "Resume"}</button>
            <button className="btn" onClick={() => setEditing(true)}><Icon name="edit" className="w-3.5 h-3.5" /> Edit</button>
            <button className="btn text-crit hover:bg-crit/10" onClick={remove}><Icon name="trash" className="w-3.5 h-3.5" /></button>
          </>}
        </>}
      />
      <Page>
        {p.last_error && <div className="rounded-lg border border-crit/40 bg-crit/10 text-crit text-sm p-3">{p.last_error}</div>}
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
          <Tile label="Round-trip time" value={fmtMs(p.rtt_ms)} />
          <Tile label="Packet loss" value={fmtLoss(p.loss_pct)} tone={p.loss_pct ? 1 : undefined} />
          <Tile label="Last round" value={<span className="text-base">{jitter?.output ?? "–"}</span>} />
          <Tile label="Created" value={<span className="text-base">{fmtAgo(p.created_at)}</span>} />
        </div>
        <Card title="Latency" actions={<AddToDashboard probeId={p.id} preset="probe_latency" />}>
          <div className="p-3">
            <MetricChart probeId={p.id} range={range} metrics={[{ name: "ping_avg", label: "avg" }]} format={FORMATS.ms} area={false}
              band={{ min: "ping_min", max: "ping_max", label: "min–max" }} height={280} />
          </div>
        </Card>
        <div className="grid lg:grid-cols-2 gap-4">
          <Card title="Packet loss" actions={<AddToDashboard probeId={p.id} preset="probe_loss" />}>
            <div className="p-3"><MetricChart probeId={p.id} range={range} metrics={[{ name: "ping_loss", label: "loss" }]} format={FORMATS.pct} height={200} /></div>
          </Card>
          <Card title="Jitter">
            <div className="p-3"><MetricChart probeId={p.id} range={range} metrics={[{ name: "ping_jitter", label: "jitter" }]} format={FORMATS.ms} area={false} height={200} /></div>
          </Card>
        </div>
        <Card title="Checks">
          <table className="tbl">
            <thead><tr><th>State</th><th>Service</th><th>Output</th><th>Since</th></tr></thead>
            <tbody>
              {p.services.map((s) => (
                <tr key={s.id}><td><StateBadge state={s.state} small /></td><td className="text-strong">{s.name}</td>
                  <td className="text-xs text-fg2">{s.output}</td><td className="text-xs text-muted">{fmtAgo(s.last_change)}</td></tr>
              ))}
              {!p.services.length && <tr><td colSpan={4}><Empty>Waiting for the first round…</Empty></td></tr>}
            </tbody>
          </table>
        </Card>
      </Page>
      {editing && <ProbeForm initial={p} onClose={() => setEditing(false)} />}
    </>
  );
}
