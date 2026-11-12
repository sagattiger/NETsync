/** Setup → Plugin store: container plugins from the NETsync catalog, installed with one click. */
import { useEffect, useRef, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../api";
import { Icon } from "../components/Icon";
import { Page, PageHeader } from "../components/Layout";
import { Empty, Modal } from "../components/ui";
import { useMe } from "./probes/shared";

interface StoreEntry {
  name: string; title: string; version: string; author: string; icon: string; description: string;
  permissions: string[]; memory_mb: number; source: { repo: string; ref: string; context: string; dockerfile: string };
  docs: string | null; installed: string | null; update: boolean; foreign: boolean; status: string | null;
  status_detail: string | null; container: { status: string; version: string } | null; job: string | null;
}
interface Job { id: string; name: string; status: "running" | "done" | "error"; log: string[]; error: string | null; plugin_status?: string | null; plugin_detail?: string | null }

const PERMISSION_TEXT: Record<string, string> = {
  tools: "Offer tools to the AI coworker and MCP clients",
  events: "Receive NETsync events (alerts, recoveries, syslog, user removals) as they happen",
  "call:read": "Call NETsync's read-only tools (devices, alerts, metrics, syslog)",
  terminal: "Open SSH terminals for NETsync users, with the rights NETsync signs for each session",
};

function JobLog({ jobId, onDone }: { jobId: string; onDone: () => void }) {
  const { data: job } = useQuery({
    queryKey: ["store-job", jobId], queryFn: () => api<Job>(`/store/jobs/${jobId}`),
    refetchInterval: (q) => (q.state.data && q.state.data.status !== "running" && q.state.data.plugin_status === "online" ? false : 1500),
  });
  const end = useRef<HTMLDivElement>(null);
  useEffect(() => { end.current?.scrollIntoView({ block: "end" }); }, [job?.log.length]);
  const finished = job && job.status !== "running";
  useEffect(() => { if (finished) onDone(); }, [finished, onDone]);
  return (
    <div className="space-y-2">
      <div className="text-sm">
        {!job || job.status === "running" ? <span className="text-muted">Building and starting… this takes a minute or two the first time.</span>
          : job.status === "error" ? <span className="text-crit">Failed: {job.error}</span>
          : job.plugin_status === "online" ? <span className="text-ok">Installed and running.</span>
          : <span className="text-warn">Started, waiting for the plugin to answer… {job.plugin_detail ?? ""}</span>}
      </div>
      <pre className="text-[11px] leading-snug bg-inset border border-line rounded-lg p-2 max-h-72 overflow-auto whitespace-pre-wrap">
        {(job?.log ?? []).join("\n")}<div ref={end} />
      </pre>
    </div>
  );
}

export default function Store() {
  const me = useMe();
  const qc = useQueryClient();
  const isAdmin = me?.role === "admin";
  const { data, error, isLoading } = useQuery({ queryKey: ["store"], queryFn: () => api<{ plugins: StoreEntry[]; installer: boolean }>("/store"), refetchInterval: 15_000 });
  const [installing, setInstalling] = useState<StoreEntry | null>(null);
  const [accepted, setAccepted] = useState(false);
  const [job, setJob] = useState<string | null>(null);
  const [removing, setRemoving] = useState<StoreEntry | null>(null);
  const [dropData, setDropData] = useState(false);
  const [logs, setLogs] = useState<{ name: string; text: string } | null>(null);
  const [err, setErr] = useState("");
  const refresh = () => qc.invalidateQueries({ queryKey: ["store"] });

  async function install(e: StoreEntry) {
    setErr("");
    try {
      const j = await api<Job>(`/store/${e.name}/install`, { body: { accept_permissions: e.permissions } });
      setJob(j.id);
    } catch (x: any) { setErr(x.message); }
  }
  async function remove() {
    if (!removing) return;
    setErr("");
    try {
      await api(`/store/${removing.name}?keep_data=${!dropData}`, { method: "DELETE" });
      setRemoving(null); refresh();
    } catch (x: any) { setErr(x.message); }
  }
  async function showLogs(name: string) {
    try { setLogs({ name, text: (await api<{ logs: string }>(`/store/${name}/logs?tail=300`)).logs }); } catch (x: any) { setErr(x.message); }
  }

  return (
    <Page>
      <PageHeader title="Plugin store" sub="Plugins run in their own containers with only the permissions you accept."
        actions={<button className="btn" onClick={() => api("/store?refresh=true").then(refresh)}><Icon name="refresh" className="w-3.5 h-3.5" /> Refresh catalog</button>} />
      {isAdmin && data && !data.installer && (
        <div className="card p-4 text-sm border-warn/40">
          The installer container is not running, so plugins can't be installed yet. On the NETsync host run:
          <pre className="mt-2 bg-inset rounded-md p-2 text-xs">cd /opt/netsync && docker compose up -d installer</pre>
        </div>
      )}
      {err && <div className="text-sm text-crit">{err}</div>}
      {isLoading && <Empty>Loading the catalog…</Empty>}
      {error && <Empty>{(error as Error).message}</Empty>}
      <div className="grid md:grid-cols-2 xl:grid-cols-3 gap-4">
        {data?.plugins.map((p) => (
          <div key={p.name} className="card p-4 flex flex-col gap-3">
            <div className="flex items-start gap-3">
              <span className="w-10 h-10 rounded-xl bg-accent/15 text-accent flex items-center justify-center shrink-0"><Icon name={p.icon} className="w-5 h-5" /></span>
              <div className="min-w-0 flex-1">
                <div className="font-semibold text-strong">{p.title}</div>
                <div className="text-xs text-muted">v{p.version}{p.author ? ` · ${p.author}` : ""}</div>
              </div>
              {p.installed && (
                <span className={`pill text-xxs px-2 py-0.5 ${p.status === "online" ? "pill-ok" : p.status === "pending" ? "pill-unknown" : "pill-crit"}`}>
                  {p.status === "online" ? `installed v${p.installed}` : p.status ?? "installed"}
                </span>
              )}
            </div>
            <p className="text-sm text-fg2 flex-1">{p.description}</p>
            {p.status && p.status !== "online" && p.status_detail && <div className="text-xs text-crit">{p.status_detail}</div>}
            <div className="flex flex-wrap gap-1.5">
              {p.permissions.map((perm) => <span key={perm} className="pill pill-unknown text-xxs px-2 py-0.5" title={PERMISSION_TEXT[perm]}>{perm}</span>)}
              <span className="pill pill-unknown text-xxs px-2 py-0.5">{p.memory_mb} MB</span>
            </div>
            {isAdmin && (
              <div className="flex flex-wrap gap-2">
                {p.foreign ? <span className="text-xs text-muted">A plugin with this name was registered by hand (AI tools → Container plugins).</span>
                  : !p.installed ? (
                    <button className="btn btn-primary" disabled={!data?.installer} onClick={() => { setInstalling(p); setAccepted(false); setJob(null); }}>
                      <Icon name="plus" className="w-3.5 h-3.5" /> Install
                    </button>
                  ) : (
                    <>
                      {p.update && <button className="btn btn-primary" onClick={() => { setInstalling(p); setAccepted(false); setJob(null); }}>Update to v{p.version}</button>}
                      <button className="btn" onClick={() => api(`/store/${p.name}/restart`, { method: "POST" }).then(refresh).catch((x) => setErr(x.message))}>Restart</button>
                      <button className="btn" onClick={() => showLogs(p.name)}>Logs</button>
                      <button className="btn text-crit" onClick={() => { setRemoving(p); setDropData(false); }}>Remove</button>
                    </>
                  )}
                {p.docs && <a className="btn" href={`https://github.com/${p.source.repo}/blob/${p.source.ref}/${p.docs}`} target="_blank" rel="noreferrer">Docs <Icon name="external" className="w-3 h-3" /></a>}
              </div>
            )}
          </div>
        ))}
      </div>

      {installing && (
        <Modal title={`${installing.installed ? "Update" : "Install"} ${installing.title}`} onClose={() => { setInstalling(null); refresh(); }} wide>
          {!job ? (
            <div className="space-y-4">
              <p className="text-sm text-fg2">NETsync downloads <code>{installing.source.repo}@{installing.source.ref}</code>, builds it and runs it in its own container
                (no privileges, no access to the host, {installing.memory_mb} MB memory).</p>
              <div>
                <div className="text-sm font-medium text-strong mb-1.5">It asks for these permissions</div>
                <ul className="text-sm space-y-1">
                  {installing.permissions.map((perm) => <li key={perm} className="flex gap-2"><Icon name="check" className="w-4 h-4 text-accent shrink-0 mt-0.5" /><span><b>{perm}</b>: {PERMISSION_TEXT[perm] ?? perm}</span></li>)}
                </ul>
              </div>
              <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={accepted} onChange={(e) => setAccepted(e.target.checked)} /> I accept these permissions</label>
              {err && <div className="text-sm text-crit">{err}</div>}
              <div className="flex justify-end gap-2">
                <button className="btn" onClick={() => setInstalling(null)}>Cancel</button>
                <button className="btn btn-primary" disabled={!accepted} onClick={() => install(installing)}>{installing.installed ? "Update" : "Install"}</button>
              </div>
            </div>
          ) : <JobLog jobId={job} onDone={refresh} />}
        </Modal>
      )}

      {removing && (
        <Modal title={`Remove ${removing.title}`} onClose={() => setRemoving(null)}>
          <div className="space-y-4 text-sm">
            <p>The container stops and NETsync forgets the plugin.</p>
            <label className="flex items-center gap-2"><input type="checkbox" checked={dropData} onChange={(e) => setDropData(e.target.checked)} /> Also delete its data (for the SSH terminal: its key, trusted host keys and the list of accounts it created)</label>
            {err && <div className="text-crit">{err}</div>}
            <div className="flex justify-end gap-2"><button className="btn" onClick={() => setRemoving(null)}>Cancel</button><button className="btn btn-primary" onClick={remove}>Remove</button></div>
          </div>
        </Modal>
      )}

      {logs && (
        <Modal title={`Logs · ${logs.name}`} onClose={() => setLogs(null)} wide>
          <pre className="text-[11px] leading-snug bg-inset border border-line rounded-lg p-2 max-h-[60vh] overflow-auto whitespace-pre-wrap">{logs.text || "(empty)"}</pre>
        </Modal>
      )}
    </Page>
  );
}
