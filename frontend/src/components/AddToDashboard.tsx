import { useState } from "react";
import { Link } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api, Dashboard, Widget } from "../api";
import { newWidgetId } from "../pages/dashboards/WidgetEditor";
import { Icon } from "./Icon";
import { Modal, Segmented } from "./ui";

/** Small button that adds a graph widget for (device, preset, component) to a dashboard. */
export function AddToDashboard({ deviceId = null, probeId = null, preset, componentId = null, label = "Add to dashboard", type = "graph" }: {
  deviceId?: number | null; probeId?: number | null; preset: string | null; componentId?: number | null; label?: string;
  type?: "graph" | "uptime";
}) {
  const [open, setOpen] = useState(false);
  return (
    <>
      <button className="btn btn-ghost px-2 py-1 text-muted hover:text-strong" onClick={(e) => { e.stopPropagation(); setOpen(true); }}>
        <Icon name="grid" className="w-3.5 h-3.5" /> {label}
      </button>
      {open && <Picker deviceId={deviceId} probeId={probeId} preset={preset} componentId={componentId} type={type} onClose={() => setOpen(false)} />}
    </>
  );
}

function Picker({ deviceId, probeId, preset, componentId, type, onClose }: {
  deviceId: number | null; probeId: number | null; preset: string | null; componentId: number | null;
  type: "graph" | "uptime"; onClose: () => void;
}) {
  const qc = useQueryClient();
  const { data = [] } = useQuery({ queryKey: ["dashboards"], queryFn: () => api<Dashboard[]>("/dashboards") });
  const editable = data.filter((d) => d.can_edit);
  const [target, setTarget] = useState<number | "new" | null>(null); // null = first editable dashboard
  const [name, setName] = useState("My dashboard");
  const [size, setSize] = useState<Widget["size"]>("m");
  const [done, setDone] = useState<Dashboard | null>(null);
  const [error, setError] = useState("");

  const chosen: number | "new" = target ?? editable[0]?.id ?? "new";

  async function add() {
    setError("");
    const widget: Widget = {
      id: newWidgetId(), type, title: "", size, device_id: probeId ? null : deviceId, component_id: probeId ? null : componentId, preset,
      ...(probeId ? { probe_id: probeId } : {}),
    };
    try {
      let saved: Dashboard;
      if (chosen === "new") {
        saved = await api<Dashboard>("/dashboards", { body: { name, shared: false, widgets: [widget] } });
      } else {
        const d = editable.find((x) => x.id === chosen)!;
        saved = await api<Dashboard>(`/dashboards/${d.id}`, { method: "PUT", body: {
          name: d.name, description: d.description, shared: d.shared, widgets: [...d.widgets, widget],
        } });
      }
      qc.invalidateQueries({ queryKey: ["dashboards"] });
      qc.setQueryData(["dashboard", saved.id], saved);
      setDone(saved);
    } catch (e: any) { setError(e.message); }
  }

  return (
    <Modal title="Add graph to dashboard" onClose={onClose}>
      {done ? (
        <div className="space-y-4">
          <div className="text-sm text-fg">Added to <span className="font-medium text-strong">{done.name}</span>.</div>
          <div className="flex justify-end gap-2">
            <button className="btn" onClick={onClose}>Close</button>
            <Link className="btn btn-primary" to={`/dashboards/${done.id}`}>Open dashboard</Link>
          </div>
        </div>
      ) : (
        <div className="space-y-4" onClick={(e) => e.stopPropagation()}>
          <div>
            <label className="label">Dashboard</label>
            <select className="input w-full" value={String(chosen)} onChange={(e) => setTarget(e.target.value === "new" ? "new" : +e.target.value)}>
              {editable.map((d) => <option key={d.id} value={d.id}>{d.name}</option>)}
              <option value="new">+ New dashboard…</option>
            </select>
          </div>
          {chosen === "new" && (
            <div><label className="label">New dashboard name</label>
              <input className="input w-full" value={name} onChange={(e) => setName(e.target.value)} /></div>
          )}
          <div><label className="label">Width</label>
            <Segmented value={size} onChange={setSize} options={[["s", "Small"], ["m", "Half"], ["l", "Full"]]} /></div>
          {error && <div className="text-xs text-crit">{error}</div>}
          <div className="flex justify-end gap-2">
            <button className="btn" onClick={onClose}>Cancel</button>
            <button className="btn btn-primary" onClick={add} disabled={chosen === "new" && !name.trim()}>Add</button>
          </div>
        </div>
      )}
    </Modal>
  );
}
