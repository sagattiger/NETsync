/** Setup → Housekeeping: how long each kind of data is kept, what it costs on disk, and cleanup. */
import { useEffect, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api, fmtAgo, fmtBytes, PluginSettings } from "../api";
import { Icon } from "../components/Icon";
import { Page, PageHeader } from "../components/Layout";
import { Field } from "../components/PluginSettingsModal";
import { Bar, Card, Empty } from "../components/ui";

interface TableRow {
  key: string; label: string; days: number; size: number; oldest: string | null; hypertable: string;
  compressed?: { before: number; after: number };
}
interface LastRun {
  time: string; reason: string; ok: boolean; seconds: number; error?: string;
  backfill?: string[]; policies?: string[]; purged?: Record<string, number>;
}
interface Status {
  settings: Record<string, number>; tables: TableRow[]; database_size: number;
  disk: { total: number; used: number; free: number; pct: number | null }; disk_warning: boolean; last_run: LastRun | null;
}

const fmtDays = (d: number) => (d % 365 === 0 ? `${d / 365} year${d === 365 ? "" : "s"}` : d % 30 === 0 && d >= 60 ? `${d / 30} months` : `${d} days`);

function LastRunBox({ run }: { run: LastRun | null }) {
  if (!run) return <p className="text-xs text-muted">No cleanup has run yet. The worker runs one every 6 hours and whenever the settings change.</p>;
  const purged = Object.entries(run.purged ?? {});
  const notes = [...(run.backfill ?? []), ...(run.policies ?? [])];
  return (
    <div className="text-xs space-y-1.5">
      <div className="flex flex-wrap items-center gap-2">
        <span className={`pill px-2 py-0.5 text-xxs ${run.ok ? "pill-ok" : "pill-crit"}`}>{run.ok ? "OK" : "FAILED"}</span>
        <span className="text-fg">{fmtAgo(run.time)}</span>
        <span className="text-muted">· {run.reason} · {run.seconds} s</span>
      </div>
      {run.error && <div className="text-crit break-words">{run.error}</div>}
      {notes.map((n) => <div key={n} className="text-muted">• {n}</div>)}
      {purged.length > 0
        ? <div className="text-muted">Removed: {purged.map(([k, n]) => `${n.toLocaleString()} ${k}`).join(" · ")}</div>
        : run.ok && <div className="text-muted">Nothing to remove.</div>}
    </div>
  );
}

export default function Housekeeping() {
  const qc = useQueryClient();
  const { data: status } = useQuery({ queryKey: ["housekeeping"], queryFn: () => api<Status>("/plugins/housekeeping/status"), refetchInterval: 30_000 });
  const { data: settings } = useQuery({ queryKey: ["plugin-settings", "housekeeping"], queryFn: () => api<PluginSettings>("/plugins/housekeeping/settings") });
  const [config, setConfig] = useState<Record<string, any>>({});
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const [busy, setBusy] = useState<"save" | "run" | null>(null);
  useEffect(() => { if (settings) setConfig(settings.config); }, [settings]);

  async function save() {
    setBusy("save"); setMsg(null);
    try {
      const saved = await api<PluginSettings>("/plugins/housekeeping/settings", { method: "PUT", body: { enabled: true, config } });
      qc.setQueryData(["plugin-settings", "housekeeping"], saved);
      setMsg({ ok: true, text: "Saved. The worker applies new limits within a minute; data past a shorter limit is removed then." });
      setTimeout(() => qc.invalidateQueries({ queryKey: ["housekeeping"] }), 70_000);
    } catch (e) { setMsg({ ok: false, text: (e as Error).message }); }
    setBusy(null);
  }

  async function runNow() {
    setBusy("run"); setMsg(null);
    const before = status?.last_run?.time;
    try {
      await api("/plugins/housekeeping/run", { method: "POST" });
      const deadline = Date.now() + 5 * 60_000;
      while (Date.now() < deadline) {
        await new Promise((r) => setTimeout(r, 3000));
        const s = await api<Status>("/plugins/housekeeping/status");
        if (s.last_run && s.last_run.time !== before) { qc.setQueryData(["housekeeping"], s); break; }
      }
    } catch (e) { setMsg({ ok: false, text: (e as Error).message }); }
    setBusy(null);
  }

  const sections = settings ? [...new Set(settings.fields.map((f) => f.section ?? "Settings"))] : [];
  return (
    <>
      <PageHeader title="Housekeeping" sub="How long NETsync keeps graphs, logs and events, and how much space they use"
        actions={<button className="btn" disabled={!!busy} onClick={runNow}>
          <Icon name="refresh" className={`w-3.5 h-3.5 ${busy === "run" ? "animate-spin" : ""}`} /> {busy === "run" ? "Cleaning up…" : "Run cleanup now"}
        </button>} />
      <Page>
        {!status ? <Card><Empty>Loading…</Empty></Card> : (
          <div className="grid xl:grid-cols-3 gap-4">
            <div className="xl:col-span-2 space-y-4">
              <Card title="Stored data">
                <table className="tbl">
                  <thead><tr><th>Data</th><th>Kept for</th><th className="hidden sm:table-cell">Oldest</th><th className="text-right">Size</th></tr></thead>
                  <tbody>
                    {status.tables.map((t) => (
                      <tr key={t.key}>
                        <td className="text-strong font-medium">{t.label}</td>
                        <td className="text-fg2 whitespace-nowrap">{fmtDays(t.days)}</td>
                        <td className="text-muted text-xs hidden sm:table-cell whitespace-nowrap">{t.oldest ? fmtAgo(t.oldest) : "–"}</td>
                        <td className="text-right tabular-nums whitespace-nowrap">
                          {fmtBytes(t.size)}
                          {t.compressed && t.compressed.before > 0 && (
                            <div className="text-xxs text-ok">compressed part {fmtBytes(t.compressed.before)} → {fmtBytes(t.compressed.after)}</div>
                          )}
                        </td>
                      </tr>
                    ))}
                    <tr><td className="text-muted">Whole database</td><td /><td className="hidden sm:table-cell" /><td className="text-right tabular-nums font-semibold text-strong">{fmtBytes(status.database_size)}</td></tr>
                  </tbody>
                </table>
              </Card>

              {settings && (
                <Card title="Retention" flush={false}>
                  <div className="space-y-6">
                    {sections.map((sec) => (
                      <fieldset key={sec}>
                        <legend className="text-xs font-semibold uppercase tracking-wider text-muted mb-3">{sec}</legend>
                        <div className="grid sm:grid-cols-2 gap-4">
                          {settings.fields.filter((f) => (f.section ?? "Settings") === sec).map((f) => (
                            <Field key={f.key} f={f} plugin="housekeeping" config={config} set={(k, v) => setConfig((c) => ({ ...c, [k]: v }))} />
                          ))}
                        </div>
                      </fieldset>
                    ))}
                    {msg && <div className={`text-sm rounded-lg p-3 border ${msg.ok ? "border-ok/40 bg-ok/10 text-ok" : "border-crit/40 bg-crit/10 text-crit"}`}>{msg.text}</div>}
                    <div className="flex justify-end">
                      <button className="btn btn-primary" onClick={save} disabled={!!busy}>{busy === "save" ? "Saving…" : "Save"}</button>
                    </div>
                  </div>
                </Card>
              )}
            </div>

            <div className="space-y-4">
              <Card title="Server disk" flush={false}>
                <Bar pct={status.disk.pct} />
                <div className="text-xs text-muted mt-2">{fmtBytes(status.disk.free)} free of {fmtBytes(status.disk.total)}</div>
                {status.disk_warning && (
                  <div className="mt-3 text-xs rounded-lg p-3 border border-warn/40 bg-warn/10 text-warn">
                    The disk is fuller than {status.settings.disk_warn_pct}%. Shorten a retention below, or grow the disk.
                  </div>
                )}
              </Card>
              <Card title="Last cleanup" flush={false}><LastRunBox run={status.last_run} /></Card>
              <Card title="How it works" flush={false}>
                <ul className="text-xs text-muted space-y-1.5 list-disc pl-4">
                  <li>Graphs up to 7 days use every poll; 30-day graphs use hourly averages; 1-year graphs use daily averages.</li>
                  <li>Older detail is compressed, which usually saves about 90%.</li>
                  <li>Deleted devices and probes, components that disappeared and old AI jobs are removed every 6 hours.</li>
                  <li>Pinned event comments are always kept.</li>
                </ul>
              </Card>
            </div>
          </div>
        )}
      </Page>
    </>
  );
}
