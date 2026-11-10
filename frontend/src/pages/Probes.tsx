import { useMemo, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api, fmtAgo, prefs, Probe } from "../api";
import { Icon } from "../components/Icon";
import { Page, PageHeader } from "../components/Layout";
import { Card, Empty, hideLg, hideMd, hideSm } from "../components/ui";
import { KumaImport } from "./probes/KumaImport";
import { ProbeForm } from "./probes/ProbeForm";
import { daysTone, fmtMs, fmtPct, KindIcon, kindMeta, Sparkline, StatusPill, uptimeTone, useMe } from "./probes/shared";

export { ProbeForm } from "./probes/ProbeForm";
export { fmtLoss, fmtMs, Sparkline, useMe } from "./probes/shared";

export async function toggleProbe(p: Probe) {
  return api(`/probes/${p.id}/${p.enabled ? "pause" : "resume"}`, { method: "POST" });
}

const STATES: [string, string][] = [["", "All states"], ["OK", "Up"], ["WARN", "Warning"], ["CRIT", "Down"], ["UNKNOWN", "Pending"], ["PAUSED", "Paused"]];

export default function Probes() {
  const qc = useQueryClient();
  const nav = useNavigate();
  const me = useMe();
  const canEdit = me?.role !== "viewer";
  const [params, setParams] = useSearchParams();
  const kind = params.get("kind") ?? "", tag = params.get("tag") ?? "", state = params.get("state") ?? "";
  const [q, setQ] = useState("");
  const [form, setForm] = useState<{ probe?: Probe } | null>(null);
  const [importing, setImporting] = useState(false);
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const { data: all = [], isLoading } = useQuery({ queryKey: ["probes"], queryFn: () => api<Probe[]>("/probes"), refetchInterval: prefs.refreshMs(30_000) });

  const tags = useMemo(() => [...new Set(all.flatMap((p) => p.tags))].sort(), [all]);
  const kinds = useMemo(() => [...new Set(all.map((p) => p.kind))].sort(), [all]);
  const data = all.filter((p) =>
    (!kind || p.kind === kind) && (!tag || p.tags.includes(tag)) &&
    (!state || (state === "PAUSED" ? !p.enabled : p.enabled && ["OK", "WARN", "CRIT", "UNKNOWN"][p.state] === state)) &&
    (!q || `${p.name} ${p.target} ${p.tags.join(" ")}`.toLowerCase().includes(q.toLowerCase())));
  const setFilter = (k: string, v: string) => { const n = new URLSearchParams(params); if (v) n.set(k, v); else n.delete(k); setParams(n, { replace: true }); };
  const counts = { up: all.filter((p) => p.enabled && p.state <= 1).length, down: all.filter((p) => p.enabled && p.state === 2).length, paused: all.filter((p) => !p.enabled).length };

  const toggleSel = (id: number) => setSelected((s) => { const n = new Set(s); if (n.has(id)) n.delete(id); else n.add(id); return n; });
  const allSel = data.length > 0 && data.every((p) => selected.has(p.id));

  async function bulk(action: "pause" | "resume" | "delete") {
    const ids = [...selected].filter((id) => data.some((p) => p.id === id));
    if (!ids.length) return;
    if (action === "delete" && !confirm(`Delete ${ids.length} probe(s) and their history?`)) return;
    await api("/probes/bulk", { body: { ids, action } });
    setSelected(new Set());
    qc.invalidateQueries({ queryKey: ["probes"] });
  }
  async function toggle(p: Probe) { await toggleProbe(p); qc.invalidateQueries({ queryKey: ["probes"] }); }
  async function remove(p: Probe) {
    if (!confirm(`Delete probe "${p.name}" and its history?`)) return;
    await api(`/probes/${p.id}`, { method: "DELETE" });
    qc.invalidateQueries({ queryKey: ["probes"] });
  }

  return (
    <>
      <PageHeader title="Probes"
        sub={<>{counts.up} up · <span className={counts.down ? "text-crit" : ""}>{counts.down} down</span> · {counts.paused} paused</>}
        actions={canEdit && <>
          <button className="btn" onClick={() => setImporting(true)}>Import from Uptime Kuma</button>
          <button className="btn btn-primary" onClick={() => setForm({})}><Icon name="plus" className="w-3.5 h-3.5" /> New probe</button>
        </>} />
      <Page>
        <div className="flex flex-wrap items-center gap-2">
          <input className="input py-1.5 text-xs w-full sm:w-56" placeholder="Filter name / target / tag…" value={q} onChange={(e) => setQ(e.target.value)} />
          <select className="input py-1.5 text-xs" value={kind} onChange={(e) => setFilter("kind", e.target.value)}>
            <option value="">All kinds</option>{kinds.map((k) => <option key={k} value={k}>{kindMeta(k).label}</option>)}
          </select>
          <select className="input py-1.5 text-xs" value={state} onChange={(e) => setFilter("state", e.target.value)}>
            {STATES.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
          </select>
          {tags.length > 0 && (
            <select className="input py-1.5 text-xs" value={tag} onChange={(e) => setFilter("tag", e.target.value)}>
              <option value="">All tags</option>{tags.map((t) => <option key={t}>{t}</option>)}
            </select>
          )}
          {canEdit && selected.size > 0 && (
            <div className="flex items-center gap-1 ml-auto text-xs">
              <span className="text-muted mr-1">{selected.size} selected</span>
              <button className="btn py-1" onClick={() => bulk("pause")}><Icon name="pause" className="w-3.5 h-3.5" /> Pause</button>
              <button className="btn py-1" onClick={() => bulk("resume")}><Icon name="play" className="w-3.5 h-3.5" /> Resume</button>
              <button className="btn py-1 text-crit hover:bg-crit/10" onClick={() => bulk("delete")}><Icon name="trash" className="w-3.5 h-3.5" /> Delete</button>
            </div>
          )}
        </div>
        <Card>
          {isLoading ? <Empty>Loading…</Empty> : !all.length ? <Empty art="empty-probes">No probes yet. Watch a website, an API, a port, a DNS record or a certificate.</Empty>
            : !data.length ? <Empty>No probes match these filters.</Empty> : (
            <table className="tbl">
              <thead><tr>
                {canEdit && <th className="w-8"><input type="checkbox" checked={allSel} onChange={() => setSelected(allSel ? new Set() : new Set(data.map((p) => p.id)))} /></th>}
                <th>State</th><th>Name</th><th className="text-right">Response</th>
                <th className={hideMd}>Last hour</th><th className={`text-right ${hideSm}`}>24 h</th><th className={`text-right ${hideMd}`}>30 d</th>
                <th className={`text-right ${hideLg}`}>Cert</th><th className={hideLg}>Last check</th><th></th>
              </tr></thead>
              <tbody>
                {data.map((p) => (
                  <tr key={p.id} className={`cursor-pointer ${p.enabled ? "" : "opacity-60"}`} onClick={() => nav(`/probes/${p.id}`)}>
                    {canEdit && <td onClick={(e) => e.stopPropagation()}><input type="checkbox" checked={selected.has(p.id)} onChange={() => toggleSel(p.id)} /></td>}
                    <td><StatusPill enabled={p.enabled} maintenance={p.maintenance} state={p.state} /></td>
                    <td className="max-w-[18rem]">
                      <div className="flex items-center gap-2 min-w-0"><KindIcon kind={p.kind} className="w-3.5 h-3.5 shrink-0" />
                        <Link to={`/probes/${p.id}`} className="font-medium text-strong hover:text-accent truncate" onClick={(e) => e.stopPropagation()}>{p.name}</Link>
                        {p.upside_down && <span className="text-xxs text-muted" title="Upside down">⇅</span>}</div>
                      <div className="text-xs text-muted font-mono truncate">{p.kind === "push" ? "push" : `${p.target}${p.port ? `:${p.port}` : ""}`}</div>
                      {p.tags.length > 0 && <div className="flex flex-wrap gap-1 mt-0.5">{p.tags.map((t) => <span key={t} className="text-xxs px-1.5 rounded bg-chip text-fg2">{t}</span>)}</div>}
                    </td>
                    <td className="text-right tabular-nums text-strong">{fmtMs(p.rtt_ms ?? p.last_response_ms)}</td>
                    <td className={hideMd}><Sparkline points={p.spark} /></td>
                    <td className={`text-right tabular-nums ${hideSm} ${uptimeTone(p.uptime["24h"])}`}>{fmtPct(p.uptime["24h"])}</td>
                    <td className={`text-right tabular-nums ${hideMd} ${uptimeTone(p.uptime["30d"])}`}>{fmtPct(p.uptime["30d"])}</td>
                    <td className={`text-right tabular-nums text-xs ${hideLg} ${daysTone(p.cert_days_left)}`}>{p.cert_days_left != null ? `${Math.floor(p.cert_days_left)} d` : ""}</td>
                    <td className={`text-xs max-w-[14rem] ${hideLg}`}><div className="truncate text-fg2" title={p.last_message ?? ""}>{p.last_message ?? "–"}</div>
                      <div className="text-muted">{p.last_run ? fmtAgo(p.last_run) : "not run yet"}</div></td>
                    <td className="text-right whitespace-nowrap" onClick={(e) => e.stopPropagation()}>
                      {canEdit && <>
                        <button className="btn btn-ghost px-2 py-1" title={p.enabled ? "Pause" : "Resume"} onClick={() => toggle(p)}><Icon name={p.enabled ? "pause" : "play"} className="w-3.5 h-3.5" /></button>
                        <button className="btn btn-ghost px-2 py-1" title="Edit" onClick={() => setForm({ probe: p })}><Icon name="edit" className="w-3.5 h-3.5" /></button>
                        <button className="btn btn-ghost px-2 py-1 text-crit hover:bg-crit/10" title="Delete" onClick={() => remove(p)}><Icon name="trash" className="w-3.5 h-3.5" /></button>
                      </>}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </Card>
      </Page>
      {form && <ProbeForm initial={form.probe} onClose={() => setForm(null)} />}
      {importing && <KumaImport onClose={() => setImporting(false)} />}
    </>
  );
}
