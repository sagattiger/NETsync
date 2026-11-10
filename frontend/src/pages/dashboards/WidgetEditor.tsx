import { useState } from "react";
import { Widget, WidgetType } from "../../api";
import { Modal, Segmented } from "../../components/ui";
import { usePresets } from "../../presets";
import { autoTitle, useComponents, useDevices } from "./WidgetView";

const TYPES: [WidgetType, string, string][] = [
  ["graph", "Graph", "Interface traffic, CPU, latency, TCP/UDP…"],
  ["device", "Device", "Status card with service counts"],
  ["services", "Services", "All services of a device"],
  ["problems", "Problems", "Open problems, one device or all"],
];

export const newWidgetId = () => Math.random().toString(36).slice(2, 10);

export default function WidgetEditor({ initial, isPublic, onSave, onClose }: {
  initial?: Widget; isPublic?: boolean; onSave: (w: Widget) => void; onClose: () => void;
}) {
  const devices = useDevices();
  const [w, setW] = useState<Widget>(initial ?? {
    id: newWidgetId(), type: "graph", title: "", size: "m", device_id: null, component_id: null, preset: "port_traffic",
  });
  const { presets, byId: presetById, groups } = usePresets();
  const preset = presetById(w.preset);
  const components = useComponents(w.device_id, w.type === "graph" ? preset?.kind : undefined);
  const set = (patch: Partial<Widget>) => setW((p) => ({ ...p, ...patch }));

  const needsDevice = w.type !== "problems";
  const needsComponent = w.type === "graph" && !!preset?.kind;
  const valid = (!needsDevice || w.device_id) && (w.type !== "graph" || preset) && (!needsComponent || w.component_id);

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

        <div>
          <label className="label">Device {w.type === "problems" && "(leave empty for all devices)"}</label>
          <select className="input w-full" value={w.device_id ?? ""} onChange={(e) => set({ device_id: e.target.value ? +e.target.value : null, component_id: null })}>
            <option value="">{w.type === "problems" ? "All devices" : "Choose a device…"}</option>
            {devices.map((d) => <option key={d.id} value={d.id}>{d.hostname}</option>)}
          </select>
        </div>

        {w.type === "graph" && (
          <div>
            <label className="label">Graph</label>
            <select className="input w-full" value={w.preset ?? ""} onChange={(e) => set({ preset: e.target.value, component_id: null })}>
              {groups.map((g) => (
                <optgroup key={g} label={g}>
                  {presets.filter((p) => p.group === g).map((p) => <option key={p.id} value={p.id}>{p.label}</option>)}
                </optgroup>
              ))}
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
              onChange={(e) => set({ public_title: e.target.value || null })} placeholder="e.g. Core router · Uplink 1" />
            <div className="text-xs text-muted mt-1">Leave empty to show a generic title (graph name, without the hostname).</div>
          </div>
        )}

        <div className="grid sm:grid-cols-[1fr_auto] gap-4">
          <div>
            <label className="label">Title (optional)</label>
            <input className="input w-full" value={w.title} onChange={(e) => set({ title: e.target.value })}
              placeholder={autoTitle(w, devices, components, presetById)} />
          </div>
          <div>
            <label className="label">Width</label>
            <Segmented value={w.size} onChange={(size) => set({ size })} options={[["s", "Small"], ["m", "Half"], ["l", "Full"]]} />
          </div>
        </div>
      </div>
      <div className="mt-6 flex justify-end gap-2">
        <button className="btn" onClick={onClose}>Cancel</button>
        <button className="btn btn-primary" disabled={!valid} onClick={() => onSave(w)}>{initial ? "Update" : "Add widget"}</button>
      </div>
    </Modal>
  );
}
