import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api, fmtAgo, Group, Me, prefs, Probe } from "../api";
import { Icon } from "../components/Icon";
import { Page, PageHeader } from "../components/Layout";
import { Card, Empty, hideMd, hideSm, Modal, StateBadge } from "../components/ui";

export const useMe = () => useQuery({ queryKey: ["me"], queryFn: () => api<Me>("/auth/me") }).data;

// Mirrors netsync/probes.py validate_target: an IP address or hostname, nothing else.
const IPV4 = /^(25[0-5]|2[0-4]\d|1?\d?\d)(\.(25[0-5]|2[0-4]\d|1?\d?\d)){3}$/;
const HOST = /^(?=.{1,253}\.?$)(?!-)[A-Za-z0-9-]{1,63}(?<!-)(\.(?!-)[A-Za-z0-9-]{1,63}(?<!-))*\.?$/;
export function targetError(v: string): string | null {
  const t = v.trim();
  if (!t) return "Required";
  if (IPV4.test(t) || (t.includes(":") && /^[0-9a-fA-F:.]+$/.test(t))) return null;
  if (HOST.test(t) && !/^\d+$/.test(t.replace(/\.$/, "").split(".").pop() ?? "")) return null;
  return "Enter an IP address or hostname (no http://, ports or paths)";
}

export const fmtMs = (v: number | null | undefined) => (v == null ? "–" : `${v < 10 ? v.toFixed(2) : v.toFixed(1)} ms`);
export const fmtLoss = (v: number | null | undefined) => (v == null ? "–" : `${v.toFixed(0)}%`);

export function Sparkline({ points, width = 120, height = 28 }: { points: [string, number][]; width?: number; height?: number }) {
  const vs = points.map((p) => p[1]).filter((v) => v != null);
  if (vs.length < 2) return <span className="text-xxs text-muted">–</span>;
  const min = Math.min(...vs), max = Math.max(...vs), span = max - min || 1;
  const d = points.map(([, v], i) => `${(i / (points.length - 1)) * width},${height - 2 - ((v - min) / span) * (height - 4)}`).join(" ");
  return (
    <svg width={width} height={height} className="text-accent overflow-visible" aria-hidden>
      <polyline points={d} fill="none" stroke="currentColor" strokeWidth={1.5} strokeLinejoin="round" strokeLinecap="round" />
    </svg>
  );
}

export function ProbeForm({ initial, onClose, onSaved }: { initial?: Probe; onClose: () => void; onSaved?: (p: Probe) => void }) {
  const qc = useQueryClient();
  const me = useMe();
  const { data: groups = [] } = useQuery({ queryKey: ["groups"], queryFn: () => api<Group[]>("/groups") });
  const [f, setF] = useState({
    name: initial?.name ?? "", target: initial?.target ?? "", interval_s: initial?.interval_s ?? 60,
    count: initial?.count ?? 5, enabled: initial?.enabled ?? true, group_ids: initial?.group_ids ?? [] as number[],
  });
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);
  const tErr = f.target ? targetError(f.target) : null;
  const set = (patch: Partial<typeof f>) => setF((p) => ({ ...p, ...patch }));

  async function save() {
    setError(""); setSaving(true);
    try {
      const body = { ...f, kind: "icmp", target: f.target.trim(), name: f.name.trim() };
      const p = initial ? await api<Probe>(`/probes/${initial.id}`, { method: "PUT", body }) : await api<Probe>("/probes", { body });
      qc.invalidateQueries({ queryKey: ["probes"] });
      qc.invalidateQueries({ queryKey: ["probe", p.id] });
      onSaved?.(p);
      onClose();
    } catch (e: any) { setError(e.message); } finally { setSaving(false); }
  }

  return (
    <Modal title={initial ? "Edit probe" : "New probe"} onClose={onClose}>
      <div className="space-y-4">
        <div className="grid sm:grid-cols-2 gap-4">
          <div><label className="label">Name</label>
            <input className="input w-full" autoFocus maxLength={64} value={f.name} onChange={(e) => set({ name: e.target.value })} placeholder="Google" /></div>
          <div><label className="label">Target (IP or hostname)</label>
            <input className="input w-full font-mono" maxLength={253} value={f.target} onChange={(e) => set({ target: e.target.value })} placeholder="8.8.8.8 or google.com" />
            {tErr && <div className="text-xs text-crit mt-1">{tErr}</div>}</div>
        </div>
        <div className="grid grid-cols-2 gap-4">
          <div><label className="label">Interval</label>
            <select className="input w-full" value={f.interval_s} onChange={(e) => set({ interval_s: +e.target.value })}>
              {[30, 60, 120, 180, 300].map((s) => <option key={s} value={s}>every {s < 60 ? `${s} s` : `${s / 60} min`}</option>)}
            </select></div>
          <div><label className="label">Pings per round</label>
            <input className="input w-full" type="number" min={1} max={20} value={f.count} onChange={(e) => set({ count: Math.max(1, Math.min(20, +e.target.value || 1)) })} /></div>
        </div>
        {groups.length > 0 && (
          <div><label className="label">Device groups {me?.role !== "admin" && "(yours)"}</label>
            <div className="flex flex-wrap gap-2">
              {groups.map((g) => {
                const on = f.group_ids.includes(g.id);
                return (
                  <button key={g.id} onClick={() => set({ group_ids: on ? f.group_ids.filter((x) => x !== g.id) : [...f.group_ids, g.id] })}
                    className={`px-2.5 py-1 rounded-full text-xs border ${on ? "border-accent bg-accent/10 text-accent" : "border-edge text-muted hover:text-strong"}`}>{g.name}</button>
                );
              })}
            </div></div>
        )}
        <label className="flex items-center gap-2 text-sm text-fg cursor-pointer select-none">
          <input type="checkbox" checked={f.enabled} onChange={(e) => set({ enabled: e.target.checked })} /> Enabled
        </label>
        <div className="text-xs text-muted">Ping RTT and Ping loss checks use your threshold rules (checks <code className="font-mono">ping_rtt</code> and <code className="font-mono">ping_loss</code>), so problems and alerts work as for devices.</div>
        {error && <div className="text-xs text-crit">{error}</div>}
        <div className="flex justify-end gap-2">
          <button className="btn" onClick={onClose}>Cancel</button>
          <button className="btn btn-primary" onClick={save} disabled={saving || !f.name.trim() || !!targetError(f.target)}>{saving ? "Saving…" : initial ? "Save" : "Add probe"}</button>
        </div>
      </div>
    </Modal>
  );
}

export async function toggleProbe(p: Probe) {
  return api<Probe>(`/probes/${p.id}`, { method: "PUT", body: {
    name: p.name, target: p.target, kind: p.kind, interval_s: p.interval_s, count: p.count, group_ids: p.group_ids, enabled: !p.enabled,
  } });
}

export default function Probes() {
  const qc = useQueryClient();
  const nav = useNavigate();
  const me = useMe();
  const canEdit = me?.role !== "viewer";
  const [form, setForm] = useState<{ probe?: Probe } | null>(null);
  const { data = [], isLoading } = useQuery({ queryKey: ["probes"], queryFn: () => api<Probe[]>("/probes"), refetchInterval: prefs.refreshMs(30_000) });

  async function remove(p: Probe) {
    if (!confirm(`Delete probe "${p.name}" and its history?`)) return;
    await api(`/probes/${p.id}`, { method: "DELETE" });
    qc.invalidateQueries({ queryKey: ["probes"] });
  }
  async function toggle(p: Probe) {
    await toggleProbe(p);
    qc.invalidateQueries({ queryKey: ["probes"] });
  }

  return (
    <>
      <PageHeader title="Probes" sub="Ping any IP address or hostname: latency, jitter and packet loss"
        actions={canEdit && <button className="btn btn-primary" onClick={() => setForm({})}><Icon name="plus" className="w-3.5 h-3.5" /> New probe</button>} />
      <Page>
        <Card>
          {isLoading ? <Empty>Loading…</Empty> : !data.length ? <Empty>No probes yet. Add one to ping e.g. 8.8.8.8 or google.com.</Empty> : (
            <table className="tbl">
              <thead><tr>
                <th>State</th><th>Name</th><th className={hideSm}>Target</th><th className="text-right">RTT</th><th className="text-right">Loss</th>
                <th className={hideMd}>Last hour</th><th className={hideMd}>Interval</th><th></th>
              </tr></thead>
              <tbody>
                {data.map((p) => (
                  <tr key={p.id} className={`cursor-pointer ${p.enabled ? "" : "opacity-60"}`} onClick={() => nav(`/probes/${p.id}`)}>
                    <td>{p.enabled ? <StateBadge state={p.state} small /> : <span className="text-xxs font-semibold uppercase px-2 py-0.5 rounded-full bg-chip text-muted">paused</span>}</td>
                    <td><Link to={`/probes/${p.id}`} className="font-medium text-strong hover:text-accent" onClick={(e) => e.stopPropagation()}>{p.name}</Link>
                      <div className="text-xs text-muted font-mono sm:hidden">{p.target}</div></td>
                    <td className={`font-mono text-xs text-fg2 ${hideSm}`}>{p.target}</td>
                    <td className="text-right tabular-nums text-strong">{fmtMs(p.rtt_ms)}</td>
                    <td className={`text-right tabular-nums ${p.loss_pct ? "text-warn" : "text-fg2"}`}>{fmtLoss(p.loss_pct)}</td>
                    <td className={hideMd}><Sparkline points={p.spark} /></td>
                    <td className={`text-xs text-fg2 ${hideMd}`}>{p.interval_s}s × {p.count}<div className="text-muted">{p.last_run ? fmtAgo(p.last_run) : "not run yet"}</div></td>
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
    </>
  );
}
