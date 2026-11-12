/** Setup → Terminal access: who gets which rights, preparing servers, accounts NETsync created, session audit. */
import { useState } from "react";
import { Link } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api, Device, fmtAgo, Group } from "../api";
import { Icon } from "../components/Icon";
import { Page, PageHeader } from "../components/Layout";
import { Card, Empty } from "../components/ui";
import { DesktopClients, TerminalSessionRow, useTerminalStatus } from "./TerminalPage";

interface AdminInfo {
  plugin: string; plugin_status: string; public_key: string;
  host_keys: { target: string; fingerprint: string; added: number }[];
  accounts: { target: string; account: string; device_id: number | null; hostname: string; level: string; created: number; last_login: number }[];
  pending_removals: { target: string; account: string; tries: number; last_error: string | null }[];
}
type GroupT = Group & { terminal_access?: string };

const LEVELS: [string, string, string][] = [
  ["none", "No terminal", ""],
  ["read", "Read-only", "normal account, can read logs; no sudo"],
  ["write", "Read and write", "sudo for services, packages, journal, reboot"],
  ["full", "Full", "full sudo"],
];
const ts = (s: number) => fmtAgo(new Date(s * 1000).toISOString());

export default function TerminalSetup() {
  const qc = useQueryClient();
  const status = useTerminalStatus();
  const { data: groups = [] } = useQuery({ queryKey: ["groups"], queryFn: () => api<GroupT[]>("/groups") });
  const { data: devices = [] } = useQuery({ queryKey: ["devices"], queryFn: () => api<Device[]>("/devices") });
  const info = useQuery({ queryKey: ["terminal-admin"], queryFn: () => api<AdminInfo>("/terminal/admin"), enabled: !!status?.plugin, retry: false });
  const { data: sessions = [] } = useQuery({ queryKey: ["terminal-sessions", "all"], queryFn: () => api<TerminalSessionRow[]>("/terminal/sessions?limit=200"), refetchInterval: 30_000 });
  const [source, setSource] = useState(() => location.hostname);
  const [script, setScript] = useState("");
  const [copied, setCopied] = useState(false);
  const [checkId, setCheckId] = useState<number | "">("");
  const [checkOut, setCheckOut] = useState<{ ok: boolean; error?: string; version?: number } | null>(null);
  const [err, setErr] = useState("");

  const setLevel = async (g: GroupT, level: string) => {
    setErr("");
    try { await api(`/groups/${g.id}`, { method: "PATCH", body: { terminal_access: level } }); qc.invalidateQueries({ queryKey: ["groups"] }); }
    catch (x: any) { setErr(x.message); }
  };
  const generate = async () => {
    setErr(""); setScript("");
    try { setScript((await api<{ script: string }>("/terminal/admin/setup", { body: { source } })).script); } catch (x: any) { setErr(x.message); }
  };
  const download = () => {
    const url = URL.createObjectURL(new Blob([script], { type: "text/x-sh" }));
    const a = document.createElement("a");
    a.href = url; a.download = "netsync-terminal-setup.sh"; a.click();
    URL.revokeObjectURL(url);
  };
  const check = async () => {
    if (!checkId) return;
    setCheckOut(null);
    try { setCheckOut(await api("/terminal/admin/check", { body: { device_id: checkId } })); } catch (x: any) { setCheckOut({ ok: false, error: x.message }); }
  };
  const act = async (path: string, body: object) => {
    setErr("");
    try { await api(path, { body }); qc.invalidateQueries({ queryKey: ["terminal-admin"] }); } catch (x: any) { setErr(x.message); }
  };

  return (
    <Page>
      <PageHeader title="Terminal access" sub="SSH terminals inside NETsync: every user gets their own ns-<user> account on each server, with rights from their groups." />
      {status && !status.plugin && (
        <Empty>Install the <b>SSH terminal</b> plugin first: <Link to="/setup/store" className="text-accent underline">Plugin store</Link></Empty>
      )}
      {err && <div className="text-sm text-crit">{err}</div>}

      <Card title="Rights per group" flush={false}>
        <p className="text-sm text-muted mb-3">Members get this level on the group's devices (the best one if they share several groups). Admins always have full access; viewers at most read-only.
          Changes apply at the next login.</p>
        {groups.length === 0 ? <div className="text-sm text-muted">No groups yet (Users &amp; groups).</div> : (
          <table className="table">
            <thead><tr><th>Group</th><th>Terminal</th><th className="hidden md:table-cell">On the server</th></tr></thead>
            <tbody>
              {groups.map((g) => {
                const lvl = g.terminal_access ?? "none";
                return (
                  <tr key={g.id}>
                    <td className="text-strong">{g.name}</td>
                    <td>
                      <select className="input h-8" value={lvl} onChange={(e) => setLevel(g, e.target.value)}>
                        {LEVELS.map(([k, l]) => <option key={k} value={k}>{l}</option>)}
                      </select>
                    </td>
                    <td className="hidden md:table-cell text-xs text-muted">{LEVELS.find(([k]) => k === lvl)?.[2]}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </Card>

      {status?.plugin && (
        <Card title="Prepare a server" flush={false}>
          <ol className="text-sm text-fg2 list-decimal pl-5 space-y-1 mb-3">
            <li>Generate the setup script below. NETsync must reach the server from the address you enter (as the server sees it).</li>
            <li>Run it once as root on each Linux server: <code>sudo bash netsync-terminal-setup.sh</code>. It installs sudo if needed.</li>
            <li>It adds a <code>netsync</code> account whose key works only from that address and can only manage <code>ns-*</code> accounts,
              the groups <code>netsync-users / netsync-write / netsync-full</code>, and lets ns-* accounts log in with a password only through NETsync.</li>
          </ol>
          <div className="flex flex-wrap items-end gap-2">
            <label className="text-sm">NETsync address seen by servers<input className="input mt-1 w-56 font-mono" value={source} onChange={(e) => setSource(e.target.value)} /></label>
            <button className="btn btn-primary" onClick={generate}>Generate setup script</button>
            {script && <>
              <button className="btn" onClick={download}><Icon name="arrow" className="w-3.5 h-3.5 rotate-90" /> Download</button>
              <button className="btn" onClick={() => navigator.clipboard.writeText(script).then(() => { setCopied(true); setTimeout(() => setCopied(false), 1500); })}>{copied ? "Copied" : "Copy"}</button>
            </>}
          </div>
          {script && <pre className="mt-3 text-[11px] leading-snug bg-inset border border-line rounded-lg p-2 max-h-80 overflow-auto">{script}</pre>}
          <div className="mt-4 flex flex-wrap items-end gap-2">
            <label className="text-sm">Check a server
              <select className="input mt-1 w-64" value={checkId} onChange={(e) => setCheckId(e.target.value ? Number(e.target.value) : "")}>
                <option value="">Choose…</option>
                {devices.filter((d) => d.device_type !== "probe").sort((a, b) => a.hostname.localeCompare(b.hostname)).map((d) => <option key={d.id} value={d.id}>{d.hostname}</option>)}
              </select>
            </label>
            <button className="btn" disabled={!checkId} onClick={check}>Check</button>
            {checkOut && <span className={`text-sm ${checkOut.ok ? "text-ok" : "text-crit"}`}>{checkOut.ok ? `Ready (account manager v${checkOut.version})` : checkOut.error}</span>}
          </div>
          {info.data && <div className="mt-4 text-xs text-muted break-all">Gateway key: <code>{info.data.public_key}</code></div>}
        </Card>
      )}

      {info.data && <DesktopClients />}

      {info.data && (
        <>
          <Card title={`Accounts NETsync created (${info.data.accounts.length})`}>
            {info.data.accounts.length === 0 ? <div className="p-4 text-sm text-muted">None yet: an account is created the first time a user opens a terminal on a server.</div> : (
              <table className="table">
                <thead><tr><th>Account</th><th>Server</th><th>Level</th><th>Last login</th><th /></tr></thead>
                <tbody>
                  {info.data.accounts.map((a) => (
                    <tr key={a.target + a.account}>
                      <td className="font-mono text-strong">{a.account}</td><td>{a.hostname} <span className="text-xs text-muted">{a.target}</span></td>
                      <td>{a.level}</td><td className="text-xs text-muted">{ts(a.last_login)}</td>
                      <td className="text-right"><button className="btn h-7 text-crit" onClick={() => confirm(`Remove ${a.account} from every server now?`) && act("/terminal/admin/remove-account", { account: a.account })}>Remove everywhere</button></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
            {info.data.pending_removals.length > 0 && (
              <div className="p-4 border-t border-line text-sm">
                <div className="font-medium text-warn mb-1">Waiting to be removed (retried every 10 minutes)</div>
                {info.data.pending_removals.map((r) => <div key={r.target + r.account} className="text-xs text-muted">{r.account} on {r.target}: {r.tries} tries{r.last_error ? ` · ${r.last_error}` : ""}</div>)}
              </div>
            )}
          </Card>

          <Card title="Trusted server keys">
            {info.data.host_keys.length === 0 ? <div className="p-4 text-sm text-muted">None yet.</div> : (
              <table className="table">
                <thead><tr><th>Server</th><th>Fingerprint</th><th>Since</th><th /></tr></thead>
                <tbody>
                  {info.data.host_keys.map((h) => (
                    <tr key={h.target}>
                      <td>{h.target}</td><td className="font-mono text-xs">{h.fingerprint}</td><td className="text-xs text-muted">{ts(h.added)}</td>
                      <td className="text-right"><button className="btn h-7" title="Use after reinstalling the server" onClick={() => confirm(`Forget the key of ${h.target}? The next connection trusts whatever key it presents.`) && act("/terminal/admin/forget-host", { target: h.target })}>Forget</button></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </Card>
        </>
      )}

      <Card title="Sessions">
        {sessions.length === 0 ? <div className="p-4 text-sm text-muted">No terminal sessions yet.</div> : (
          <table className="table">
            <thead><tr><th>When</th><th>User</th><th>Server</th><th>Level</th><th>Via</th><th>Status</th><th className="hidden lg:table-cell">From</th></tr></thead>
            <tbody>
              {sessions.map((s) => (
                <tr key={s.id}>
                  <td className="text-xs text-muted whitespace-nowrap">{fmtAgo(s.created_at)}</td>
                  <td>{s.username} <span className="text-xs text-muted font-mono">{s.account}</span></td>
                  <td>{s.device_id ? <Link to={`/devices/${s.device_id}`} className="hover:underline">{s.hostname}</Link> : s.hostname}</td>
                  <td>{s.level}</td>
                  <td className="text-xs">{s.via === "ssh" ? "SSH client" : "browser"}</td>
                  <td className="text-xs max-w-[18rem] truncate" title={s.reason ?? ""}>{s.status}{s.reason ? ` · ${s.reason}` : ""}</td>
                  <td className="hidden lg:table-cell text-xs text-muted">{s.client_ip}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Card>
    </Page>
  );
}
