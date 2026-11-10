import { useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { api } from "../../api";
import { Icon } from "../../components/Icon";
import { Modal } from "../../components/ui";
import { KindIcon, kindMeta } from "./shared";

interface PlanItem {
  name: string; kind: string; kuma_type: string; target: string; port: number | null; interval_s: number;
  retries: number; enabled: boolean; tags: string[]; warnings: string[]; has_secrets: boolean;
}
interface Plan { create: PlanItem[]; skipped: { name: string; type: string | null; reason: string }[]; notifications: { name: string; type: string }[] }
interface Created { id: number; name: string; kind: string; push_url?: string }

/** Uptime Kuma: Settings -> Backup -> Export (JSON). Preview first, then import the selected monitors. */
export function KumaImport({ onClose }: { onClose: () => void }) {
  const qc = useQueryClient();
  const [backup, setBackup] = useState<any>(null);
  const [plan, setPlan] = useState<Plan | null>(null);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [result, setResult] = useState<{ created: Created[] } | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function load(file: File) {
    setError(""); setPlan(null);
    try {
      const data = JSON.parse(await file.text());
      setBusy(true);
      const p = await api<Plan>("/probes/import/kuma/preview", { body: data });
      setBackup(data);
      setPlan(p);
      setSelected(new Set(p.create.map((c) => c.name)));
    } catch (e: any) {
      setError(e instanceof SyntaxError ? "This file is not JSON. Export a backup in Uptime Kuma: Settings → Backup → Export." : e.message);
    } finally { setBusy(false); }
  }

  async function run() {
    setBusy(true); setError("");
    try {
      const r = await api<{ created: Created[] }>("/probes/import/kuma", { body: { backup, names: [...selected] } });
      setResult(r);
      qc.invalidateQueries({ queryKey: ["probes"] });
    } catch (e: any) { setError(e.message); } finally { setBusy(false); }
  }

  const toggle = (n: string) => setSelected((s) => { const x = new Set(s); if (x.has(n)) x.delete(n); else x.add(n); return x; });

  if (result) {
    const pushes = result.created.filter((c) => c.push_url);
    return (
      <Modal title="Import finished" onClose={onClose} wide>
        <div className="space-y-4 text-sm">
          <div className="text-fg">Created <span className="font-semibold text-strong">{result.created.length}</span> probe{result.created.length === 1 ? "" : "s"}.</div>
          {pushes.length > 0 && (
            <div className="space-y-2">
              <div className="rounded-lg border border-warn/40 bg-warn/10 text-warn p-3">New push URLs, shown only once. Update the jobs that called Uptime Kuma.</div>
              {pushes.map((c) => (
                <div key={c.id}><div className="text-xs text-muted">{c.name}</div>
                  <code className="block break-all font-mono text-xs px-3 py-2 rounded-lg bg-inset border border-line text-strong select-all">{c.push_url}</code></div>
              ))}
            </div>
          )}
          <div className="flex justify-end"><button className="btn btn-primary" onClick={onClose}>Done</button></div>
        </div>
      </Modal>
    );
  }

  return (
    <Modal title="Import from Uptime Kuma" onClose={onClose} wide>
      <div className="space-y-4 text-sm">
        {!plan && (
          <>
            <div className="text-fg2">In Uptime Kuma open <span className="text-strong">Settings → Backup → Export</span> and upload the JSON file here.
              You'll see what will be created and what is skipped before anything is saved.</div>
            <label className="block rounded-xl border-2 border-dashed border-edge hover:border-accent p-6 text-center cursor-pointer text-muted hover:text-accent">
              <Icon name="plus" className="w-5 h-5 mx-auto mb-1" />{busy ? "Reading…" : "Choose the backup file (.json)"}
              <input type="file" accept="application/json,.json" className="hidden" onChange={(e) => e.target.files?.[0] && load(e.target.files[0])} />
            </label>
            <div className="text-xs text-muted">Imported: HTTP(S), keyword, JSON query, TCP port, ping, DNS and push monitors (name, interval, retries,
              URL, method, headers, body, accepted codes, keyword, auth). Credentials and headers are stored encrypted. Notification settings are not imported.</div>
          </>
        )}
        {plan && (
          <>
            <div>
              <div className="flex items-center justify-between mb-2">
                <span className="font-medium text-strong">Will be created ({selected.size}/{plan.create.length})</span>
                {plan.create.length > 0 && <button className="text-xs text-muted hover:text-strong" onClick={() => setSelected(selected.size === plan.create.length ? new Set() : new Set(plan.create.map((c) => c.name)))}>
                  {selected.size === plan.create.length ? "Select none" : "Select all"}</button>}
              </div>
              <div className="max-h-72 overflow-y-auto rounded-lg border border-line divide-y divide-line">
                {!plan.create.length && <div className="p-3 text-muted">Nothing to import.</div>}
                {plan.create.map((c) => (
                  <label key={c.name} className="flex items-start gap-3 p-2.5 cursor-pointer hover:bg-inset">
                    <input type="checkbox" className="mt-1" checked={selected.has(c.name)} onChange={() => toggle(c.name)} />
                    <KindIcon kind={c.kind} className="w-4 h-4 mt-0.5" />
                    <div className="min-w-0 flex-1">
                      <div className="text-strong">{c.name} <span className="text-xs text-muted">· {kindMeta(c.kind).label} · every {c.interval_s}s{c.retries > 1 ? ` · ${c.retries} retries` : ""}{!c.enabled ? " · paused" : ""}</span></div>
                      {c.kind !== "push" && <div className="text-xs font-mono text-fg2 truncate">{c.target}{c.port ? `:${c.port}` : ""}</div>}
                      {c.warnings.map((w) => <div key={w} className="text-xs text-warn">{w}</div>)}
                    </div>
                  </label>
                ))}
              </div>
            </div>
            {plan.skipped.length > 0 && (
              <div>
                <div className="font-medium text-strong mb-2">Skipped ({plan.skipped.length})</div>
                <div className="max-h-40 overflow-y-auto rounded-lg border border-line divide-y divide-line">
                  {plan.skipped.map((s, i) => (
                    <div key={i} className="p-2.5 text-xs"><span className="text-strong">{s.name}</span>{s.type && <span className="text-muted"> · {s.type}</span>}
                      <div className="text-muted">{s.reason}</div></div>
                  ))}
                </div>
              </div>
            )}
            {plan.notifications.length > 0 && (
              <div>
                <div className="font-medium text-strong mb-1">Needs setup ({plan.notifications.length})</div>
                <div className="text-xs text-muted mb-2">Notifications are not imported (their tokens and passwords stay in Uptime Kuma). Recreate them under Setup → Notifications.</div>
                <div className="flex flex-wrap gap-2">{plan.notifications.map((n, i) => <span key={i} className="px-2 py-0.5 rounded-full bg-chip text-xs text-fg">{n.name} <span className="text-muted">({n.type})</span></span>)}</div>
              </div>
            )}
          </>
        )}
        {error && <div className="text-xs text-crit">{error}</div>}
        <div className="flex justify-end gap-2">
          {plan && <button className="btn" onClick={() => { setPlan(null); setBackup(null); }}>Choose another file</button>}
          <button className="btn" onClick={onClose}>Cancel</button>
          {plan && <button className="btn btn-primary" disabled={busy || !selected.size} onClick={run}>{busy ? "Importing…" : `Import ${selected.size}`}</button>}
        </div>
      </div>
    </Modal>
  );
}
