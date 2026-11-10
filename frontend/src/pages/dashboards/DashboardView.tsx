import React, { useEffect, useState } from "react";
import { useNavigate, useParams, useSearchParams } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api, Dashboard, prefs, Widget, WidgetCols, widgetCols } from "../../api";
import { Icon } from "../../components/Icon";
import { Page, PageHeader } from "../../components/Layout";
import { Empty, Segmented } from "../../components/ui";
import { DashboardForm } from "./Dashboards";
import WidgetEditor from "./WidgetEditor";
import { autoTitle, useComponents, useDevices, useProbes, WidgetBody, WidgetLogo } from "./WidgetView";
import { usePresets } from "../../presets";

// 12-column grid on wide screens, 6 on tablets, 1 on phones. Literal class names so Tailwind keeps them.
const SPAN: Record<WidgetCols, string> = {
  3: "md:col-span-3 xl:col-span-3", 4: "md:col-span-3 xl:col-span-4", 6: "md:col-span-6 xl:col-span-6",
  8: "md:col-span-6 xl:col-span-8", 12: "md:col-span-6 xl:col-span-12",
};
export const COL_OPTIONS: [WidgetCols, string][] = [[3, "¼ width"], [4, "⅓ width"], [6, "½ width"], [8, "⅔ width"], [12, "Full width"]];
/** Keep the legacy size in step with cols for clients that only know s/m/l. */
export const sizeFor = (cols: WidgetCols): Widget["size"] => (cols <= 4 ? "s" : cols >= 12 ? "l" : "m");
const RANGES: [string, string][] = [["1h", "1h"], ["6h", "6h"], ["24h", "24h"], ["7d", "7d"], ["30d", "30d"], ["1y", "1y"]];

const COL_STEPS: WidgetCols[] = [3, 4, 6, 8, 12];

/** Drag the right edge of a widget to resize it; snaps to ¼, ⅓, ½, ⅔ and full width. */
function ResizeHandle({ cols, onResize }: { cols: WidgetCols; onResize: (c: WidgetCols) => void }) {
  function start(e: React.PointerEvent<HTMLDivElement>) {
    const grid = e.currentTarget.closest("section")?.parentElement;
    if (!grid) return;
    e.preventDefault();
    const unit = grid.clientWidth / 12; // pixels per twelfth of the dashboard width
    const x0 = e.clientX;
    let current = cols;
    const move = (ev: PointerEvent) => {
      const want = cols + (ev.clientX - x0) / unit;
      const snapped = COL_STEPS.reduce((a, b) => (Math.abs(b - want) < Math.abs(a - want) ? b : a));
      if (snapped !== current) { current = snapped; onResize(snapped); }
    };
    const up = () => { window.removeEventListener("pointermove", move); window.removeEventListener("pointerup", up); document.body.style.cursor = ""; };
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", up);
    document.body.style.cursor = "ew-resize";
  }
  return (
    <div onPointerDown={start} title="Drag to resize"
      className="hidden md:flex absolute top-0 right-0 h-full w-2.5 cursor-ew-resize items-center justify-center group/rs hover:bg-accent/10">
      <span className="w-0.5 h-8 rounded-full bg-edge group-hover/rs:bg-accent" />
    </div>
  );
}

function WidgetCard({ w, range, editing, onEdit, onRemove, onMove, onResize, first, last }: {
  w: Widget; range: string; editing: boolean; first: boolean; last: boolean;
  onEdit: () => void; onRemove: () => void; onMove: (dir: -1 | 1) => void; onResize: (cols: WidgetCols) => void;
}) {
  const devices = useDevices();
  const components = useComponents(w.device_id);
  const { byId: presetById } = usePresets();
  const probes = useProbes();
  const ctl = "p-1.5 rounded-md text-muted hover:text-strong hover:bg-inset disabled:opacity-30";
  return (
    <section className={`card overflow-hidden relative col-span-1 ${SPAN[widgetCols(w)]} ${editing ? "ring-1 ring-accent/30" : ""}`}>
      <header className="px-4 py-2.5 border-b border-line flex items-center gap-2 min-h-[2.75rem]">
        <WidgetLogo logo={w.logo} />
        <h3 className="text-sm font-medium text-strong truncate flex-1">{w.title || autoTitle(w, devices, components, presetById, probes)}</h3>
        {editing && (
          <div className="flex items-center gap-0.5 shrink-0">
            <button className={ctl} disabled={first} onClick={() => onMove(-1)} title="Move left / up"><Icon name="chevron" className="w-3.5 h-3.5 rotate-180" /></button>
            <button className={ctl} disabled={last} onClick={() => onMove(1)} title="Move right / down"><Icon name="chevron" className="w-3.5 h-3.5" /></button>
            <select className="bg-surface text-xs text-muted hover:text-strong px-1 py-1 rounded-md outline-none" value={widgetCols(w)}
              onChange={(e) => onResize(+e.target.value as WidgetCols)} title="Width">
              {COL_OPTIONS.map(([c, label]) => <option key={c} value={c}>{label}</option>)}
            </select>
            <button className={ctl} onClick={onEdit} title="Edit"><Icon name="edit" className="w-3.5 h-3.5" /></button>
            <button className={`${ctl} hover:text-crit`} onClick={onRemove} title="Remove"><Icon name="trash" className="w-3.5 h-3.5" /></button>
          </div>
        )}
      </header>
      <WidgetBody w={w} range={range} />
      {editing && <ResizeHandle cols={widgetCols(w)} onResize={onResize} />}
    </section>
  );
}

export default function DashboardView() {
  const id = Number(useParams().id);
  const [params, setParams] = useSearchParams();
  const nav = useNavigate();
  const qc = useQueryClient();
  const { data: dash } = useQuery({ queryKey: ["dashboard", id], queryFn: () => api<Dashboard>(`/dashboards/${id}`) });
  const [range, setRange] = useState(() => prefs.get().default_range ?? "24h");
  const [draft, setDraft] = useState<Dashboard | null>(null);
  const [editor, setEditor] = useState<{ widget?: Widget } | null>(null);
  const [settings, setSettings] = useState(false);
  const [saving, setSaving] = useState(false);
  const editing = !!draft;

  // ?edit=1 (right after creating) opens edit mode
  useEffect(() => {
    if (dash && params.get("edit") && dash.can_edit && !draft) { setDraft(structuredClone(dash)); setParams({}, { replace: true }); }
  }, [dash, params, draft, setParams]);

  if (!dash) return <Empty>Loading…</Empty>;
  const view = draft ?? dash;
  const widgets = view.widgets;
  const update = (ws: Widget[]) => setDraft((d) => (d ? { ...d, widgets: ws } : d));

  async function save() {
    if (!draft) return;
    setSaving(true);
    try {
      const saved = await api<Dashboard>(`/dashboards/${id}`, { method: "PUT", body: {
        name: draft.name, description: draft.description, shared: draft.shared, widgets: draft.widgets,
        public: draft.public, public_name: draft.public_name,
      } });
      qc.setQueryData(["dashboard", id], saved);
      qc.invalidateQueries({ queryKey: ["dashboards"] });
      setDraft(null);
    } finally { setSaving(false); }
  }

  async function remove() {
    if (!confirm(`Delete dashboard "${dash!.name}"?`)) return;
    await api(`/dashboards/${id}`, { method: "DELETE" });
    qc.invalidateQueries({ queryKey: ["dashboards"] });
    nav("/dashboards");
  }

  const move = (i: number, dir: -1 | 1) => {
    const ws = [...widgets];
    [ws[i], ws[i + dir]] = [ws[i + dir], ws[i]];
    update(ws);
  };

  return (
    <>
      <PageHeader
        title={view.name}
        sub={<>{view.description ?? (view.shared ? "Shared dashboard" : "Private dashboard")} · by {view.owner}
          {view.public && <span className="ml-2 px-2 py-0.5 rounded-full bg-ok/15 text-ok text-xxs font-medium">public{view.public_name ? ` as “${view.public_name}”` : ""}</span>}</>}
        actions={editing ? (
          <>
            <button className="btn" onClick={() => setSettings(true)}>Settings</button>
            <button className="btn text-crit hover:bg-crit/10" onClick={remove}><Icon name="trash" className="w-3.5 h-3.5" /> Delete</button>
            <button className="btn" onClick={() => setDraft(null)}>Cancel</button>
            <button className="btn btn-primary" onClick={save} disabled={saving}><Icon name="check" className="w-3.5 h-3.5" /> {saving ? "Saving…" : "Save"}</button>
          </>
        ) : (
          <>
            <Segmented value={range} onChange={setRange} options={RANGES} />
            {dash.can_edit && <button className="btn" onClick={() => setDraft(structuredClone(dash))}><Icon name="edit" className="w-3.5 h-3.5" /> Edit</button>}
          </>
        )}
      />
      <Page>
        {editing && (
          <button onClick={() => setEditor({})}
            className="w-full rounded-xl border-2 border-dashed border-edge hover:border-accent hover:text-accent text-muted py-4 text-sm font-medium transition-colors flex items-center justify-center gap-2">
            <Icon name="plus" className="w-4 h-4" /> Add widget
          </button>
        )}
        {!widgets.length ? (
          !editing && <div className="card"><Empty>This dashboard is empty.{dash.can_edit && " Click Edit to add widgets."}</Empty></div>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-6 xl:grid-cols-12 gap-4">
            {widgets.map((w, i) => (
              <WidgetCard key={w.id} w={w} range={range} editing={editing} first={i === 0} last={i === widgets.length - 1}
                onEdit={() => setEditor({ widget: w })}
                onRemove={() => update(widgets.filter((x) => x.id !== w.id))}
                onMove={(dir) => move(i, dir)}
                onResize={(cols) => update(widgets.map((x) => (x.id === w.id ? { ...x, cols, size: sizeFor(cols) } : x)))} />
            ))}
          </div>
        )}
      </Page>
      {editor && (
        <WidgetEditor initial={editor.widget} isPublic={view.public} onClose={() => setEditor(null)} onSave={(w) => {
          update(editor.widget ? widgets.map((x) => (x.id === w.id ? w : x)) : [...widgets, w]);
          setEditor(null);
        }} />
      )}
      {settings && draft && (
        <DashboardForm initial={draft} onClose={() => setSettings(false)}
          onSaved={(d) => { setDraft({ ...draft, name: d.name, description: d.description, shared: d.shared, public: d.public, public_name: d.public_name }); setSettings(false); }} />
      )}
    </>
  );
}
