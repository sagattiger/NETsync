import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api, Device } from "../../api";
import { Modal } from "../../components/ui";
import { LogoPicker } from "../dashboards/WidgetEditor";
import { Column, IPB, Row } from "./types";

const GROUPS: [string, string[]][] = [
  ["Service", ["service", "description"]],
  ["Placement", ["hypervisor", "type", "os", "vmid", "ha", "hostname"]],
  ["Addresses", ["ip_mgmt", "ip_wan", "nat", "ip_lan"]],
  ["Names & URLs", ["fqdn_internal", "fqdn_public", "urls_public", "ssl", "urls_internal"]],
  ["Ports", ["http_port", "https_port", "telnet_port", "ssh_port", "winbox"]],
  ["Logins", ["web_user", "web_pass", "os_user", "os_pass", "db_pass", "enable_secret", "aaa"]],
];

/** What the form shows for a stored value. */
function toInput(col: Column, v: any): any {
  if (v === undefined || v === null) return col.type === "service" ? { name: "", logo: null } : "";
  if (col.type === "urls") return (Array.isArray(v) ? v : [v]).join("\n");
  if (col.type === "bool") return v ? "yes" : "no";
  return col.type === "service" || col.type === "device" ? v : String(v);
}

/** Add or edit an entry (admins). Only fields you change are sent, so discovery keeps filling the others. */
export function RowEditor({ row, columns, rows, onClose, onSaved }: {
  row: Row | null; columns: Column[]; rows: Row[]; onClose: () => void; onSaved: () => void;
}) {
  const { data: devices = [] } = useQuery({ queryKey: ["devices"], queryFn: () => api<Device[]>("/devices") });
  const byKey = useMemo(() => Object.fromEntries(columns.map((c) => [c.key, c])), [columns]);
  const [vals, setVals] = useState<Record<string, any>>(() => Object.fromEntries(columns.map((c) => [c.key, toInput(c, row?.values[c.key])])));
  const [dirty, setDirty] = useState<Set<string>>(new Set());
  const [clear, setClear] = useState<Set<string>>(new Set());
  const [sensitive, setSensitive] = useState(row?.sensitive ?? false);
  const [alert, setAlert] = useState<string>(row?.alert_when_down == null ? "inherit" : row.alert_when_down ? "on" : "off");
  const [runsOn, setRunsOn] = useState<number | null>(row?.runs_on_id ?? null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const set = (k: string, v: any) => { setVals((x) => ({ ...x, [k]: v })); setDirty((d) => new Set(d).add(k)); };

  const grouped = new Set(GROUPS.flatMap(([, keys]) => keys));
  const groups: [string, Column[]][] = [
    ...GROUPS.map(([g, keys]) => [g, keys.map((k) => byKey[k]).filter(Boolean)] as [string, Column[]]),
    ["Custom", columns.filter((c) => !grouped.has(c.key))],
  ].filter(([, cs]) => cs.length) as [string, Column[]][];

  function payload(): Record<string, any> {
    const out: Record<string, any> = {};
    for (const k of dirty) {
      const c = byKey[k];
      const v = vals[k];
      if (c.type === "bool") out[k] = v === "" ? null : v === "yes";
      else if (c.type === "service") out[k] = v?.name || v?.logo ? v : null;
      else if (c.type === "device") out[k] = v || null;
      else out[k] = v === "" && c.type !== "secret" ? null : v;
    }
    for (const k of clear) out[k] = null;
    return out;
  }
  async function save() {
    setBusy(true); setError("");
    const body = { values: payload(), sensitive, alert_when_down: alert === "inherit" ? null : alert === "on", runs_on_id: runsOn };
    try {
      await api(row ? `${IPB}/rows/${row.id}` : `${IPB}/rows`, { method: row ? "PUT" : "POST", body });
      onSaved();
    } catch (e: any) { setError(e.message); } finally { setBusy(false); }
  }
  async function remove() {
    if (!row || !confirm("Delete this entry? Its passwords are deleted too.")) return;
    try { await api(`${IPB}/rows/${row.id}`, { method: "DELETE" }); onSaved(); } catch (e: any) { setError(e.message); }
  }
  async function resolve(key: string, keep: "manual" | "discovered") {
    if (!row) return;
    try { await api(`${IPB}/rows/${row.id}/conflicts/${key}`, { body: { keep } }); onSaved(); } catch (e: any) { setError(e.message); }
  }

  const input = (c: Column) => {
    const id = `re-${c.key}`;
    const v = vals[c.key];
    switch (c.type) {
      case "service":
        return <div className="flex gap-2 items-start"><input id={id} className="input flex-1" placeholder="Name" value={v?.name ?? ""} onChange={(e) => set(c.key, { ...v, name: e.target.value })} />
          <div className="w-64"><LogoPicker value={v?.logo} onChange={(logo) => set(c.key, { ...v, logo })} /></div></div>;
      case "device":
        return <select id={id} className="input w-full" value={v?.id ?? ""} onChange={(e) => {
          const d = devices.find((x) => x.id === Number(e.target.value)); set(c.key, d ? { id: d.id, name: d.hostname } : null);
        }}><option value="">—</option>{devices.map((d) => <option key={d.id} value={d.id}>{d.hostname}</option>)}</select>;
      case "bool":
        return <select id={id} className="input w-full" value={v} onChange={(e) => set(c.key, e.target.value)}><option value="">—</option><option value="yes">yes</option><option value="no">no</option></select>;
      case "choice":
        return <select id={id} className="input w-full" value={v} onChange={(e) => set(c.key, e.target.value)}><option value="">—</option>{(c.options ?? []).map((o) => <option key={o}>{o}</option>)}</select>;
      case "urls":
      case "longtext":
        return <textarea id={id} className="input w-full" rows={2} value={v} placeholder={c.type === "urls" ? "One https://… per line" : undefined} onChange={(e) => set(c.key, e.target.value)} />;
      case "secret": {
        const saved = row?.secrets[c.key]?.set && !clear.has(c.key);
        return <div className="flex gap-2 items-center">
          <input id={id} type="password" autoComplete="new-password" className="input flex-1" value={v}
            placeholder={saved ? "Saved - leave empty to keep it" : ""} onChange={(e) => { set(c.key, e.target.value); setClear((s) => { const n = new Set(s); n.delete(c.key); return n; }); }} />
          {saved && <button type="button" className="text-xs text-muted hover:text-crit" onClick={() => { setClear((s) => new Set(s).add(c.key)); set(c.key, ""); }}>Clear</button>}
        </div>;
      }
      default:
        return <input id={id} className={`input w-full ${c.type === "ip" ? "font-mono" : ""}`} inputMode={c.type === "port" || c.type === "number" ? "numeric" : undefined}
          placeholder={c.type === "ip" ? "10.0.0.5 (several: separate with commas)" : undefined} value={v} onChange={(e) => set(c.key, e.target.value)} />;
    }
  };

  return (
    <Modal title={row ? `Edit ${row.values.service?.name || row.values.hostname || `entry #${row.id}`}` : "New entry"} onClose={onClose} wide>
      <div className="space-y-5 max-h-[70vh] overflow-y-auto pr-1">
        {row && Object.keys(row.conflicts ?? {}).length > 0 && (
          <div className="rounded-lg border border-warn/40 bg-warn/5 p-3 space-y-2">
            <div className="text-sm font-medium text-warn">Discovery says something different</div>
            {Object.entries(row.conflicts).map(([k, c]) => (
              <div key={k} className="text-xs flex flex-wrap items-center gap-2">
                <b className="text-strong">{byKey[k]?.label ?? k}</b> yours: <code>{JSON.stringify(c.manual)}</code> · discovered: <code>{JSON.stringify(c.discovered)}</code>
                <button className="btn h-6 text-xs" onClick={() => resolve(k, "manual")}>Keep mine</button>
                <button className="btn h-6 text-xs" onClick={() => resolve(k, "discovered")}>Use discovered</button>
              </div>))}
          </div>
        )}
        {groups.map(([g, cs]) => (
          <fieldset key={g} className="space-y-2">
            <legend className="text-xs font-semibold uppercase tracking-wide text-muted mb-1">{g}</legend>
            <div className="grid sm:grid-cols-2 gap-3">
              {cs.map((c) => (
                <div key={c.key} className={c.type === "service" || c.type === "longtext" || c.type === "urls" ? "sm:col-span-2" : ""}>
                  <label className="label" htmlFor={`re-${c.key}`}>{c.label}{row?.manual_keys.includes(c.key) ? "" : row?.source === "learned" && row.values[c.key] !== undefined ? <span className="text-xxs text-accent ml-1">learned</span> : null}</label>
                  {input(c)}
                </div>))}
            </div>
          </fieldset>
        ))}
        <fieldset className="space-y-2">
          <legend className="text-xs font-semibold uppercase tracking-wide text-muted mb-1">Options</legend>
          <div className="grid sm:grid-cols-2 gap-3">
            <div><label className="label" htmlFor="re-runs">Runs on (shares its IPs)</label>
              <select id="re-runs" className="input w-full" value={runsOn ?? ""} onChange={(e) => setRunsOn(e.target.value ? Number(e.target.value) : null)}>
                <option value="">—</option>{rows.filter((r) => r.id !== row?.id).map((r) => <option key={r.id} value={r.id}>{r.values.service?.name || r.values.hostname || `#${r.id}`}</option>)}
              </select></div>
            <div><label className="label" htmlFor="re-alert">Alert when down</label>
              <select id="re-alert" className="input w-full" value={alert} onChange={(e) => setAlert(e.target.value)}>
                <option value="inherit">As its network says</option><option value="on">On</option><option value="off">Off</option>
              </select></div>
          </div>
          <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={sensitive} onChange={(e) => setSensitive(e.target.checked)} /> 🔒 Sensitive: only admins see this entry</label>
        </fieldset>
      </div>
      {error && <div className="text-crit text-xs mt-3" role="alert">{error}</div>}
      <div className="mt-4 flex items-center justify-between gap-2">
        {row ? <button className="btn text-crit" onClick={remove}>Delete entry</button> : <span />}
        <span className="flex gap-2"><button className="btn" onClick={onClose}>Cancel</button>
          <button className="btn btn-primary" onClick={save} disabled={busy}>{busy ? "Saving…" : "Save"}</button></span>
      </div>
    </Modal>
  );
}
