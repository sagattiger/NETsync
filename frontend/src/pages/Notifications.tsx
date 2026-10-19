import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api, Group } from "../api";
import { PageHeader } from "../components/Layout";
import { Card, Empty, Modal, StateBadge } from "../components/ui";

interface Channel { name: string; label: string; fields: { key: string; label: string; type: string; required?: boolean }[] }
interface NRule { id: number; name: string; channel: string; config: Record<string, string>; min_state: number; notify_recovery: boolean; device_group_id: number | null; enabled: boolean }

export default function Notifications() {
  const qc = useQueryClient();
  const [adding, setAdding] = useState(false);
  const [msg, setMsg] = useState("");
  const { data: rules = [] } = useQuery({ queryKey: ["nrules"], queryFn: () => api<NRule[]>("/notifications") });
  const { data: channels = [] } = useQuery({ queryKey: ["channels"], queryFn: () => api<Channel[]>("/notifications/channels") });
  const { data: groups = [] } = useQuery({ queryKey: ["groups"], queryFn: () => api<Group[]>("/groups") });

  async function test(id: number) {
    setMsg("");
    try { await api(`/notifications/${id}/test`, { method: "POST" }); setMsg("Test notification sent"); }
    catch (e: any) { setMsg(e.message); }
  }
  async function remove(id: number) {
    await api(`/notifications/${id}`, { method: "DELETE" });
    qc.invalidateQueries({ queryKey: ["nrules"] });
  }

  return (
    <>
      <PageHeader title="Notifications" sub="Who gets alerted, how, and for what"
        actions={<button className="btn btn-primary" onClick={() => setAdding(true)}>+ New notification rule</button>} />
      <div className="p-5 space-y-3">
        {msg && <div className="text-xs text-accent">{msg}</div>}
        <Card>
          {!rules.length ? <Empty>No notification rules - nobody is alerted yet</Empty> : (
            <table className="tbl">
              <thead><tr><th>Name</th><th>Channel</th><th>Min state</th><th>Recovery</th><th>Group</th><th></th></tr></thead>
              <tbody>
                {rules.map((r) => (
                  <tr key={r.id}>
                    <td>{r.name}</td><td>{channels.find((c) => c.name === r.channel)?.label ?? r.channel}</td>
                    <td><StateBadge state={r.min_state} small /></td><td>{r.notify_recovery ? "yes" : "no"}</td>
                    <td>{groups.find((g) => g.id === r.device_group_id)?.name ?? "all"}</td>
                    <td className="text-right whitespace-nowrap">
                      <button className="text-xs text-muted hover:text-accent mr-3" onClick={() => test(r.id)}>Send test</button>
                      <button className="text-xs text-muted hover:text-crit" onClick={() => remove(r.id)}>Delete</button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </Card>
      </div>
      {adding && <AddRule channels={channels} groups={groups} onClose={() => { setAdding(false); qc.invalidateQueries({ queryKey: ["nrules"] }); }} />}
    </>
  );
}

function AddRule({ channels, groups, onClose }: { channels: Channel[]; groups: Group[]; onClose: () => void }) {
  const [name, setName] = useState("");
  const [channel, setChannel] = useState(channels[0]?.name ?? "email");
  const [config, setConfig] = useState<Record<string, string>>({});
  const [minState, setMinState] = useState(2);
  const [recovery, setRecovery] = useState(true);
  const [groupId, setGroupId] = useState<number | null>(null);
  const [error, setError] = useState("");
  const ch = channels.find((c) => c.name === channel);

  async function save() {
    try {
      await api("/notifications", { body: { name, channel, config, min_state: minState, notify_recovery: recovery, device_group_id: groupId } });
      onClose();
    } catch (e: any) { setError(e.message); }
  }

  return (
    <Modal title="New notification rule" onClose={onClose}>
      <div className="grid gap-3">
        <div><label className="label">Name</label><input className="input w-full" value={name} onChange={(e) => setName(e.target.value)} /></div>
        <div><label className="label">Channel</label>
          <select className="input w-full" value={channel} onChange={(e) => { setChannel(e.target.value); setConfig({}); }}>
            {channels.map((c) => <option key={c.name} value={c.name}>{c.label}</option>)}
          </select></div>
        {ch?.fields.map((f) => (
          <div key={f.key}><label className="label">{f.label}</label>
            <input className="input w-full" type={f.type === "secret" ? "password" : "text"} value={config[f.key] ?? ""}
              onChange={(e) => setConfig({ ...config, [f.key]: e.target.value })} /></div>
        ))}
        <div className="grid grid-cols-2 gap-3">
          <div><label className="label">Notify from state</label>
            <select className="input w-full" value={minState} onChange={(e) => setMinState(+e.target.value)}>
              <option value={1}>WARN</option><option value={2}>CRIT</option>
            </select></div>
          <div><label className="label">Device group</label>
            <select className="input w-full" value={groupId ?? ""} onChange={(e) => setGroupId(e.target.value ? +e.target.value : null)}>
              <option value="">All devices</option>{groups.map((g) => <option key={g.id} value={g.id}>{g.name}</option>)}
            </select></div>
        </div>
        <label className="flex items-center gap-2 text-xs"><input type="checkbox" checked={recovery} onChange={(e) => setRecovery(e.target.checked)} /> Notify on recovery</label>
      </div>
      {error && <div className="text-crit text-xs mt-3">{error}</div>}
      <div className="mt-4 flex justify-end gap-2">
        <button className="btn" onClick={onClose}>Cancel</button>
        <button className="btn btn-primary" onClick={save} disabled={!name}>Save</button>
      </div>
    </Modal>
  );
}
