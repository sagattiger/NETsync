import { useSearchParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { api, Me, PluginInfo } from "../api";
import { Icon } from "../components/Icon";
import { Page, PageHeader } from "../components/Layout";
import PluginSettingsModal from "../components/PluginSettingsModal";
import { Card } from "../components/ui";

export default function Plugins() {
  const [params, setParams] = useSearchParams();
  const configure = params.get("configure");
  const { data: me } = useQuery({ queryKey: ["me"], queryFn: () => api<Me>("/auth/me") });
  const { data = [] } = useQuery({ queryKey: ["plugins"], queryFn: () => api<PluginInfo[]>("/plugins") });
  const { data: nodes = [] } = useQuery({
    queryKey: ["nodes"],
    queryFn: () => api<{ id: number; name: string; is_local: boolean; last_seen: string | null; version: string | null }[]>("/nodes"),
  });
  const isAdmin = me?.role === "admin";
  const chips = (label: string, items: string[]) =>
    items.length ? (
      <div className="flex gap-1 flex-wrap items-center">
        <span className="text-xxs text-muted w-16">{label}</span>
        {items.map((i) => <span key={i} className="px-1.5 rounded bg-chip text-xxs font-mono">{i}</span>)}
      </div>
    ) : null;

  return (
    <>
      <PageHeader title="Plugins & nodes" sub="Installed extensions and polling nodes" />
      <Page>
        <div className="grid md:grid-cols-2 xl:grid-cols-3 gap-3">
          {data.map((p) => (
            <Card key={p.name} className={p.name === "ai" ? "border-accent/40" : ""}>
              <div className="p-4 space-y-2.5 h-full flex flex-col">
                <div className="flex justify-between items-start gap-2">
                  <div className="font-semibold text-strong flex items-center gap-2">
                    {p.name === "ai" && <Icon name="sparkles" className="w-4 h-4 text-accent" />}
                    {p.label}
                  </div>
                  <span className={`text-xxs px-2 py-0.5 rounded-full font-medium ${p.enabled ? "bg-ok/10 text-ok" : "bg-chip text-muted"}`}>
                    {p.enabled ? "enabled" : "disabled"}
                  </span>
                </div>
                <div className="text-xs text-fg2 flex-1">{p.description}</div>
                {chips("modules", p.modules)}
                {chips("channels", p.channels)}
                {chips("services", p.services)}
                {chips("tabs", p.ui_tabs.map((t) => t.label))}
                <div className="flex items-center justify-between pt-1">
                  <span className="text-xxs text-muted">v{p.version}{p.builtin && " · built-in"}</span>
                  {p.configurable && isAdmin && (
                    <button className="btn" onClick={() => setParams({ configure: p.name })}>
                      <Icon name="sliders" className="w-3.5 h-3.5" /> Configure
                    </button>
                  )}
                </div>
              </div>
            </Card>
          ))}
        </div>
        <Card title="Polling nodes">
          <table className="tbl">
            <thead><tr><th>Node</th><th>Type</th><th>Version</th><th>Last seen</th></tr></thead>
            <tbody>
              {nodes.map((n) => (
                <tr key={n.id}><td>{n.name}</td><td>{n.is_local ? "local" : "remote"}</td><td>{n.version ?? "-"}</td>
                  <td className="text-xs">{n.last_seen ? new Date(n.last_seen).toLocaleString() : "never"}</td></tr>
              ))}
            </tbody>
          </table>
        </Card>
      </Page>
      {configure && isAdmin && <PluginSettingsModal name={configure} onClose={() => setParams({})} />}
    </>
  );
}
