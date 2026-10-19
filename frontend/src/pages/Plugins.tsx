import { useQuery } from "@tanstack/react-query";
import { api, PluginInfo } from "../api";
import { PageHeader } from "../components/Layout";
import { Card } from "../components/ui";

export default function Plugins() {
  const { data = [] } = useQuery({ queryKey: ["plugins"], queryFn: () => api<PluginInfo[]>("/plugins") });
  const { data: nodes = [] } = useQuery({
    queryKey: ["nodes"],
    queryFn: () => api<{ id: number; name: string; is_local: boolean; last_seen: string | null; version: string | null }[]>("/nodes"),
  });
  const chips = (label: string, items: string[]) =>
    items.length ? (
      <div className="flex gap-1 flex-wrap items-center">
        <span className="text-xxs text-muted w-16">{label}</span>
        {items.map((i) => <span key={i} className="px-1.5 rounded bg-line text-xxs font-mono">{i}</span>)}
      </div>
    ) : null;

  return (
    <>
      <PageHeader title="Plugins & nodes" sub="Installed extensions and polling nodes" />
      <div className="p-5 space-y-4">
        <div className="grid md:grid-cols-2 xl:grid-cols-3 gap-3">
          {data.map((p) => (
            <Card key={p.name}>
              <div className="p-3 space-y-2">
                <div className="flex justify-between items-baseline">
                  <div className="font-semibold">{p.name}</div>
                  <div className="text-xxs text-muted">v{p.version} {p.builtin && "· built-in"}</div>
                </div>
                <div className="text-xs text-gray-300">{p.description}</div>
                {chips("modules", p.modules)}
                {chips("channels", p.channels)}
                {chips("services", p.services)}
                {chips("tabs", p.ui_tabs.map((t) => t.label))}
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
      </div>
    </>
  );
}
