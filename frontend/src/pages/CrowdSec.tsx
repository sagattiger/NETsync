/** CrowdSec plugin page: combined totals, new bans per day, top reasons, each Local API source (status, graphs,
 * masked recent bans) and, for admins, adding / testing / removing sources. Bouncer keys are write-only. */
import { useState } from "react";
import { Link } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api, fmtAgo, prefs } from "../api";
import { Page, PageHeader } from "../components/Layout";
import { MetricChart } from "../components/MetricChart";
import { HBars } from "../components/Charts";
import { Card, Empty, Modal, StateBadge } from "../components/ui";
import PluginSettingsModal from "../components/PluginSettingsModal";
import { useMe } from "./probes/shared";
import { CrowdSecWidgetData, DayBars, fmtInt, scenarioLabel } from "./crowdsec/shared";

interface Source {
  id: number; name: string; enabled: boolean; device_id: number; url?: string; has_key?: boolean;
  last_run: string | null; last_ok: string | null; last_error: string | null; last_ms: number | null;
  stats: { local: number; community: number; total: number; other: number; simulated: number;
    by_origin: Record<string, number>; scenarios: Record<string, number> } | null;
  since: number | null;
  recent: { id: number; ip: string; scenario: string; origin: string }[];
  services: { id: number; name: string; state: string; output: string | null; value: number | null }[];
}
interface Overview {
  sources: Source[];
  combined: Omit<CrowdSecWidgetData, "id" | "type" | "title" | "scenarios"> & { scenarios: { key: string; value: number }[]; other: number };
  interval_s: number;
}
const STATE_NUM: Record<string, number> = { OK: 0, WARN: 1, CRIT: 2, UNKNOWN: 3 };
const MASK = "********";

function SourceForm({ source, onClose }: { source?: Source; onClose: () => void }) {
  const qc = useQueryClient();
  const [f, setF] = useState({ name: source?.name ?? "", url: source?.url ?? "http://", api_key: source ? MASK : "", enabled: source?.enabled ?? true });
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const keyBody = f.api_key && f.api_key !== MASK ? f.api_key : null;

  async function test() {
    setBusy(true); setMsg(null);
    try {
      const r = await api<any>("/plugins/crowdsec/test", { body: { url: f.url, api_key: keyBody, source_id: source?.id ?? null } });
      setMsg(r.ok ? { ok: true, text: `Connected in ${Math.round(r.ms)} ms: ${fmtInt(r.local)} local, ${fmtInt(r.community)} community bans` }
        : { ok: false, text: r.message || "failed" });
    } catch (e: any) { setMsg({ ok: false, text: e.message }); } finally { setBusy(false); }
  }
  async function save() {
    setBusy(true); setMsg(null);
    try {
      const body = { name: f.name, url: f.url, enabled: f.enabled, api_key: keyBody };
      await api(source ? `/plugins/crowdsec/sources/${source.id}` : "/plugins/crowdsec/sources", { method: source ? "PUT" : "POST", body });
      qc.invalidateQueries({ queryKey: ["crowdsec"] });
      onClose();
    } catch (e: any) { setMsg({ ok: false, text: e.message }); } finally { setBusy(false); }
  }
  return (
    <Modal title={source ? "Edit CrowdSec source" : "Add CrowdSec source"} onClose={onClose}>
      <div className="space-y-4">
        <div>
          <label className="label">Name</label>
          <input className="input w-full" maxLength={64} value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} placeholder="e.g. Edge proxy" />
        </div>
        <div>
          <label className="label">LAPI address</label>
          <input className="input w-full" value={f.url} onChange={(e) => setF({ ...f, url: e.target.value })} placeholder="http://crowdsec.lan:8080" />
          <div className="text-xs text-muted mt-1">NETsync reads <code>/v1/decisions</code> here. Never shown on public pages.</div>
        </div>
        <div>
          <label className="label">Bouncer key</label>
          <input className="input w-full font-mono" type="password" autoComplete="new-password" value={f.api_key}
            onFocus={() => f.api_key === MASK && setF({ ...f, api_key: "" })}
            onChange={(e) => setF({ ...f, api_key: e.target.value })} placeholder={source ? "leave as is to keep the stored key" : "from: cscli bouncers add netsync-ro"} />
          <div className="text-xs text-muted mt-1">Read-only: a bouncer key can only read decisions. Stored encrypted and never shown again.</div>
        </div>
        <label className="flex items-center gap-2 text-sm">
          <input type="checkbox" checked={f.enabled} onChange={(e) => setF({ ...f, enabled: e.target.checked })} /> Enabled
        </label>
        {msg && <div className={`text-sm ${msg.ok ? "text-ok" : "text-crit"}`}>{msg.text}</div>}
        <div className="flex justify-end gap-2">
          <button className="btn" disabled={busy || !f.url} onClick={test}>Test</button>
          <button className="btn btn-primary" disabled={busy || !f.name.trim() || !f.url || (!source && !keyBody)} onClick={save}>Save</button>
        </div>
      </div>
    </Modal>
  );
}

function SourceCard({ s, admin, operator, onEdit }: { s: Source; admin: boolean; operator: boolean; onEdit: () => void }) {
  const qc = useQueryClient();
  const lapi = s.services.find((x) => x.name === "LAPI");
  const [running, setRunning] = useState(false);
  async function run() {
    setRunning(true);
    try { await api(`/plugins/crowdsec/sources/${s.id}/run`, { method: "POST" }); } finally { setRunning(false); qc.invalidateQueries({ queryKey: ["crowdsec"] }); }
  }
  async function remove() {
    if (!confirm(`Remove the CrowdSec source "${s.name}" and its history?`)) return;
    await api(`/plugins/crowdsec/sources/${s.id}`, { method: "DELETE" });
    qc.invalidateQueries({ queryKey: ["crowdsec"] });
  }
  return (
    <Card title={<span className="flex items-center gap-2">{s.name}{!s.enabled && <span className="pill text-xxs px-2 py-0.5 bg-chip border-line text-muted">paused</span>}</span>}
      actions={admin && (
        <div className="flex gap-1">
          <button className="btn btn-sm" disabled={running} onClick={run}>{running ? "Reading…" : "Read now"}</button>
          <button className="btn btn-sm" onClick={onEdit}>Edit</button>
          <button className="btn btn-sm" onClick={remove}>Remove</button>
        </div>
      )} flush={false}>
      <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-muted mb-3">
        <StateBadge state={STATE_NUM[lapi?.state ?? "UNKNOWN"]} small label={lapi ? undefined : "pending"} />
        {admin && s.url && <span className="font-mono truncate max-w-[18rem]" title={s.url}>{s.url}</span>}
        <span>last read {s.last_run ? fmtAgo(s.last_run) : "never"}{s.last_ms != null && ` · ${Math.round(s.last_ms)} ms`}</span>
        {s.last_error && <span className="text-crit">{s.last_error}</span>}
        <Link className="link" to={`/devices/${s.device_id}`}>services &amp; graphs</Link>
      </div>
      {s.stats ? (
        <div className="grid sm:grid-cols-4 gap-3 text-xs mb-4">
          {([["Local bans", s.stats.local], ["Community", s.stats.community], ["Other remediations", s.stats.other], ["Simulated", s.stats.simulated]] as [string, number][])
            .map(([l, n]) => <div key={l} className="rounded-lg bg-inset px-3 py-2"><div className="text-muted">{l}</div><div className="text-base font-semibold text-strong tabular-nums">{fmtInt(n)}</div></div>)}
        </div>
      ) : <div className="text-sm text-muted mb-4">No successful read yet.</div>}
      <MetricChart deviceId={s.device_id} range="24h" height={160} area={false}
        metrics={[{ name: "cs_local", label: "local" }, { name: "cs_new", label: "new bans" }]} />
      {operator && s.recent.length > 0 && (
        <details className="mt-3">
          <summary className="text-xs text-muted cursor-pointer">Newest local bans (addresses masked)</summary>
          <table className="tbl mt-2"><tbody>
            {s.recent.slice(0, 10).map((r) => (
              <tr key={r.id}><td className="font-mono text-xs">{r.ip}</td><td className="text-xs">{scenarioLabel(r.scenario)}</td><td className="text-xs text-muted">{r.origin}</td></tr>
            ))}
          </tbody></table>
        </details>
      )}
    </Card>
  );
}

export default function CrowdSec() {
  const me = useMe();
  const admin = me?.role === "admin";
  const operator = admin || me?.role === "operator";
  const [form, setForm] = useState<{ source?: Source } | null>(null);
  const [settings, setSettings] = useState(false);
  const { data, isLoading, error } = useQuery({
    queryKey: ["crowdsec", "overview"], queryFn: () => api<Overview>("/plugins/crowdsec/overview"), refetchInterval: prefs.refreshMs(30_000),
  });
  const c = data?.combined;

  return (
    <>
      <PageHeader title="CrowdSec" sub="Attackers blocked by CrowdSec, read from its Local APIs with read-only bouncer keys"
        actions={admin && (
          <div className="flex gap-2">
            <button className="btn" onClick={() => setSettings(true)}>Settings</button>
            <button className="btn btn-primary" onClick={() => setForm({})}>Add source</button>
          </div>
        )} />
      <Page>
        {error ? <Card><Empty>The CrowdSec plugin is disabled or not installed.</Empty></Card>
          : isLoading || !data ? <Card><Empty>Loading…</Empty></Card>
          : !data.sources.length ? (
            <Card><Empty>No CrowdSec source yet. {admin ? "Add one with a bouncer key (cscli bouncers add netsync-ro)." : "Ask an admin to add one."}</Empty></Card>
          ) : (
            <>
              <div className="grid sm:grid-cols-2 xl:grid-cols-4 gap-4">
                {([["Blocked now (our detection)", c!.active], ["New bans · 24 h", c!.new_24h], ["New bans · 7 days", c!.new_7d], ["Community blocklist", c!.community]] as [string, number | null][])
                  .map(([l, n]) => (
                    <Card key={l} flush={false}>
                      <div className="text-xs text-muted">{l}</div>
                      <div className="text-3xl font-bold text-strong tabular-nums mt-1">{fmtInt(n)}</div>
                    </Card>
                  ))}
              </div>
              {c!.status === "stale" && <div className="text-sm text-warn">No successful read for a while: the numbers are from {c!.updated_at ? new Date(c!.updated_at).toLocaleString() : "–"}.</div>}
              <div className="grid xl:grid-cols-2 gap-4">
                <Card title="New bans per day" flush={false}>
                  {c!.days.length ? <DayBars days={c!.days} /> : <Empty>No data yet</Empty>}
                  <div className="text-xs text-muted mt-2">Counted from {c!.since ? new Date(c!.since).toLocaleDateString() : "the first read"} on. Grey: no data.</div>
                </Card>
                <Card title="Main reasons for the current bans" flush={false}>
                  {c!.scenarios.length
                    ? <HBars items={c!.scenarios.map((s) => ({ label: scenarioLabel(s.key), value: s.value, text: fmtInt(s.value) }))} />
                    : <Empty>No active local bans</Empty>}
                </Card>
              </div>
              {data.sources.map((s) => <SourceCard key={s.id} s={s} admin={admin} operator={operator} onEdit={() => setForm({ source: s })} />)}
              <div className="text-xs text-muted">
                Counts are IP addresses banned, not individual requests. Per-country numbers are not available: CrowdSec decisions
                carry no country, and alerts (which do) need machine credentials that can also write.
              </div>
            </>
          )}
      </Page>
      {form && <SourceForm source={form.source} onClose={() => setForm(null)} />}
      {settings && <PluginSettingsModal name="crowdsec" onClose={() => setSettings(false)} />}
    </>
  );
}
