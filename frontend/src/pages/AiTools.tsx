/** Setup → AI tools: the tool hub (tools and their policy), approvals, activity log, container plugins, MCP access. */
import { Fragment, ReactNode, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api, fmtAgo } from "../api";
import { Icon } from "../components/Icon";
import { Page, PageHeader } from "../components/Layout";
import { Card, Empty, Modal, Segmented } from "../components/ui";
import { useMe } from "./probes/shared";

interface HubTool {
  name: string; title: string; description: string; plugin: string; risk: "read" | "write";
  mode: "auto" | "approve" | "off"; default_mode: string; inputSchema: { properties?: Record<string, any>; required?: string[] };
}
interface ToolCallRow {
  id: number; created_at: string; tool: string; risk: string; origin: string; actor: string; arguments: Record<string, any>;
  status: string; result: any; error: string | null; duration_ms: number | null; decided_by: string | null; reason: string | null;
}
interface RemotePluginRow {
  id: number; name: string; url: string; enabled: boolean; status: string; status_detail: string | null; last_seen: string | null;
  version: string | null; description: string | null; tools: { name: string; description: string; risk: string }[];
  requested: { key: string; label: string }[]; granted: string[]; secret?: string;
}
interface McpToken {
  id: number; name: string; prefix: string; created_by: string | null; created_at: string; last_used_at: string | null;
  status: string; scopes: { tools?: string[]; write?: boolean }; token?: string;
}

type TabKey = "tools" | "approvals" | "activity" | "plugins" | "mcp";
const STATUS_TONE: Record<string, string> = {
  done: "pill-ok", pending: "pill-warn", running: "pill-unknown", error: "pill-crit", rejected: "pill-unknown",
  online: "pill-ok", offline: "pill-crit", error_: "pill-crit",
};
const pill = (s: string) => <span className={`pill text-xxs px-2 py-0.5 ${STATUS_TONE[s] ?? "pill-unknown"}`}>{s}</span>;
const riskPill = (r: string) => (
  <span className={`pill text-xxs px-2 py-0.5 ${r === "write" ? "pill-warn" : "pill-ok"}`}>{r === "write" ? "write" : "read-only"}</span>
);

function Secret({ label, value, onClose }: { label: string; value: string; onClose: () => void }) {
  const [copied, setCopied] = useState(false);
  return (
    <Modal title={label} onClose={onClose}>
      <p className="text-sm text-fg2">Copy it now: it won't be shown again.</p>
      <div className="mt-3 flex gap-2">
        <code className="input flex-1 font-mono text-xs break-all select-all">{value}</code>
        <button className="btn" onClick={async () => { await navigator.clipboard.writeText(value); setCopied(true); }}>{copied ? "Copied" : "Copy"}</button>
      </div>
      <div className="mt-5 flex justify-end"><button className="btn btn-primary" onClick={onClose}>Done</button></div>
    </Modal>
  );
}

// ---------------------------------------------------------------- tools

function TryTool({ tool, onClose }: { tool: HubTool; onClose: () => void }) {
  const props = Object.entries(tool.inputSchema.properties ?? {});
  const [args, setArgs] = useState<Record<string, string>>({});
  const [out, setOut] = useState<any>(null);
  const [busy, setBusy] = useState(false);
  async function run() {
    setBusy(true);
    const body: Record<string, any> = {};
    for (const [k, spec] of props) {
      const v = args[k];
      if (v === undefined || v === "") continue;
      body[k] = spec.type === "integer" || spec.type === "number" ? Number(v) : spec.type === "boolean" ? v === "true" : v;
    }
    try { setOut(await api(`/tools/${tool.name}/call`, { method: "POST", body: { arguments: body } })); }
    catch (e) { setOut({ status: "error", error: (e as Error).message }); }
    setBusy(false);
  }
  return (
    <Modal title={`Try ${tool.name}`} onClose={onClose} wide>
      <p className="text-xs text-muted mb-4">{tool.description}</p>
      <div className="grid sm:grid-cols-2 gap-3">
        {props.map(([k, spec]) => (
          <div key={k}>
            <label className="label">{k}{tool.inputSchema.required?.includes(k) && " *"}</label>
            {spec.enum ? (
              <select className="input w-full" value={args[k] ?? ""} onChange={(e) => setArgs({ ...args, [k]: e.target.value })}>
                <option value="">{spec.default !== undefined ? `default (${spec.default})` : "–"}</option>
                {spec.enum.map((o: any) => <option key={String(o)} value={String(o)}>{String(o)}</option>)}
              </select>
            ) : spec.type === "boolean" ? (
              <select className="input w-full" value={args[k] ?? ""} onChange={(e) => setArgs({ ...args, [k]: e.target.value })}>
                <option value="">default ({String(spec.default ?? false)})</option><option value="true">true</option><option value="false">false</option>
              </select>
            ) : (
              <input className="input w-full" value={args[k] ?? ""} placeholder={spec.default !== undefined ? `default ${spec.default}` : spec.description ?? ""}
                onChange={(e) => setArgs({ ...args, [k]: e.target.value })} />
            )}
          </div>
        ))}
      </div>
      {out && <pre className="mt-4 p-3 rounded-lg bg-inset border border-line text-xs overflow-auto max-h-80">{JSON.stringify(out, null, 2)}</pre>}
      <div className="mt-5 flex justify-end gap-2">
        <button className="btn" onClick={onClose}>Close</button>
        <button className="btn btn-primary" onClick={run} disabled={busy}>{busy ? "Running…" : tool.risk === "write" ? "Request" : "Run"}</button>
      </div>
    </Modal>
  );
}

function ToolsTab({ isAdmin }: { isAdmin: boolean }) {
  const qc = useQueryClient();
  const { data: tools } = useQuery({ queryKey: ["hub-tools"], queryFn: () => api<HubTool[]>("/tools") });
  const [trying, setTrying] = useState<HubTool | null>(null);
  if (!tools) return <Card><Empty>Loading…</Empty></Card>;
  const plugins = [...new Set(tools.map((t) => t.plugin))];
  async function setMode(t: HubTool, mode: string) {
    await api(`/tools/${t.name}/policy`, { method: "PUT", body: { mode } });
    qc.invalidateQueries({ queryKey: ["hub-tools"] });
  }
  return (
    <>
      {plugins.map((p) => (
        <Card key={p} title={p === "netsync" ? "NETsync (built in)" : `Plugin · ${p}`}>
          <table className="tbl"><tbody>
            {tools.filter((t) => t.plugin === p).map((t) => (
              <tr key={t.name}>
                <td className="align-top">
                  <div className="flex flex-wrap items-center gap-2"><span className="font-mono text-xs text-strong">{t.name}</span>{riskPill(t.risk)}</div>
                  <div className="text-xs text-muted mt-1 max-w-2xl">{t.description}</div>
                </td>
                <td className="w-0 whitespace-nowrap align-top">
                  {isAdmin ? (
                    <Segmented value={t.mode} onChange={(m) => setMode(t, m)}
                      options={[["auto", "Automatic"], ["approve", "Approval"], ["off", "Off"]]} />
                  ) : <span className="text-xs text-muted">{t.mode}</span>}
                </td>
                <td className="w-0 align-top"><button className="btn" disabled={t.mode === "off"} onClick={() => setTrying(t)}>Try</button></td>
              </tr>
            ))}
          </tbody></table>
        </Card>
      ))}
      <p className="text-xs text-muted">Read-only tools run automatically; tools that change something wait for approval unless set to automatic. Every call is in the activity log.</p>
      {trying && <TryTool tool={trying} onClose={() => setTrying(null)} />}
    </>
  );
}

// ---------------------------------------------------------------- calls

function CallsTable({ rows, actions }: { rows: ToolCallRow[]; actions?: (c: ToolCallRow) => ReactNode }) {
  const [open, setOpen] = useState<number | null>(null);
  if (!rows.length) return <Empty>Nothing here</Empty>;
  return (
    <table className="tbl">
      <thead><tr><th>When</th><th>Tool</th><th className="hidden md:table-cell">By</th><th>Status</th>{actions && <th />}</tr></thead>
      <tbody>
        {rows.map((c) => (
          <Fragment key={c.id}>
            <tr className="cursor-pointer" onClick={() => setOpen(open === c.id ? null : c.id)}>
              <td className="text-xs text-muted whitespace-nowrap">#{c.id} · {fmtAgo(c.created_at)}</td>
              <td><span className="font-mono text-xs text-strong">{c.tool}</span> <span className="text-xxs text-muted">{c.origin}</span></td>
              <td className="text-xs text-fg2 hidden md:table-cell">{c.actor}{c.decided_by && <span className="text-muted"> · approved by {c.decided_by}</span>}</td>
              <td className="whitespace-nowrap">{pill(c.status)}{c.duration_ms != null && <span className="text-xxs text-muted ml-1.5">{c.duration_ms} ms</span>}</td>
              {actions && <td className="w-0 whitespace-nowrap" onClick={(e) => e.stopPropagation()}>{actions(c)}</td>}
            </tr>
            {open === c.id && (
              <tr><td colSpan={actions ? 5 : 4} className="bg-inset/40">
                {c.reason && <div className="text-xs text-fg2 mb-2">Reason: {c.reason}</div>}
                <div className="grid lg:grid-cols-2 gap-3 text-xs">
                  <div><div className="text-muted mb-1">Arguments</div><pre className="p-2 rounded bg-surface border border-line overflow-auto max-h-60">{JSON.stringify(c.arguments, null, 2)}</pre></div>
                  <div><div className="text-muted mb-1">{c.error ? "Error" : "Result"}</div>
                    <pre className={`p-2 rounded bg-surface border border-line overflow-auto max-h-60 ${c.error ? "text-crit" : ""}`}>{c.error ?? JSON.stringify(c.result, null, 2) ?? "–"}</pre></div>
                </div>
              </td></tr>
            )}
          </Fragment>
        ))}
      </tbody>
    </table>
  );
}

function ApprovalsTab() {
  const qc = useQueryClient();
  const { data = [] } = useQuery({ queryKey: ["tool-calls", "pending"], queryFn: () => api<ToolCallRow[]>("/tool-calls?status=pending"), refetchInterval: 10_000 });
  const [busy, setBusy] = useState<number | null>(null);
  async function decide(c: ToolCallRow, d: "approve" | "reject") {
    if (d === "approve" && !confirm(`Run ${c.tool} with these arguments?\n\n${JSON.stringify(c.arguments, null, 2)}`)) return;
    setBusy(c.id);
    try { await api(`/tool-calls/${c.id}/${d}`, { method: "POST" }); } catch (e) { alert((e as Error).message); }
    setBusy(null);
    qc.invalidateQueries({ queryKey: ["tool-calls"] });
  }
  return (
    <Card title={`Waiting for approval · ${data.length}`}>
      <CallsTable rows={data} actions={(c) => (
        <div className="flex gap-1.5">
          <button className="btn text-crit" disabled={busy === c.id} onClick={() => decide(c, "reject")}>Reject</button>
          <button className="btn btn-primary" disabled={busy === c.id} onClick={() => decide(c, "approve")}>Approve & run</button>
        </div>
      )} />
    </Card>
  );
}

function ActivityTab() {
  const { data = [] } = useQuery({ queryKey: ["tool-calls", "all"], queryFn: () => api<ToolCallRow[]>("/tool-calls?limit=200"), refetchInterval: 15_000 });
  return <Card title="Activity (last 200 calls)"><CallsTable rows={data} /></Card>;
}

// ---------------------------------------------------------------- container plugins

function PluginsTab() {
  const qc = useQueryClient();
  const { data = [] } = useQuery({ queryKey: ["remote-plugins"], queryFn: () => api<RemotePluginRow[]>("/remote-plugins"), refetchInterval: 20_000 });
  const [form, setForm] = useState({ name: "", url: "" });
  const [secret, setSecret] = useState<{ label: string; value: string } | null>(null);
  const [err, setErr] = useState("");
  const refresh = () => { qc.invalidateQueries({ queryKey: ["remote-plugins"] }); qc.invalidateQueries({ queryKey: ["hub-tools"] }); };
  async function add() {
    setErr("");
    try {
      const p = await api<RemotePluginRow>("/remote-plugins", { method: "POST", body: form });
      setSecret({ label: `Secret for ${p.name}`, value: p.secret! });
      setForm({ name: "", url: "" });
      refresh();
    } catch (e) { setErr((e as Error).message); }
  }
  async function update(p: RemotePluginRow, body: Record<string, any>) {
    try { await api(`/remote-plugins/${p.id}`, { method: "PUT", body }); } catch (e) { alert((e as Error).message); }
    refresh();
  }
  async function rotate(p: RemotePluginRow) {
    if (!confirm(`Create a new secret for ${p.name}? The old one stops working.`)) return;
    const r = await api<RemotePluginRow>(`/remote-plugins/${p.id}/rotate-secret`, { method: "POST" });
    setSecret({ label: `New secret for ${p.name}`, value: r.secret! });
    refresh();
  }
  async function remove(p: RemotePluginRow) {
    if (!confirm(`Remove plugin ${p.name}? Its tools disappear from NETsync; the container keeps running.`)) return;
    await api(`/remote-plugins/${p.id}`, { method: "DELETE" });
    refresh();
  }
  return (
    <>
      <Card title="Add a container plugin" flush={false}>
        <div className="grid sm:grid-cols-[12rem_1fr_auto] gap-3 items-end">
          <div><label className="label">Name</label><input className="input w-full" placeholder="ssh" value={form.name}
            onChange={(e) => setForm({ ...form, name: e.target.value.toLowerCase() })} /></div>
          <div><label className="label">URL NETsync uses to reach it</label><input className="input w-full" placeholder="http://netsync-ssh:8080"
            value={form.url} onChange={(e) => setForm({ ...form, url: e.target.value })} /></div>
          <button className="btn btn-primary" disabled={!form.name || !form.url} onClick={add}><Icon name="plus" className="w-3.5 h-3.5" /> Add</button>
        </div>
        {err && <div className="text-xs text-crit mt-2">{err}</div>}
        <p className="text-xs text-muted mt-3">NETsync shows a secret once: start the plugin with it as <code>NETSYNC_PLUGIN_SECRET</code>. See docs/PLUGIN-PROTOCOL.md.</p>
      </Card>
      {data.length === 0 ? <Card><Empty>No container plugins yet</Empty></Card> : data.map((p) => (
        <Card key={p.id} title={<span className="flex items-center gap-2">{p.name} {pill(p.status === "error" ? "error_" : p.status)}{p.version && <span className="text-xs text-muted font-normal">v{p.version}</span>}</span>}
          actions={<>
            <button className="btn" onClick={() => update(p, { enabled: !p.enabled })}>{p.enabled ? "Disable" : "Enable"}</button>
            <button className="btn" onClick={() => rotate(p)}>New secret</button>
            <button className="btn text-crit" onClick={() => remove(p)}>Remove</button>
          </>} flush={false}>
          <div className="text-xs text-muted font-mono">{p.url}</div>
          {p.description && <div className="text-sm text-fg2 mt-1">{p.description}</div>}
          {p.status_detail && <div className="text-xs text-crit mt-2">{p.status_detail}</div>}
          {p.last_seen && <div className="text-xs text-muted mt-1">last seen {fmtAgo(p.last_seen)}</div>}
          {p.requested.length > 0 && (
            <div className="mt-4">
              <div className="text-xs font-semibold text-strong mb-2">Permissions it asks for</div>
              <div className="space-y-1.5">
                {p.requested.map((r) => (
                  <label key={r.key} className="flex items-center gap-2 text-sm cursor-pointer">
                    <input type="checkbox" className="accent-accent" checked={p.granted.includes(r.key)}
                      onChange={(e) => update(p, { granted: e.target.checked ? [...p.granted, r.key] : p.granted.filter((g) => g !== r.key) })} />
                    <span className="font-mono text-xs text-fg">{r.key}</span><span className="text-xs text-muted">{r.label}</span>
                  </label>
                ))}
              </div>
            </div>
          )}
          {p.tools.length > 0 && (
            <div className="mt-4 text-xs">
              <div className="font-semibold text-strong mb-1.5">Tools</div>
              <ul className="space-y-1">{p.tools.map((t) => (
                <li key={t.name} className="flex flex-wrap items-center gap-2"><span className="font-mono">{p.name}__{t.name}</span>{riskPill(t.risk)}<span className="text-muted">{t.description}</span></li>
              ))}</ul>
            </div>
          )}
        </Card>
      ))}
      {secret && <Secret label={secret.label} value={secret.value} onClose={() => setSecret(null)} />}
    </>
  );
}

// ---------------------------------------------------------------- MCP access

function McpTab() {
  const qc = useQueryClient();
  const { data = [] } = useQuery({ queryKey: ["mcp-tokens"], queryFn: () => api<McpToken[]>("/mcp-tokens") });
  const [form, setForm] = useState({ name: "", tools: "netsync__*", write: false });
  const [secret, setSecret] = useState<string | null>(null);
  const url = `${location.origin}/api/mcp`;
  async function create() {
    const t = await api<McpToken>("/mcp-tokens", { method: "POST", body: {
      name: form.name, write: form.write, tools: form.tools.split(",").map((s) => s.trim()).filter(Boolean) } });
    setSecret(t.token!);
    setForm({ name: "", tools: "netsync__*", write: false });
    qc.invalidateQueries({ queryKey: ["mcp-tokens"] });
  }
  async function revoke(t: McpToken) {
    if (!confirm(`Revoke ${t.name}?`)) return;
    await api(`/mcp-tokens/${t.id}`, { method: "DELETE" });
    qc.invalidateQueries({ queryKey: ["mcp-tokens"] });
  }
  return (
    <>
      <Card title="MCP server" flush={false}>
        <div className="text-sm">Endpoint: <code className="font-mono text-xs text-strong select-all">{url}</code></div>
        <p className="text-xs text-muted mt-2">For Claude Desktop, n8n (MCP Client Tool node, HTTP Streamable) and other MCP clients, with a token below as
          <code> Authorization: Bearer nsm_…</code>. Setup examples are in docs/PLUGIN-PROTOCOL.md.</p>
      </Card>
      <Card title="New MCP token" flush={false}>
        <div className="grid sm:grid-cols-[1fr_1fr_auto] gap-3 items-end">
          <div><label className="label">Name</label><input className="input w-full" placeholder="Claude desktop" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} /></div>
          <div><label className="label">Tools (patterns, comma separated)</label><input className="input w-full font-mono text-xs" value={form.tools} onChange={(e) => setForm({ ...form, tools: e.target.value })} /></div>
          <button className="btn btn-primary" disabled={!form.name} onClick={create}>Create</button>
        </div>
        <label className="flex items-start gap-2 mt-3 text-sm cursor-pointer">
          <input type="checkbox" className="accent-accent mt-0.5" checked={form.write} onChange={(e) => setForm({ ...form, write: e.target.checked })} />
          <span>May request write tools<span className="block text-xs text-muted">They still wait for approval unless a tool is set to automatic.</span></span>
        </label>
      </Card>
      <Card title="MCP tokens">
        {!data.length ? <Empty>No MCP tokens</Empty> : (
          <table className="tbl">
            <thead><tr><th>Name</th><th>Scope</th><th className="hidden sm:table-cell">Last used</th><th>Status</th><th /></tr></thead>
            <tbody>{data.map((t) => (
              <tr key={t.id}>
                <td className="text-strong">{t.name}<div className="text-xxs text-muted font-mono">{t.prefix}…</div></td>
                <td className="text-xs font-mono">{(t.scopes.tools ?? []).join(", ")}{t.scopes.write && <span className="ml-1.5">{riskPill("write")}</span>}</td>
                <td className="text-xs text-muted hidden sm:table-cell">{t.last_used_at ? fmtAgo(t.last_used_at) : "never"}</td>
                <td>{pill(t.status === "active" ? "done" : "rejected")}</td>
                <td className="w-0">{t.status === "active" && <button className="btn text-crit" onClick={() => revoke(t)}>Revoke</button>}</td>
              </tr>
            ))}</tbody>
          </table>
        )}
      </Card>
      {secret && <Secret label="MCP token" value={secret} onClose={() => setSecret(null)} />}
    </>
  );
}

export default function AiTools() {
  const me = useMe();
  const isAdmin = me?.role === "admin";
  const { data: pending = [] } = useQuery({ queryKey: ["tool-calls", "pending"], queryFn: () => api<ToolCallRow[]>("/tool-calls?status=pending"),
    refetchInterval: 10_000, enabled: me?.role !== "viewer" && !!me });
  const [tab, setTab] = useState<TabKey>("tools");
  const tabs: [TabKey, string][] = [["tools", "Tools"], ...(me && me.role !== "viewer" ? [["approvals", `Approvals${pending.length ? ` · ${pending.length}` : ""}`], ["activity", "Activity"]] as [TabKey, string][] : []),
    ...(isAdmin ? [["plugins", "Container plugins"], ["mcp", "MCP access"]] as [TabKey, string][] : [])];
  return (
    <>
      <PageHeader title="AI tools" sub="Tools the AI and MCP clients can use, approvals and the activity log" />
      <Page>
        <Segmented value={tab} onChange={setTab} options={tabs} />
        {tab === "tools" && <ToolsTab isAdmin={isAdmin} />}
        {tab === "approvals" && <ApprovalsTab />}
        {tab === "activity" && <ActivityTab />}
        {tab === "plugins" && <PluginsTab />}
        {tab === "mcp" && <McpTab />}
      </Page>
    </>
  );
}
