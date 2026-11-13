import { useEffect, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { api, Dashboard, fmtAgo, Me } from "../../api";
import { Icon } from "../../components/Icon";
import { Page, PageHeader } from "../../components/Layout";
import { Empty, Modal } from "../../components/ui";

export function DashboardForm({ initial, onClose, onSaved }: {
  initial?: Pick<Dashboard, "name" | "description" | "shared" | "public" | "public_name">;
  onClose: () => void; onSaved: (d: Dashboard) => void;
}) {
  const { data: me } = useQuery({ queryKey: ["me"], queryFn: () => api<Me>("/auth/me") });
  const isAdmin = me?.role === "admin";
  const [name, setName] = useState(initial?.name ?? "");
  const [description, setDescription] = useState(initial?.description ?? "");
  const [shared, setShared] = useState(initial?.shared ?? false);
  const [isPublic, setPublic] = useState(initial?.public ?? false);
  const [publicName, setPublicName] = useState(initial?.public_name ?? "");
  const [error, setError] = useState("");
  const pub = isAdmin ? { public: isPublic, public_name: publicName.trim() || null } : {};
  return (
    <Modal title={initial ? "Dashboard settings" : "New dashboard"} onClose={onClose}>
      <form className="space-y-4" onSubmit={async (e) => {
        e.preventDefault();
        try {
          if (initial) onSaved({ ...(initial as Dashboard), name, description, shared, ...pub });
          else onSaved(await api<Dashboard>("/dashboards", { body: { name, description: description || null, shared, ...pub, widgets: [] } }));
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
        {isAdmin && (
          <div className="rounded-xl border border-line p-3 space-y-3">
            <label className="flex items-start gap-2.5 text-sm text-fg cursor-pointer select-none">
              <input type="checkbox" className="accent-accent mt-0.5" checked={isPublic} onChange={(e) => setPublic(e.target.checked)} />
              <span>
                <span className="text-strong font-medium">Public (shown on the website)</span>
                <span className="block text-xs text-muted">Readable with an API token through /api/public. Hostnames, IPs and check output are never sent.</span>
              </span>
            </label>
            {isPublic && (
              <div><label className="label">Public name (optional)</label>
                <input className="input w-full" value={publicName} maxLength={128} onChange={(e) => setPublicName(e.target.value)}
                  placeholder={name || "Network status"} /></div>
            )}
          </div>
        )}
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
  const [params, setParams] = useSearchParams();
  const [creating, setCreating] = useState(false);
  useEffect(() => {
    if (params.get("new") === "1") { setCreating(true); setParams({}, { replace: true }); }
  }, [params, setParams]);
  const { data = [], isLoading } = useQuery({ queryKey: ["dashboards"], queryFn: () => api<Dashboard[]>("/dashboards") });

  return (
    <>
      <PageHeader title="Dashboards" sub="Your own views of graphs, devices and problems"
        actions={<button className="btn btn-primary" onClick={() => setCreating(true)}><Icon name="plus" className="w-3.5 h-3.5" /> New dashboard</button>} />
      <Page>
        {isLoading ? null : !data.length ? (
          <div className="card"><Empty art="empty-dashboards">No dashboards yet. Create one and add graphs of interfaces, CPU, latency or TCP/UDP.</Empty></div>
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
                  <span className="px-2 py-0.5 rounded-pill bg-chip text-fg2">{d.widgets.length} widget{d.widgets.length === 1 ? "" : "s"}</span>
                  {d.public && <span className="px-2 py-0.5 rounded-pill bg-ok/15 text-ok inline-flex items-center gap-1"><Icon name="globe" className="w-3 h-3" />public</span>}
                  {d.shared && <span className="px-2 py-0.5 rounded-pill bg-accent/15 text-accent">shared</span>}
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
