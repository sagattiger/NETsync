import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api, logoSrc, Widget, WidgetType, widgetCols } from "../../api";
import { Icon } from "../../components/Icon";
import { Modal, Segmented } from "../../components/ui";
import { usePresets } from "../../presets";
import { autoTitle, useComponents, useDevices, useProbes } from "./WidgetView";

const TYPES: [WidgetType, string, string][] = [
  ["graph", "Graph", "Interface traffic, CPU, latency, probes…"],
  ["device", "Device", "Status card with service counts"],
  ["services", "Services", "All services of a device"],
  ["problems", "Problems", "Open problems, one device or all"],
];

const COLS: [string, string][] = [["3", "¼"], ["4", "⅓"], ["6", "½"], ["8", "⅔"], ["12", "Full"]];
// Used to fill earlier series when only a later one gets a custom colour.
const DEFAULT_COLORS = ["#00ABFA", "#F58A07", "#5B8DEF", "#F5A524", "#3DD68C", "#A78BFA"];
const HEX = /^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})$/;
const full = (hex: string) => (hex.length === 4 ? `#${hex[1]}${hex[1]}${hex[2]}${hex[2]}${hex[3]}${hex[3]}` : hex);

export const newWidgetId = () => Math.random().toString(36).slice(2, 10);

interface IconHit { slug: string; name: string; logo: string; src: string; formats: string[] }

function LogoPicker({ value, onChange }: { value: string | null | undefined; onChange: (v: string | null) => void }) {
  const [q, setQ] = useState("");
  const [debounced, setDebounced] = useState("");
  const [url, setUrl] = useState(value && !value.startsWith("di:") ? value : "");
  useEffect(() => { const t = setTimeout(() => setDebounced(q.trim()), 250); return () => clearTimeout(t); }, [q]);
  const { data = [], isFetching, error } = useQuery({
    queryKey: ["icons", debounced],
    queryFn: () => api<IconHit[]>(`/icons?q=${encodeURIComponent(debounced)}&limit=30`),
    enabled: debounced.length > 0,
    staleTime: Infinity,
  });
  const src = logoSrc(value);
  const urlOk = !url || /^https:\/\/[^\s"'<>`\\]+$/.test(url);

  return (
    <div className="space-y-2">
      <div className="flex items-center gap-3">
        <div className="w-10 h-10 rounded-lg border border-line bg-inset flex items-center justify-center shrink-0">
          {src ? <img src={src} alt="" className="w-7 h-7 object-contain" referrerPolicy="no-referrer" /> : <Icon name="globe" className="w-4 h-4 text-muted" />}
        </div>
        <div className="flex-1 min-w-0 text-xs text-muted truncate">{value ? value.replace(/^di:/, "Dashboard Icons: ") : "No logo"}</div>
        {value && <button className="btn btn-ghost px-2 py-1 text-xs" onClick={() => { onChange(null); setUrl(""); }}>Remove</button>}
      </div>
      <input className="input w-full" value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search Dashboard Icons (google, cloudflare, proxmox…)" />
      {debounced && (
        <div className="max-h-40 overflow-y-auto rounded-lg border border-line p-1.5 grid grid-cols-6 sm:grid-cols-8 gap-1">
          {error ? <div className="col-span-full text-xs text-crit p-2">{(error as Error).message}</div>
            : !data.length ? <div className="col-span-full text-xs text-muted p-2">{isFetching ? "Searching…" : "No icons found"}</div>
            : data.map((i) => (
              <button key={i.slug} title={i.name} onClick={() => { onChange(i.logo); setUrl(""); }}
                className={`aspect-square rounded-md flex items-center justify-center hover:bg-inset ${value === i.logo ? "ring-2 ring-accent" : ""}`}>
                <img src={i.src} alt={i.name} className="w-7 h-7 object-contain" loading="lazy" referrerPolicy="no-referrer" />
              </button>
            ))}
        </div>
      )}
      <div className="flex gap-2">
        <input className="input flex-1 min-w-0" value={url} onChange={(e) => setUrl(e.target.value.trim())} placeholder="…or paste an https:// image URL" />
        <button className="btn" disabled={!url || !urlOk} onClick={() => onChange(url)}>Use URL</button>
      </div>
      {!urlOk && <div className="text-xs text-crit">Only https:// image URLs are allowed.</div>}
    </div>
  );
}

export default function WidgetEditor({ initial, isPublic, onSave, onClose }: {
  initial?: Widget; isPublic?: boolean; onSave: (w: Widget) => void; onClose: () => void;
}) {
  const devices = useDevices();
  const probes = useProbes();
  const [w, setW] = useState<Widget>(initial ?? {
    id: newWidgetId(), type: "graph", title: "", size: "m", device_id: null, component_id: null, preset: "port_traffic",
  });
  const [showLook, setShowLook] = useState(!!(initial && (initial.logo || initial.colors || initial.labels || initial.compact || initial.cols || initial.height)));
  const { presets, byId: presetById, groups } = usePresets();
  const preset = presetById(w.preset);
  const isProbe = w.type === "graph" && preset?.source === "probe";
  const components = useComponents(isProbe ? null : w.device_id, w.type === "graph" ? preset?.kind : undefined);
  const set = (patch: Partial<Widget>) => setW((p) => ({ ...p, ...patch }));

  const needsDevice = w.type !== "problems" && !isProbe;
  const needsComponent = w.type === "graph" && !isProbe && !!preset?.kind;
  const series = w.type === "graph" && preset ? preset.metrics.map((m) => m.label ?? m.name) : [];
  const valid = (!needsDevice || w.device_id) && (w.type !== "graph" || preset) && (!needsComponent || w.component_id)
    && (!isProbe || w.probe_id) && (w.colors ?? []).every((c) => HEX.test(c));

  function setColor(i: number, hex: string) {
    const cs = [...(w.colors ?? [])];
    while (cs.length < i) cs.push(DEFAULT_COLORS[cs.length % DEFAULT_COLORS.length]);
    cs[i] = hex.toUpperCase();
    set({ colors: cs });
  }
  function setLabel(key: string, label: string) {
    const ls = { ...(w.labels ?? {}), [key]: label.slice(0, 16) };
    if (!label.trim()) delete ls[key];
    set({ labels: Object.keys(ls).length ? ls : null });
  }

  function save() {
    const out: Widget = { ...w };
    if (isProbe) { out.device_id = null; out.component_id = null; } else out.probe_id = null;
    if (w.type !== "graph") { out.colors = null; out.labels = null; out.compact = null; }
    if (out.labels) out.labels = Object.fromEntries(Object.entries(out.labels).filter(([k, v]) => series.includes(k) && v.trim()));
    if (out.colors) out.colors = out.colors.slice(0, Math.max(series.length, 1));
    onSave(out);
  }

  return (
    <Modal title={initial ? "Edit widget" : "Add widget"} onClose={onClose}>
      <div className="space-y-5">
        <div className="grid grid-cols-2 gap-2">
          {TYPES.map(([t, label, hint]) => (
            <button key={t} onClick={() => set({ type: t })}
              className={`text-left p-3 rounded-xl border transition-colors ${w.type === t ? "border-accent bg-accent/5" : "border-edge hover:bg-inset"}`}>
              <div className="text-sm font-medium text-strong">{label}</div>
              <div className="text-xxs text-muted mt-0.5">{hint}</div>
            </button>
          ))}
        </div>

        {w.type === "graph" && (
          <div>
            <label className="label">Graph</label>
            <select className="input w-full" value={w.preset ?? ""} onChange={(e) => set({ preset: e.target.value, component_id: null, labels: null, colors: null })}>
              {groups.map((g) => (
                <optgroup key={g} label={g}>
                  {presets.filter((p) => p.group === g).map((p) => <option key={p.id} value={p.id}>{p.label}</option>)}
                </optgroup>
              ))}
            </select>
          </div>
        )}

        {isProbe ? (
          <div>
            <label className="label">Probe</label>
            <select className="input w-full" value={w.probe_id ?? ""} onChange={(e) => set({ probe_id: e.target.value ? +e.target.value : null })}>
              <option value="">{probes.length ? "Choose a probe…" : "No probes yet: add one on the Probes page"}</option>
              {probes.map((p) => <option key={p.id} value={p.id}>{p.name} ({p.target})</option>)}
            </select>
          </div>
        ) : (
          <div>
            <label className="label">Device {w.type === "problems" && "(leave empty for all devices)"}</label>
            <select className="input w-full" value={w.device_id ?? ""} onChange={(e) => set({ device_id: e.target.value ? +e.target.value : null, component_id: null })}>
              <option value="">{w.type === "problems" ? "All devices" : "Choose a device…"}</option>
              {devices.map((d) => <option key={d.id} value={d.id}>{d.hostname}</option>)}
            </select>
          </div>
        )}

        {needsComponent && (
          <div>
            <label className="label">{preset?.kind === "port" ? "Interface" : preset?.kind === "storage" ? "Filesystem" : "Component"}</label>
            <select className="input w-full" value={w.component_id ?? ""} disabled={!w.device_id}
              onChange={(e) => set({ component_id: e.target.value ? +e.target.value : null })}>
              <option value="">{w.device_id ? "Choose…" : "Pick a device first"}</option>
              {components.map((c) => <option key={c.id} value={c.id}>{c.name}{c.descr ? ` — ${c.descr}` : ""}</option>)}
            </select>
          </div>
        )}

        {isPublic && (
          <div>
            <label className="label">Public title (shown on the website)</label>
            <input className="input w-full" maxLength={128} value={w.public_title ?? ""}
              onChange={(e) => set({ public_title: e.target.value || null })} placeholder={isProbe ? "e.g. Ping to Google" : "e.g. Core router · Uplink 1"} />
            <div className="text-xs text-muted mt-1">Leave empty to show a generic title (graph name, without the hostname{isProbe ? " or probe target" : ""}).</div>
          </div>
        )}

        <div className="grid sm:grid-cols-[1fr_auto] gap-4">
          <div>
            <label className="label">Title (optional)</label>
            <input className="input w-full" value={w.title} onChange={(e) => set({ title: e.target.value })}
              placeholder={autoTitle(w, devices, components, presetById, probes)} />
          </div>
          <div>
            <label className="label">Width</label>
            <Segmented value={String(widgetCols(w))} options={COLS}
              onChange={(c) => { const cols = +c as Widget["cols"] & number; set({ cols, size: cols <= 4 ? "s" : cols >= 12 ? "l" : "m" }); }} />
          </div>
        </div>

        <div className="border-t border-line pt-4">
          <button className="flex items-center gap-2 text-sm font-medium text-strong" onClick={() => setShowLook((v) => !v)}>
            <Icon name="chevron" className={`w-3.5 h-3.5 transition-transform ${showLook ? "rotate-90" : ""}`} /> Appearance
            <span className="text-xs font-normal text-muted">logo, colours, labels, height</span>
          </button>
          {showLook && (
            <div className="space-y-5 mt-4">
              <div>
                <label className="label">Logo</label>
                <LogoPicker value={w.logo} onChange={(logo) => set({ logo })} />
              </div>

              {w.type === "graph" && series.length > 0 && (
                <div>
                  <div className="flex items-center justify-between">
                    <label className="label">Series</label>
                    {(w.colors || w.labels) && <button className="text-xs text-muted hover:text-strong" onClick={() => set({ colors: null, labels: null })}>Reset colours &amp; labels</button>}
                  </div>
                  <div className="space-y-2">
                    {series.slice(0, 6).map((key, i) => (
                      <div key={key} className="flex items-center gap-2">
                        <input type="color" className="w-9 h-9 rounded-md border border-line bg-transparent cursor-pointer shrink-0"
                          value={full(w.colors?.[i] ?? DEFAULT_COLORS[i % DEFAULT_COLORS.length]).toLowerCase()}
                          onChange={(e) => setColor(i, e.target.value)} title={w.colors?.[i] ? w.colors[i] : "Theme colour"} />
                        <input className="input flex-1 min-w-0" maxLength={16} value={w.labels?.[key] ?? ""}
                          onChange={(e) => setLabel(key, e.target.value)}
                          placeholder={isProbe && series.length === 1 ? probes.find((p) => p.id === w.probe_id)?.name ?? key : key} />
                        <span className="text-xxs text-muted w-16 truncate">{w.colors?.[i] ? w.colors[i] : "default"}</span>
                      </div>
                    ))}
                  </div>
                  <div className="text-xs text-muted mt-1">Short labels (max 16 characters), e.g. Rx / Tx.</div>
                </div>
              )}

              <div className="grid sm:grid-cols-2 gap-4">
                <div>
                  <label className="label">Height</label>
                  <Segmented value={w.height ?? "normal"} onChange={(height) => set({ height: height === "normal" ? null : height })}
                    options={[["compact", "Compact"], ["normal", "Normal"], ["tall", "Tall"]]} />
                </div>
                {w.type === "graph" && (
                  <label className="flex items-start gap-2.5 cursor-pointer select-none sm:pt-6">
                    <input type="checkbox" className="mt-0.5" checked={!!w.compact} onChange={(e) => set({ compact: e.target.checked || null })} />
                    <span className="text-sm text-fg">Compact<span className="block text-xs text-muted">Logo, title, current value and a small chart only</span></span>
                  </label>
                )}
              </div>
            </div>
          )}
        </div>
      </div>
      <div className="mt-6 flex justify-end gap-2">
        <button className="btn" onClick={onClose}>Cancel</button>
        <button className="btn btn-primary" disabled={!valid} onClick={save}>{initial ? "Update" : "Add widget"}</button>
      </div>
    </Modal>
  );
}
