import { useEffect, useState } from "react";
import { useNavigate, useParams, useSearchParams } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api, Dashboard, prefs, Widget } from "../../api";
import { Icon } from "../../components/Icon";
import { Page, PageHeader } from "../../components/Layout";
import { Empty, Segmented } from "../../components/ui";
import { DashboardForm } from "./Dashboards";
import WidgetEditor from "./WidgetEditor";
import { autoTitle, useComponents, useDevices, WidgetBody } from "./WidgetView";

const SPAN = { s: "md:col-span-3 xl:col-span-4", m: "md:col-span-6 xl:col-span-6", l: "md:col-span-6 xl:col-span-12" };
const RANGES: [string, string][] = [["1h", "1h"], ["6h", "6h"], ["24h", "24h"], ["7d", "7d"], ["30d", "30d"], ["1y", "1y"]];

function WidgetCard({ w, range, editing, onEdit, onRemove, onMove, onResize, first, last }: {
  w: Widget; range: string; editing: boolean; first: boolean; last: boolean;
  onEdit: () => void; onRemove: () => void; onMove: (dir: -1 | 1) => void; onResize: (s: Widget["size"]) => void;
}) {
  const devices = useDevices();
  const components = useComponents(w.device_id);
  const ctl = "p-1.5 rounded-md text-muted hover:text-strong hover:bg-inset disabled:opacity-30";
  return (
    <section className={`card overflow-hidden col-span-1 ${SPAN[w.size]} ${editing ? "ring-1 ring-accent/30" : ""}`}>
      <header className="px-4 py-2.5 border-b border-line flex items-center gap-2 min-h-[2.75rem]">
        <h3 className="text-sm font-medium text-strong truncate flex-1">{w.title || autoTitle(w, devices, components)}</h3>
        {editing && (
          <div className="flex items-center gap-0.5 shrink-0">
            <button className={ctl} disabled={first} onClick={() => onMove(-1)} title="Move left / up"><Icon name="chevron" className="w-3.5 h-3.5 rotate-180" /></button>
            <button className={ctl} disabled={last} onClick={() => onMove(1)} title="Move right / down"><Icon name="chevron" className="w-3.5 h-3.5" /></button>
            <select className="bg-transparent text-xs text-muted hover:text-strong px-1 py-1 rounded-md outline-none" value={w.size}
              onChange={(e) => onResize(e.target.value as Widget["size"])} title="Width">
              <option value="s">Small</option><option value="m">Half</option><option value="l">Full</option>
            </select>
            <button className={ctl} onClick={onEdit} title="Edit"><Icon name="edit" className="w-3.5 h-3.5" /></button>
            <button className={`${ctl} hover:text-crit`} onClick={onRemove} title="Remove"><Icon name="trash" className="w-3.5 h-3.5" /></button>
          </div>
        )}
      </header>
      <WidgetBody w={w} range={range} />
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
        sub={<>{view.description ?? (view.shared ? "Shared dashboard" : "Private dashboard")} · by {view.owner}</>}
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
                onResize={(size) => update(widgets.map((x) => (x.id === w.id ? { ...x, size } : x)))} />
            ))}
          </div>
        )}
      </Page>
      {editor && (
        <WidgetEditor initial={editor.widget} onClose={() => setEditor(null)} onSave={(w) => {
          update(editor.widget ? widgets.map((x) => (x.id === w.id ? w : x)) : [...widgets, w]);
          setEditor(null);
        }} />
      )}
      {settings && draft && (
        <DashboardForm initial={draft} onClose={() => setSettings(false)}
          onSaved={(d) => { setDraft({ ...draft, name: d.name, description: d.description, shared: d.shared }); setSettings(false); }} />
      )}
    </>
  );
}
