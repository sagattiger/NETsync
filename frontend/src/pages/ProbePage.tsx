import { ReactNode, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api, fmtAgo, fmtDateTime, Heartbeat, prefs, Probe } from "../api";
import { AddToDashboard } from "../components/AddToDashboard";
import { Icon } from "../components/Icon";
import { Page, PageHeader } from "../components/Layout";
import { MetricChart } from "../components/MetricChart";
import { Card, Empty, Segmented, StateBadge } from "../components/ui";
import { FORMATS } from "../presets";
import EventsTab from "./device/EventsTab";
import { toggleProbe } from "./Probes";
import { ProbeForm, PushUrlModal } from "./probes/ProbeForm";
import { daysTone, fmtLoss, fmtMs, fmtPct, HeartbeatBar, KindIcon, kindMeta, StatusPill, uptimeTone, useMe } from "./probes/shared";

const RANGES: [string, string][] = [["1h", "1h"], ["6h", "6h"], ["24h", "24h"], ["7d", "7d"], ["30d", "30d"], ["1y", "1y"]];
const WINDOWS: ["24h" | "7d" | "30d" | "1y", string][] = [["24h", "24 hours"], ["7d", "7 days"], ["30d", "30 days"], ["1y", "1 year"]];

function CertPanel({ p }: { p: Probe }) {
  const c = p.cert!;
  const row = (k: string, v: ReactNode) => <div className="flex gap-3 py-1.5 border-b border-line last:border-0"><span className="w-32 shrink-0 text-muted">{k}</span><span className="text-fg min-w-0 break-words">{v}</span></div>;
  return (
    <Card title="Certificate" flush={false}>
      <div className="flex items-baseline gap-2 mb-3">
        <span className={`text-3xl font-semibold tabular-nums ${daysTone(c.days_left)}`}>{Math.floor(c.days_left)}</span>
        <span className="text-sm text-muted">days left · expires {fmtDateTime(c.not_after)}</span>
      </div>
      <div className="text-sm">
        {row("Subject", c.subject_cn ?? "–")}
        {row("Issuer", [c.issuer, c.issuer_org && c.issuer_org !== c.issuer ? c.issuer_org : null].filter(Boolean).join(" · ") || "–")}
        {row("Hostname", c.hostname_match == null ? "not checked" : c.hostname_match ? <span className="text-ok">matches</span> : <span className="text-crit">mismatch</span>)}
        {row("Chain", c.chain_valid == null ? "not verified (TLS errors ignored)" : c.chain_valid ? <span className="text-ok">trusted</span> : <span className="text-crit">untrusted{c.self_signed ? " (self-signed)" : ""}</span>)}
        {row("Protocol / key", [c.tls_version, `${c.key_type}${c.key_bits ? ` ${c.key_bits}` : ""}`].filter(Boolean).join(" · "))}
        {row("Valid from", fmtDateTime(c.not_before))}
        {c.sans.length > 0 && row("Names (SAN)", <span className="font-mono text-xs">{c.sans.join(", ")}</span>)}
      </div>
    </Card>
  );
}

export default function ProbePage() {
  const id = Number(useParams().id);
  const nav = useNavigate();
  const qc = useQueryClient();
  const me = useMe();
  const canEdit = me?.role !== "viewer";
  const [range, setRange] = useState(() => prefs.get().default_range ?? "24h");
  const [editing, setEditing] = useState(false);
  const [pushUrl, setPushUrl] = useState<string | null>(null);
  const { data: p, error } = useQuery({ queryKey: ["probe", id], queryFn: () => api<Probe>(`/probes/${id}`), refetchInterval: prefs.refreshMs(30_000) });
  const { data: beats = [] } = useQuery({ queryKey: ["probe-beats", id], queryFn: () => api<Heartbeat[]>(`/probes/${id}/heartbeats?limit=100`), refetchInterval: prefs.refreshMs(30_000) });

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
  const icmp = p.kind === "icmp";
  async function regenerate() {
    if (!confirm("Create a new push URL? The current one stops working immediately.")) return;
    setPushUrl((await api<{ push_url: string }>(`/probes/${id}/push-token`, { method: "POST" })).push_url);
  }

  return (
    <>
      <PageHeader back={{ to: "/probes", label: "Probes" }}
        title={<span className="flex items-center gap-3"><KindIcon kind={p.kind} className="w-5 h-5" />{p.name} <StatusPill enabled={p.enabled} maintenance={p.maintenance} state={p.state} /></span>}
        sub={<>{kindMeta(p.kind).label}{p.kind !== "push" && <> · <span className="font-mono">{p.target}{p.port ? `:${p.port}` : ""}</span></>} · every {p.interval_s}s
          {p.retries > 1 && ` · ${p.retries} retries`}{p.upside_down && " · upside down"} · {p.last_run ? `checked ${fmtAgo(p.last_run)}` : "not run yet"}</>}
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
        <Card flush={false}>
          <div className="flex items-center justify-between gap-3 mb-2 text-xs text-muted">
            <span className="flex items-center gap-2">Last {beats.length} checks <AddToDashboard probeId={p.id} preset={null} type="uptime" label="Add uptime to dashboard" /></span>
            <span className={p.state === 2 ? "text-crit" : "text-fg2"}>{p.last_message ?? ""}</span>
          </div>
          <HeartbeatBar beats={beats} />
          {p.description && <div className="text-sm text-fg2 mt-3">{p.description}</div>}
          {p.tags.length > 0 && <div className="flex flex-wrap gap-1 mt-2">{p.tags.map((t) => <span key={t} className="text-xxs px-1.5 rounded bg-chip text-fg2">{t}</span>)}</div>}
        </Card>

        <div className="grid grid-cols-2 lg:grid-cols-5 gap-4">
          <div className="card px-4 py-3.5">
            <div className="text-xs text-muted">Response</div>
            <div className="text-2xl font-semibold mt-1 tabular-nums text-strong">{fmtMs(p.rtt_ms ?? p.last_response_ms)}</div>
            {icmp && <div className="text-xxs text-muted mt-0.5">loss {fmtLoss(p.loss_pct)}</div>}
          </div>
          {WINDOWS.map(([k, label]) => (
            <div key={k} className="card px-4 py-3.5">
              <div className="text-xs text-muted">Uptime {label}</div>
              <div className={`text-2xl font-semibold mt-1 tabular-nums ${uptimeTone(p.uptime[k])}`}>{fmtPct(p.uptime[k])}</div>
              <div className="text-xxs text-muted mt-0.5">avg {fmtMs(p.avg_ms[k])}</div>
            </div>
          ))}
        </div>

        {p.kind === "push" && (
          <Card title="Push URL" flush={false} actions={canEdit && <button className="btn btn-ghost px-2 py-1" onClick={regenerate}><Icon name="refresh" className="w-3.5 h-3.5" /> New URL</button>}>
            <div className="text-sm text-fg2">Your job calls a secret URL (shown once when it was created) with <code className="font-mono text-xs">?status=up|down&amp;msg=…&amp;ping=…</code>.
              DOWN when nothing arrives within {p.interval_s}s + {p.config.grace_s ?? 30}s grace. Lost the URL? Create a new one.</div>
          </Card>
        )}
        <Card title="Response time" actions={<AddToDashboard probeId={p.id} preset={icmp ? "probe_latency" : "probe_response"} />}>
          <div className="p-3">
            {icmp
              ? <MetricChart probeId={p.id} range={range} metrics={[{ name: "ping_avg", label: "avg" }]} format={FORMATS.ms} area={false}
                  band={{ min: "ping_min", max: "ping_max", label: "min–max" }} height={260} />
              : <MetricChart probeId={p.id} range={range} metrics={[{ name: "response_ms", label: "response" }]} format={FORMATS.ms} area={false}
                  band={{ min: "response_ms", max: "response_ms", label: "min–max" }} height={260} />}
          </div>
        </Card>

        <div className={`grid gap-4 ${p.cert ? "lg:grid-cols-2" : ""}`}>
          {p.cert && <CertPanel p={p} />}
          <Card title="Checks">
            <table className="tbl">
              <thead><tr><th>State</th><th>Service</th><th>Output</th><th>Since</th></tr></thead>
              <tbody>
                {p.services.map((s) => (
                  <tr key={s.id}><td><StateBadge state={s.state} small /></td><td className="text-strong">{s.name}</td>
                    <td className="text-xs text-fg2">{s.output}</td><td className="text-xs text-muted">{fmtAgo(s.last_change)}</td></tr>
                ))}
                {!p.services.length && <tr><td colSpan={4}><Empty>Waiting for the first check…</Empty></td></tr>}
              </tbody>
            </table>
          </Card>
        </div>
        {icmp && (
          <div className="grid lg:grid-cols-2 gap-4">
            <Card title="Packet loss" actions={<AddToDashboard probeId={p.id} preset="probe_loss" />}>
              <div className="p-3"><MetricChart probeId={p.id} range={range} metrics={[{ name: "ping_loss", label: "loss" }]} format={FORMATS.pct} height={200} /></div>
            </Card>
            <Card title="Jitter">
              <div className="p-3"><MetricChart probeId={p.id} range={range} metrics={[{ name: "ping_jitter", label: "jitter" }]} format={FORMATS.ms} area={false} height={200} /></div>
            </Card>
          </div>
        )}
        <Card title="Recent events"><div className="p-0"><EventsTab deviceId={p.device_id} /></div></Card>
      </Page>
      {editing && <ProbeForm initial={p} onClose={() => setEditing(false)} />}
      {pushUrl && <PushUrlModal url={pushUrl} onClose={() => setPushUrl(null)} />}
    </>
  );
}
