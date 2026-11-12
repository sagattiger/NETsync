/** Terminal: SSH sessions to servers in tabs, side by side with the rest of NETsync. */
import { useCallback, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { api, Device, fmtAgo } from "../api";
import { Icon } from "../components/Icon";
import { Page, PageHeader } from "../components/Layout";
import { Card, Empty } from "../components/ui";
import { TerminalView } from "../components/TerminalView";

export interface TerminalStatus { available: boolean; plugin: string | null; plugin_status: string | null; account: string }
export interface TerminalSessionRow {
  id: string; created_at: string; username: string; account: string; device_id: number | null; hostname: string; level: string;
  status: string; reason: string | null; client_ip: string | null; connected_at: string | null; ended_at: string | null;
  bytes_in: number | null; bytes_out: number | null;
}
export const useTerminalStatus = () =>
  useQuery({ queryKey: ["terminal-status"], queryFn: () => api<TerminalStatus>("/terminal/status"), staleTime: 60_000, retry: false }).data;

interface Tab { key: string; deviceId: number; title: string }

export default function TerminalPage() {
  const status = useTerminalStatus();
  const { data: devices = [] } = useQuery({ queryKey: ["devices"], queryFn: () => api<Device[]>("/devices") });
  const { data: recent = [] } = useQuery({ queryKey: ["terminal-sessions"], queryFn: () => api<TerminalSessionRow[]>("/terminal/sessions?limit=15"), refetchInterval: 30_000 });
  const [tabs, setTabs] = useState<Tab[]>([]);
  const [active, setActive] = useState<string | null>(null);
  const [q, setQ] = useState("");
  const [picking, setPicking] = useState(false);

  const servers = useMemo(() => devices.filter((d) => d.device_type !== "probe" && (!q || `${d.hostname} ${d.ip ?? ""} ${d.os ?? ""}`.toLowerCase().includes(q.toLowerCase())))
    .sort((a, b) => a.hostname.localeCompare(b.hostname)), [devices, q]);

  const open = (d: { id: number; hostname: string }) => {
    const key = `${d.id}-${Date.now()}`;
    setTabs((t) => [...t, { key, deviceId: d.id, title: d.hostname }]);
    setActive(key); setPicking(false); setQ("");
  };
  const close = (key: string) => {
    setTabs((t) => {
      const next = t.filter((x) => x.key !== key);
      if (active === key) setActive(next[next.length - 1]?.key ?? null);
      return next;
    });
  };
  const rename = useCallback((key: string) => (title: string) => setTabs((t) => t.map((x) => (x.key === key ? { ...x, title } : x))), []);

  if (status && !status.available) {
    return (
      <Page>
        <PageHeader title="Terminal" />
        <Empty>
          The SSH terminal plugin is not {status.plugin ? "running" : "installed"}.{" "}
          <Link to="/setup/store" className="text-accent underline">Plugin store</Link>
        </Empty>
      </Page>
    );
  }

  const picker = (
    <div className="card p-3 space-y-2 max-w-xl">
      <input autoFocus className="input w-full" placeholder="Find a server…" value={q} onChange={(e) => setQ(e.target.value)} />
      <div className="max-h-80 overflow-y-auto divide-y divide-line">
        {servers.slice(0, 100).map((d) => (
          <button key={d.id} onClick={() => open(d)} className="w-full flex items-center gap-3 px-2 py-2 text-left hover:bg-active/40 rounded-md">
            <Icon name="server" className="w-4 h-4 text-muted shrink-0" />
            <span className="text-sm text-strong truncate flex-1">{d.hostname}</span>
            <span className="text-xs text-muted truncate">{d.ip}{d.os ? ` · ${d.os}` : ""}</span>
          </button>
        ))}
        {servers.length === 0 && <div className="p-3 text-sm text-muted">No devices match.</div>}
      </div>
    </div>
  );

  return (
    <div className="px-4 sm:px-6 pb-6 space-y-3 h-[calc(100vh-4rem)] flex flex-col">
      <div className="flex items-center gap-1 overflow-x-auto shrink-0 pt-2">
        {tabs.map((t) => (
          <div key={t.key} className={`group flex items-center gap-2 h-9 pl-3 pr-1.5 rounded-lg text-sm cursor-pointer whitespace-nowrap ${active === t.key ? "bg-active text-strong" : "text-muted hover:bg-active/50"}`}
            onClick={() => { setActive(t.key); setPicking(false); }}>
            <Icon name="terminal" className="w-3.5 h-3.5" />{t.title}
            <button className="p-0.5 rounded hover:bg-inset" onClick={(e) => { e.stopPropagation(); close(t.key); }} title="Close"><Icon name="x" className="w-3.5 h-3.5" /></button>
          </div>
        ))}
        <button className="btn h-9" onClick={() => setPicking((p) => !p)}><Icon name="plus" className="w-3.5 h-3.5" /> New session</button>
        <span className="flex-1" />
        <span className="text-xs text-muted hidden md:inline">You log in as <b className="text-fg">{status?.account}</b></span>
      </div>

      {(picking || tabs.length === 0) && (
        <div className="grid lg:grid-cols-2 gap-4 items-start">
          {picker}
          <Card title="Your recent sessions">
            {recent.length === 0 ? <div className="p-4 text-sm text-muted">None yet.</div> : (
              <table className="table">
                <tbody>
                  {recent.map((s) => (
                    <tr key={s.id} className="cursor-pointer" onClick={() => s.device_id && open({ id: s.device_id, hostname: s.hostname })}>
                      <td className="text-strong">{s.hostname}</td>
                      <td className="text-xs text-muted">{s.account} · {s.level}</td>
                      <td className="text-xs text-muted">{fmtAgo(s.created_at)}</td>
                      <td className="text-xs text-muted truncate max-w-[14rem]" title={s.reason ?? ""}>{s.status}{s.reason ? ` · ${s.reason}` : ""}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </Card>
        </div>
      )}

      <div className={`flex-1 min-h-[24rem] relative ${picking || tabs.length === 0 ? "hidden" : ""}`}>
        {tabs.map((t) => (
          <div key={t.key} className={`absolute inset-0 ${active === t.key ? "" : "invisible"}`}>
            <TerminalView deviceId={t.deviceId} className="h-full" onTitle={rename(t.key)} />
          </div>
        ))}
      </div>
    </div>
  );
}
