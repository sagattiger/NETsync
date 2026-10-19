import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api, Group, Me } from "../api";
import { PageHeader } from "../components/Layout";
import { Card, Empty, Modal } from "../components/ui";

interface Rule {
  id: number; name: string; check: string; device_group_id: number | null; device_id: number | null;
  item_regex: string | null; warn: number | null; crit: number | null; direction: string; priority: number; enabled: boolean;
}

const CHECKS: [string, string][] = [
  ["cpu_util", "CPU utilization (%)"], ["mem_used", "Memory used (%)"], ["storage_used", "Filesystem used (%)"],
  ["if", "Interface utilization (%)"], ["ping_rtt", "Ping RTT (ms)"], ["ping_loss", "Ping packet loss (%)"],
];

export default function Rules() {
  const qc = useQueryClient();
  const [editing, setEditing] = useState<Partial<Rule> | null>(null);
  const { data: me } = useQuery({ queryKey: ["me"], queryFn: () => api<Me>("/auth/me") });
  const { data: rules = [] } = useQuery({ queryKey: ["rules"], queryFn: () => api<Rule[]>("/rules") });
  const { data: defaults = {} } = useQuery({ queryKey: ["rule-defaults"], queryFn: () => api<Record<string, { warn: number; crit: number; direction: string }>>("/rules/defaults") });
  const { data: groups = [] } = useQuery({ queryKey: ["groups"], queryFn: () => api<Group[]>("/groups") });
  const isAdmin = me?.role === "admin";
  const groupName = (id: number | null) => groups.find((g) => g.id === id)?.name ?? "all";

  async function save() {
    if (!editing) return;
    const body = { direction: "above", priority: 100, enabled: true, params: {}, ...editing };
    if (editing.id) await api(`/rules/${editing.id}`, { method: "PUT", body });
    else await api("/rules", { body });
    setEditing(null);
    qc.invalidateQueries({ queryKey: ["rules"] });
  }
  async function remove(id: number) {
    await api(`/rules/${id}`, { method: "DELETE" });
    qc.invalidateQueries({ queryKey: ["rules"] });
  }

  return (
    <>
      <PageHeader title="Threshold rules" sub="First matching rule (lowest priority number) wins; otherwise defaults apply"
        actions={isAdmin && <button className="btn btn-primary" onClick={() => setEditing({ check: "cpu_util", name: "" })}>+ New rule</button>} />
      <div className="px-4 sm:px-6 pb-8 space-y-4">
        <Card title="Rules">
          {!rules.length ? <Empty>No custom rules - defaults are used</Empty> : (
            <table className="tbl">
              <thead><tr><th>Prio</th><th>Name</th><th>Check</th><th>Group</th><th>Item regex</th><th>Warn</th><th>Crit</th><th></th></tr></thead>
              <tbody>
                {rules.map((r) => (
                  <tr key={r.id} className={r.enabled ? "" : "opacity-50"}>
                    <td className="tabular-nums">{r.priority}</td><td>{r.name}</td><td className="font-mono text-xs">{r.check}</td>
                    <td>{groupName(r.device_group_id)}</td><td className="font-mono text-xs">{r.item_regex ?? "*"}</td>
                    <td className="text-warn">{r.direction === "below" ? "≤" : "≥"} {r.warn ?? "-"}</td>
                    <td className="text-crit">{r.direction === "below" ? "≤" : "≥"} {r.crit ?? "-"}</td>
                    <td className="text-right whitespace-nowrap">
                      {isAdmin && <>
                        <button className="text-xs text-muted hover:text-accent mr-3" onClick={() => setEditing(r)}>Edit</button>
                        <button className="text-xs text-muted hover:text-crit" onClick={() => remove(r.id)}>Delete</button>
                      </>}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </Card>
        <Card title="Built-in defaults">
          <table className="tbl">
            <thead><tr><th>Check</th><th>Warn</th><th>Crit</th></tr></thead>
            <tbody>
              {Object.entries(defaults).map(([k, v]) => (
                <tr key={k}><td className="font-mono text-xs">{k}</td><td className="text-warn">{v.warn}</td><td className="text-crit">{v.crit}</td></tr>
              ))}
            </tbody>
          </table>
        </Card>
      </div>
      {editing && (
        <Modal title={editing.id ? "Edit rule" : "New rule"} onClose={() => setEditing(null)}>
          <div className="grid grid-cols-2 gap-3">
            <div className="col-span-2"><label className="label">Name</label>
              <input className="input w-full" value={editing.name ?? ""} onChange={(e) => setEditing({ ...editing, name: e.target.value })} /></div>
            <div><label className="label">Check</label>
              <select className="input w-full" value={editing.check} onChange={(e) => setEditing({ ...editing, check: e.target.value })}>
                {CHECKS.map(([k, l]) => <option key={k} value={k}>{l}</option>)}
              </select></div>
            <div><label className="label">Device group</label>
              <select className="input w-full" value={editing.device_group_id ?? ""} onChange={(e) => setEditing({ ...editing, device_group_id: e.target.value ? +e.target.value : null })}>
                <option value="">All devices</option>
                {groups.map((g) => <option key={g.id} value={g.id}>{g.name}</option>)}
              </select></div>
            <div className="col-span-2"><label className="label">Item regex (service name, optional)</label>
              <input className="input w-full font-mono" placeholder="e.g. Interface (Gi|Te).*" value={editing.item_regex ?? ""}
                onChange={(e) => setEditing({ ...editing, item_regex: e.target.value || null })} /></div>
            <div><label className="label">Warning at</label>
              <input className="input w-full" type="number" value={editing.warn ?? ""} onChange={(e) => setEditing({ ...editing, warn: e.target.value === "" ? null : +e.target.value })} /></div>
            <div><label className="label">Critical at</label>
              <input className="input w-full" type="number" value={editing.crit ?? ""} onChange={(e) => setEditing({ ...editing, crit: e.target.value === "" ? null : +e.target.value })} /></div>
            <div><label className="label">Direction</label>
              <select className="input w-full" value={editing.direction ?? "above"} onChange={(e) => setEditing({ ...editing, direction: e.target.value })}>
                <option value="above">value above limit</option><option value="below">value below limit</option>
              </select></div>
            <div><label className="label">Priority</label>
              <input className="input w-full" type="number" value={editing.priority ?? 100} onChange={(e) => setEditing({ ...editing, priority: +e.target.value })} /></div>
          </div>
          <div className="mt-4 flex justify-end gap-2">
            <button className="btn" onClick={() => setEditing(null)}>Cancel</button>
            <button className="btn btn-primary" onClick={save} disabled={!editing.name}>Save</button>
          </div>
        </Modal>
      )}
    </>
  );
}
