import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api, fmtAgo, Group } from "../api";
import { PageHeader } from "../components/Layout";
import { Card, Empty, Modal, StateBadge } from "../components/ui";

interface Field { key: string; label: string; type: string; required?: boolean; help?: string }
interface Channel { name: string; label: string; fields: Field[] }
interface ProblemType { key: string; label: string; checks: string[] }
interface NRule {
  id: number; name: string; channel: string; config: Record<string, string>; min_state: number; notify_recovery: boolean;
  device_group_id: number | null; enabled: boolean; problem_types: string[] | null; secrets_set: string[];
  sent_alert: number; sent_recovery: number; sent_failed: number; last_sent_at: string | null; last_error: string | null;
}

export default function Notifications() {
  const qc = useQueryClient();
  const [editing, setEditing] = useState<NRule | "new" | null>(null);
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const [busy, setBusy] = useState<number | null>(null);
  const { data: rules = [] } = useQuery({ queryKey: ["nrules"], queryFn: () => api<NRule[]>("/notifications") });
  const { data: channels = [] } = useQuery({ queryKey: ["channels"], queryFn: () => api<Channel[]>("/notifications/channels") });
  const { data: types = [] } = useQuery({ queryKey: ["problem-types"], queryFn: () => api<ProblemType[]>("/notifications/problem-types") });
  const { data: groups = [] } = useQuery({ queryKey: ["groups"], queryFn: () => api<Group[]>("/groups") });
  const refresh = () => qc.invalidateQueries({ queryKey: ["nrules"] });

  async function test(r: NRule) {
    setMsg(null); setBusy(r.id);
    try { await api(`/notifications/${r.id}/test`, { method: "POST" }); setMsg({ ok: true, text: `Test sent through "${r.name}"` }); }
    catch (e: any) { setMsg({ ok: false, text: `${r.name}: ${e.message}` }); }
    finally { setBusy(null); }
  }
  async function remove(r: NRule) {
    if (!confirm(`Delete the notification rule "${r.name}"?`)) return;
    await api(`/notifications/${r.id}`, { method: "DELETE" });
    refresh();
  }
  const typeLabel = (r: NRule) => !r.problem_types?.length ? "All"
    : r.problem_types.length > 2 ? `${r.problem_types.length} types`
    : r.problem_types.map((k) => types.find((t) => t.key === k)?.label.split(" (")[0] ?? k).join(", ");

  return (
    <>
      <PageHeader title="Notifications" sub="Who gets alerted, how, and for what"
        actions={<button className="btn btn-primary" onClick={() => setEditing("new")}>+ New notification rule</button>} />
      <div className="px-4 sm:px-6 pb-8 space-y-3">
        {msg && <div role="status" className={`text-xs ${msg.ok ? "text-ok" : "text-crit"}`}>{msg.text}</div>}
        <Card>
          {!rules.length ? <Empty>No notification rules - nobody is alerted yet</Empty> : (
            <div className="overflow-x-auto">
              <table className="tbl">
                <thead><tr>
                  <th>Name</th><th>Channel</th><th>Problem types</th><th>Min state</th><th>Recovery</th><th>Group</th>
                  <th title="Notifications sent: alerts, recoveries, failed (tests not counted)">Sent</th><th></th>
                </tr></thead>
                <tbody>
                  {rules.map((r) => (
                    <tr key={r.id} className={r.enabled ? "" : "opacity-60"}>
                      <td className="font-medium text-strong">{r.name}{!r.enabled && <span className="ml-2 text-xxs text-muted">(off)</span>}</td>
                      <td>{channels.find((c) => c.name === r.channel)?.label ?? r.channel}</td>
                      <td className="text-xs" title={r.problem_types?.map((k) => types.find((t) => t.key === k)?.label ?? k).join(", ")}>{typeLabel(r)}</td>
                      <td><StateBadge state={r.min_state} small /></td>
                      <td>{r.notify_recovery ? "yes" : "no"}</td>
                      <td>{groups.find((g) => g.id === r.device_group_id)?.name ?? "all"}</td>
                      <td><Counts r={r} /></td>
                      <td className="text-right whitespace-nowrap">
                        <button className="text-xs text-muted hover:text-accent mr-3" onClick={() => setEditing(r)}>Edit</button>
                        <button className="text-xs text-muted hover:text-accent mr-3 disabled:opacity-50" disabled={busy === r.id} onClick={() => test(r)}>
                          {busy === r.id ? "Sending…" : "Send test"}</button>
                        <button className="text-xs text-muted hover:text-crit" onClick={() => remove(r)}>Delete</button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Card>
      </div>
      {editing && <RuleForm rule={editing === "new" ? null : editing} channels={channels} types={types} groups={groups}
        onClose={() => setEditing(null)} onSaved={() => { setEditing(null); refresh(); }} />}
    </>
  );
}

/** Alerts / recoveries / failed sends, with the last send and the last error on hover. */
function Counts({ r }: { r: NRule }) {
  const title = [`${r.sent_alert} alerts, ${r.sent_recovery} recoveries, ${r.sent_failed} failed`,
    r.last_sent_at ? `last sent ${fmtAgo(r.last_sent_at)}` : "never sent", r.last_error ? `last error: ${r.last_error}` : ""]
    .filter(Boolean).join("\n");
  return (
    <span className="inline-flex items-center gap-2.5 text-xs tabular-nums whitespace-nowrap" title={title}>
      <span className="text-crit" aria-label={`${r.sent_alert} alerts`}>▲ {r.sent_alert}</span>
      <span className="text-ok" aria-label={`${r.sent_recovery} recoveries`}>✓ {r.sent_recovery}</span>
      <span className={r.sent_failed ? "text-warn font-semibold" : "text-muted"} aria-label={`${r.sent_failed} failed`}>✕ {r.sent_failed}</span>
    </span>
  );
}

function RuleForm({ rule, channels, types, groups, onClose, onSaved }: {
  rule: NRule | null; channels: Channel[]; types: ProblemType[]; groups: Group[]; onClose: () => void; onSaved: () => void;
}) {
  const [name, setName] = useState(rule?.name ?? "");
  const [channel, setChannel] = useState(rule?.channel ?? channels[0]?.name ?? "email");
  const [config, setConfig] = useState<Record<string, string>>(rule?.config ?? {});
  const [minState, setMinState] = useState(rule?.min_state ?? 2);
  const [recovery, setRecovery] = useState(rule?.notify_recovery ?? true);
  const [groupId, setGroupId] = useState<number | null>(rule?.device_group_id ?? null);
  const [enabled, setEnabled] = useState(rule?.enabled ?? true);
  const [picked, setPicked] = useState<string[]>(rule?.problem_types ?? []);
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);
  const ch = channels.find((c) => c.name === channel);
  const savedSecret = (key: string) => rule?.channel === channel && rule.secrets_set.includes(key);
  const toggle = (k: string) => setPicked((p) => p.includes(k) ? p.filter((x) => x !== k) : [...p, k]);

  async function save() {
    setSaving(true); setError("");
    const body = { name, channel, config, min_state: minState, notify_recovery: recovery, device_group_id: groupId, enabled,
      problem_types: picked.length ? picked : null };
    try {
      await api(rule ? `/notifications/${rule.id}` : "/notifications", { method: rule ? "PUT" : "POST", body });
      onSaved();
    } catch (e: any) { setError(e.message); } finally { setSaving(false); }
  }

  return (
    <Modal title={rule ? `Edit "${rule.name}"` : "New notification rule"} onClose={onClose} wide>
      <div className="grid gap-3">
        <div className="grid sm:grid-cols-2 gap-3">
          <div><label className="label" htmlFor="nr-name">Name</label>
            <input id="nr-name" className="input w-full" value={name} onChange={(e) => setName(e.target.value)} /></div>
          <div><label className="label" htmlFor="nr-channel">Channel</label>
            <select id="nr-channel" className="input w-full" value={channel} onChange={(e) => { setChannel(e.target.value); setConfig({}); }}>
              {channels.map((c) => <option key={c.name} value={c.name}>{c.label}</option>)}
            </select></div>
        </div>
        {ch?.fields.map((f) => (
          <div key={f.key}><label className="label" htmlFor={`nr-${f.key}`}>{f.label}</label>
            <input id={`nr-${f.key}`} className="input w-full" type={f.type === "secret" ? "password" : "text"} autoComplete="off"
              value={config[f.key] ?? ""} placeholder={savedSecret(f.key) ? "Saved - leave empty to keep it" : undefined}
              onChange={(e) => setConfig({ ...config, [f.key]: e.target.value })} />
            {f.help && <div className="text-xs text-muted mt-1">{f.help}</div>}</div>
        ))}

        <fieldset>
          <legend className="label flex items-center justify-between w-full">
            <span>Problem types</span>
            <span className="text-xs font-normal text-muted">{picked.length ? `${picked.length} selected` : "None ticked = all types"}</span>
          </legend>
          <div className="grid sm:grid-cols-2 gap-x-4 gap-y-1 mt-1">
            {types.map((t) => (
              <label key={t.key} className="flex items-center gap-2 text-xs py-1 cursor-pointer" title={t.checks.length ? `Checks: ${t.checks.join(", ")}` : "Any check not in the other types"}>
                <input type="checkbox" checked={picked.includes(t.key)} onChange={() => toggle(t.key)} /> {t.label}
              </label>
            ))}
          </div>
          {picked.length > 0 && <button type="button" className="text-xs text-muted hover:text-accent mt-1" onClick={() => setPicked([])}>Clear (send all types)</button>}
        </fieldset>

        <div className="grid sm:grid-cols-2 gap-3">
          <div><label className="label" htmlFor="nr-state">Notify from state</label>
            <select id="nr-state" className="input w-full" value={minState} onChange={(e) => setMinState(+e.target.value)}>
              <option value={1}>WARN</option><option value={2}>CRIT</option>
            </select></div>
          <div><label className="label" htmlFor="nr-group">Device group</label>
            <select id="nr-group" className="input w-full" value={groupId ?? ""} onChange={(e) => setGroupId(e.target.value ? +e.target.value : null)}>
              <option value="">All devices</option>{groups.map((g) => <option key={g.id} value={g.id}>{g.name}</option>)}
            </select></div>
        </div>
        <div className="flex flex-wrap gap-x-6 gap-y-2">
          <label className="flex items-center gap-2 text-xs"><input type="checkbox" checked={recovery} onChange={(e) => setRecovery(e.target.checked)} /> Notify on recovery</label>
          <label className="flex items-center gap-2 text-xs"><input type="checkbox" checked={enabled} onChange={(e) => setEnabled(e.target.checked)} /> Enabled</label>
        </div>
        {rule && <div className="text-xs text-muted">Sent so far: {rule.sent_alert} alerts, {rule.sent_recovery} recoveries, {rule.sent_failed} failed
          {rule.last_sent_at && <> · last {fmtAgo(rule.last_sent_at)}</>}
          {rule.last_error && <div className="text-warn mt-1 break-words">Last error: {rule.last_error}</div>}</div>}
      </div>
      {error && <div className="text-crit text-xs mt-3" role="alert">{error}</div>}
      <div className="mt-4 flex justify-end gap-2">
        <button className="btn" onClick={onClose}>Cancel</button>
        <button className="btn btn-primary" onClick={save} disabled={!name.trim() || saving}>{saving ? "Saving…" : "Save"}</button>
      </div>
    </Modal>
  );
}
