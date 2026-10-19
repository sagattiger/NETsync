import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { api, Dashboard, fmtAgo } from "../../api";
import { Icon } from "../../components/Icon";
import { Page, PageHeader } from "../../components/Layout";
import { Empty, Modal } from "../../components/ui";

export function DashboardForm({ initial, onClose, onSaved }: {
  initial?: Pick<Dashboard, "name" | "description" | "shared">; onClose: () => void; onSaved: (d: Dashboard) => void;
}) {
  const [name, setName] = useState(initial?.name ?? "");
  const [description, setDescription] = useState(initial?.description ?? "");
  const [shared, setShared] = useState(initial?.shared ?? false);
  const [error, setError] = useState("");
  return (
    <Modal title={initial ? "Dashboard settings" : "New dashboard"} onClose={onClose}>
      <form className="space-y-4" onSubmit={async (e) => {
        e.preventDefault();
        try {
          if (initial) onSaved({ ...(initial as Dashboard), name, description, shared });
          else onSaved(await api<Dashboard>("/dashboards", { body: { name, description: description || null, shared, widgets: [] } }));
        } catch (err: any) { setError(err.message); }
      }}>
        <div><label className="label">Name</label>
          <input className="input w-full" autoFocus value={name} onChange={(e) => setName(e.target.value)} placeholder="Core network" /></div>
        <div><label className="label">Description (optional)</label>
          <input className="input w-full" value={description} onChange={(e) => setDescription(e.target.value)} /></div>
        <label className="flex items-center gap-2.5 text-sm text-fg cursor-pointer select-none">
          <input type="checkbox" className="accent-accent" checked={shared} onChange={(e) => setShared(e.target.checked)} />
          Share with all users
          <span className="text-xs text-muted">(they still only see devices they have access to)</span>
        </label>
        {error && <div className="text-xs text-crit">{error}</div>}
        <div className="flex justify-end gap-2 pt-2">
          <button type="button" className="btn" onClick={onClose}>Cancel</button>
          <button className="btn btn-primary" disabled={!name.trim()}>{initial ? "Apply" : "Create"}</button>
        </div>
      </form>
    </Modal>
  );
}

export default function Dashboards() {
  const nav = useNavigate();
  const [creating, setCreating] = useState(false);
  const { data = [], isLoading } = useQuery({ queryKey: ["dashboards"], queryFn: () => api<Dashboard[]>("/dashboards") });

  return (
    <>
      <PageHeader title="Dashboards" sub="Your own views of graphs, devices and problems"
        actions={<button className="btn btn-primary" onClick={() => setCreating(true)}><Icon name="plus" className="w-3.5 h-3.5" /> New dashboard</button>} />
      <Page>
        {isLoading ? null : !data.length ? (
          <div className="card"><Empty>No dashboards yet. Create one and add graphs of interfaces, CPU, latency or TCP/UDP.</Empty></div>
        ) : (
          <div className="grid sm:grid-cols-2 xl:grid-cols-3 gap-3">
            {data.map((d) => (
              <Link key={d.id} to={`/dashboards/${d.id}`} className="card p-4 hover:border-accent/60 transition-colors group">
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0">
                    <div className="font-medium text-strong truncate group-hover:text-accent transition-colors">{d.name}</div>
                    {d.description && <div className="text-xs text-muted mt-0.5 line-clamp-2">{d.description}</div>}
                  </div>
                  <span className="w-9 h-9 rounded-lg bg-inset border border-line flex items-center justify-center text-fg2 shrink-0">
                    <Icon name="grid" className="w-4 h-4" />
                  </span>
                </div>
                <div className="flex flex-wrap items-center gap-2 mt-4 text-xxs text-muted">
                  <span className="px-2 py-0.5 rounded-full bg-chip text-fg2">{d.widgets.length} widget{d.widgets.length === 1 ? "" : "s"}</span>
                  {d.shared && <span className="px-2 py-0.5 rounded-full bg-accent/15 text-accent">shared</span>}
                  <span>by {d.owner} · updated {fmtAgo(d.updated_at)}</span>
                </div>
              </Link>
            ))}
          </div>
        )}
      </Page>
      {creating && <DashboardForm onClose={() => setCreating(false)} onSaved={(d) => nav(`/dashboards/${d.id}?edit=1`)} />}
    </>
  );
}
