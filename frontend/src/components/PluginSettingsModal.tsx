import { useEffect, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { AIJob, api, fmtAgo, PluginSettings, SettingField } from "../api";
import { Icon } from "./Icon";
import { Modal } from "./ui";

function ModelPicker({ plugin, config, value, onChange }: { plugin: string; config: Record<string, any>; value: string; onChange: (v: string) => void }) {
  const [models, setModels] = useState<{ name: string; parameters?: string; family?: string }[] | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  async function load() {
    setLoading(true);
    setError("");
    try {
      setModels(await api(`/plugins/${plugin}/models`, { body: { config: { base_url: config.base_url, api_key: config.api_key } } }));
    } catch (e: any) { setError(e.message); setModels(null); }
    setLoading(false);
  }
  useEffect(() => { if (config.base_url) load(); /* eslint-disable-next-line react-hooks/exhaustive-deps */ }, []);

  return (
    <div className="space-y-1.5">
      <div className="flex gap-2">
        {models?.length ? (
          <select className="input flex-1" value={value} onChange={(e) => onChange(e.target.value)}>
            <option value="">Choose a model…</option>
            {models.map((m) => (
              <option key={m.name} value={m.name}>{m.name}{m.parameters ? ` · ${m.parameters}` : ""}{m.family ? ` · ${m.family}` : ""}</option>
            ))}
            {value && !models.some((m) => m.name === value) && <option value={value}>{value} (not installed)</option>}
          </select>
        ) : (
          <input className="input flex-1 font-mono" value={value} onChange={(e) => onChange(e.target.value)} placeholder="llama3.1:8b" />
        )}
        <button type="button" className="btn" onClick={load} disabled={loading || !config.base_url} title="Load models from the server">
          <Icon name="refresh" className={`w-3.5 h-3.5 ${loading ? "animate-spin" : ""}`} />
        </button>
      </div>
      {error && <div className="text-xs text-crit">{error}</div>}
      {models && !models.length && <div className="text-xs text-warn">No models installed. Run e.g. <code className="font-mono">ollama pull llama3.1:8b</code> on the Ollama host.</div>}
    </div>
  );
}

function Field({ f, plugin, config, set }: { f: SettingField; plugin: string; config: Record<string, any>; set: (k: string, v: any) => void }) {
  const v = config[f.key];
  if (f.type === "bool") {
    return (
      <label className="flex items-start gap-3 cursor-pointer select-none py-1">
        <input type="checkbox" className="accent-accent mt-0.5" checked={!!v} onChange={(e) => set(f.key, e.target.checked)} />
        <span>
          <span className="text-sm text-strong">{f.label}</span>
          {f.help && <span className="block text-xs text-muted mt-0.5">{f.help}</span>}
        </span>
      </label>
    );
  }
  return (
    <div>
      <label className="label">{f.label}</label>
      {f.type === "select" ? (
        <select className="input w-full" value={String(v ?? "")} onChange={(e) => set(f.key, e.target.value)}>
          {f.options?.map(([val, label]) => <option key={val} value={val}>{label}</option>)}
        </select>
      ) : f.type === "textarea" ? (
        <textarea className="input w-full min-h-[5rem]" value={v ?? ""} onChange={(e) => set(f.key, e.target.value)} />
      ) : f.type === "model" ? (
        <ModelPicker plugin={plugin} config={config} value={v ?? ""} onChange={(val) => set(f.key, val)} />
      ) : (
        <input className="input w-full" type={f.type === "secret" ? "password" : f.type === "number" ? "number" : "text"}
          step={f.float ? "0.1" : undefined} min={f.min} max={f.max} value={v ?? ""} autoComplete="off"
          onChange={(e) => set(f.key, e.target.value)} />
      )}
      {f.help && <div className="text-xs text-muted mt-1">{f.help}</div>}
    </div>
  );
}

function RecentJobs() {
  const { data = [] } = useQuery({ queryKey: ["ai-jobs"], queryFn: () => api<AIJob[]>("/plugins/ai/jobs?limit=8"), refetchInterval: 10_000 });
  if (!data.length) return null;
  return (
    <div>
      <div className="text-xs font-medium text-muted mb-2">Recent activity</div>
      <ul className="divide-y divide-line border border-line rounded-lg text-xs">
        {data.map((j) => (
          <li key={j.id} className="px-3 py-2 flex items-center gap-2">
            <span className={`w-2 h-2 rounded-full ${j.status === "done" ? "bg-ok" : j.status === "error" ? "bg-crit" : "bg-warn animate-pulse"}`} />
            <span className="text-strong">{j.kind}</span>
            <span className="text-muted">{j.auto ? "auto" : j.requested_by}</span>
            <span className="text-muted truncate flex-1" title={j.error ?? ""}>{j.status === "error" ? j.error : j.duration != null ? `${j.duration.toFixed(1)} s` : j.status}</span>
            <span className="text-muted whitespace-nowrap">{fmtAgo(j.created_at)}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

export default function PluginSettingsModal({ name, onClose }: { name: string; onClose: () => void }) {
  const qc = useQueryClient();
  const { data } = useQuery({ queryKey: ["plugin-settings", name], queryFn: () => api<PluginSettings>(`/plugins/${name}/settings`) });
  const [enabled, setEnabled] = useState(false);
  const [config, setConfig] = useState<Record<string, any>>({});
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const [busy, setBusy] = useState<string | null>(null);

  useEffect(() => { if (data) { setEnabled(data.enabled); setConfig(data.config); } }, [data]);
  if (!data) return null;
  const set = (k: string, v: any) => setConfig((c) => ({ ...c, [k]: v }));
  const sections = [...new Set(data.fields.map((f) => f.section ?? "Settings"))];

  async function save() {
    setBusy("save");
    setMsg(null);
    try {
      const saved = await api<PluginSettings>(`/plugins/${name}/settings`, { method: "PUT", body: { enabled, config } });
      qc.setQueryData(["plugin-settings", name], saved);
      for (const key of ["plugins", "ai-status"]) qc.invalidateQueries({ queryKey: [key] });
      setMsg({ ok: true, text: "Settings saved" });
    } catch (e: any) { setMsg({ ok: false, text: e.message }); }
    setBusy(null);
  }

  async function action(a: PluginSettings["actions"][number]) {
    setBusy(a.id);
    setMsg(null);
    try {
      const r = await api<{ message?: string }>(`/plugins/${name}${a.path}`, { method: a.method, body: { config } });
      setMsg({ ok: true, text: r.message ?? "OK" });
    } catch (e: any) { setMsg({ ok: false, text: e.message }); }
    setBusy(null);
  }

  return (
    <Modal title={`${data.label} settings`} onClose={onClose}>
      <div className="space-y-6">
        <label className="flex items-center justify-between gap-4 p-3 rounded-xl border border-line bg-inset/40 cursor-pointer">
          <span>
            <span className="block text-sm font-medium text-strong">Enable {data.label}</span>
            <span className="block text-xs text-muted">When disabled nothing is sent to the AI server.</span>
          </span>
          <input type="checkbox" className="accent-accent w-4 h-4" checked={enabled} onChange={(e) => setEnabled(e.target.checked)} />
        </label>

        {sections.map((sec) => (
          <fieldset key={sec} className="space-y-3">
            <legend className="text-xs font-semibold uppercase tracking-wider text-muted mb-2">{sec}</legend>
            {data.fields.filter((f) => (f.section ?? "Settings") === sec).map((f) => (
              <Field key={f.key} f={f} plugin={name} config={config} set={set} />
            ))}
          </fieldset>
        ))}

        {name === "ai" && <RecentJobs />}

        {msg && (
          <div className={`text-sm rounded-lg p-3 border ${msg.ok ? "border-ok/40 bg-ok/10 text-ok" : "border-crit/40 bg-crit/10 text-crit"}`}>{msg.text}</div>
        )}
      </div>
      <div className="mt-6 flex flex-wrap justify-end gap-2 sticky bottom-0 bg-surface pt-3">
        {data.actions.map((a) => (
          <button key={a.id} className="btn" onClick={() => action(a)} disabled={!!busy}>
            {busy === a.id ? "Working…" : a.label}
          </button>
        ))}
        <button className="btn" onClick={onClose}>Close</button>
        <button className="btn btn-primary" onClick={save} disabled={!!busy}>{busy === "save" ? "Saving…" : "Save"}</button>
      </div>
    </Modal>
  );
}
