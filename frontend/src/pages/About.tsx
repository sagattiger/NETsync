import { ReactNode } from "react";
import { useQuery } from "@tanstack/react-query";
import { api, fmtAgo, fmtBytes, fmtDateTime, fmtDuration } from "../api";
import { Icon } from "../components/Icon";
import { Page, PageHeader } from "../components/Layout";
import { Card, Tile } from "../components/ui";

interface About {
  product: string; version: string;
  links: Record<"github" | "docs" | "plugins" | "deploy" | "issues" | "api", string>;
  runtime: { python: string; platform: string; api_uptime_seconds: number; node_name: string; poll_interval: number; discovery_interval: number };
  packages: Record<string, string | null>;
  database: { postgres: string | null; timescaledb: string | null; size: number | null;
    tables: { name: string; retention: string; size: number | null; rows: number | null; chunks: number | null }[] };
  redis: { version?: string; memory?: string; uptime_seconds?: number };
  counts: Record<string, number>;
  plugins: { name: string; version: string; builtin: boolean }[];
  nodes: { name: string; is_local: boolean; version: string | null; last_seen: string | null }[];
}

const n = (v: number | null | undefined) => (v == null ? "-" : v.toLocaleString());

function KV({ rows }: { rows: [string, ReactNode][] }) {
  return (
    <table className="tbl"><tbody>
      {rows.map(([k, v]) => (
        <tr key={k}><td className="text-muted w-44 whitespace-nowrap">{k}</td><td className="text-fg font-mono text-xs break-all">{v ?? "-"}</td></tr>
      ))}
    </tbody></table>
  );
}

export default function AboutPage() {
  const { data: a } = useQuery({ queryKey: ["about"], queryFn: () => api<About>("/about"), refetchInterval: 60_000 });
  if (!a) return null;
  const c = a.counts;
  const links: [string, string, string][] = [
    ["Documentation", a.links.docs, "note"], ["GitHub", a.links.github, "puzzle"], ["Report an issue", a.links.issues, "alert"],
    ["Plugin guide", a.links.plugins, "puzzle"], ["Deploy guide", a.links.deploy, "server"], ["API reference", a.links.api, "list"],
  ];
  const frontend = Object.entries(__APP_DEPS__);

  return (
    <>
      <PageHeader title="About" sub="System information and statistics" />
      <Page>
        <div className="card p-6 flex flex-col md:flex-row md:items-center gap-6">
          <div className="flex items-center gap-4 flex-1">
            <span className="w-14 h-14 rounded-2xl bg-accent text-white font-bold flex items-center justify-center text-2xl">N</span>
            <div>
              <div className="text-2xl font-semibold text-strong tracking-tight">{a.product}</div>
              <div className="text-sm text-muted">Version {a.version} · SNMP network monitoring</div>
              <div className="text-xs text-muted mt-1">API up {fmtDuration(a.runtime.api_uptime_seconds)} · UI built {fmtDateTime(__BUILD_TIME__)}</div>
            </div>
          </div>
          <div className="flex flex-wrap gap-2">
            {links.map(([label, href, icon]) => (
              <a key={label} href={href} target="_blank" rel="noopener noreferrer" className="btn">
                <Icon name={icon} className="w-3.5 h-3.5" /> {label}
              </a>
            ))}
          </div>
        </div>

        <div className="grid grid-cols-2 md:grid-cols-3 xl:grid-cols-6 gap-3">
          <Tile label="Devices" value={n(c.devices)} hint={c.devices_down ? `${c.devices_down} down` : "all up"} />
          <Tile label="Ports" value={n(c.ports)} hint={`${n(c.components)} components`} />
          <Tile label="Services" value={n(c.services)} hint={`${n(c.services_problems)} with problems`} />
          <Tile label="Events" value={n(c.events)} hint={`${n(c.events_24h)} in last 24h`} />
          <Tile label="Syslog entries" value={n(c.syslog)} hint={`${n(c.syslog_24h)} in last 24h`} />
          <Tile label="Database" value={fmtBytes(a.database.size)} hint="total size" />
          <Tile label="Comments" value={n(c.comments)} hint={`${n(c.pinned)} pinned`} />
          <Tile label="Device notes" value={n(c.notes)} />
          <Tile label="Dashboards" value={n(c.dashboards)} />
          <Tile label="Users" value={n(c.users)} />
          <Tile label="Plugins" value={a.plugins.length} />
          <Tile label="Polling nodes" value={a.nodes.length} />
        </div>

        <div className="grid xl:grid-cols-2 gap-4 items-start">
          <Card title="Time-series storage">
            <table className="tbl">
              <thead><tr><th>Table</th><th className="text-right">Size</th><th className="text-right">Rows (approx.)</th><th className="text-right">Chunks</th><th>Retention</th></tr></thead>
              <tbody>
                {a.database.tables.map((t) => (
                  <tr key={t.name}>
                    <td className="font-mono text-xs text-strong">{t.name}</td>
                    <td className="text-right tabular-nums">{fmtBytes(t.size)}</td>
                    <td className="text-right tabular-nums">{n(t.rows)}</td>
                    <td className="text-right tabular-nums">{n(t.chunks)}</td>
                    <td className="text-fg2">{t.retention}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </Card>

          <Card title="Database & cache">
            <KV rows={[
              ["PostgreSQL", a.database.postgres], ["TimescaleDB", a.database.timescaledb],
              ["Database size", fmtBytes(a.database.size)],
              ["Redis", a.redis.version], ["Redis memory", a.redis.memory], ["Redis uptime", fmtDuration(a.redis.uptime_seconds)],
            ]} />
          </Card>

          <Card title="Runtime">
            <KV rows={[
              ["Python", a.runtime.python], ["Platform", a.runtime.platform], ["Node name", a.runtime.node_name],
              ["Poll interval", `${a.runtime.poll_interval} s`], ["Discovery interval", fmtDuration(a.runtime.discovery_interval)],
              ["API uptime", fmtDuration(a.runtime.api_uptime_seconds)],
            ]} />
          </Card>

          <Card title="Polling nodes">
            <table className="tbl">
              <thead><tr><th>Node</th><th>Type</th><th>Version</th><th>Last seen</th></tr></thead>
              <tbody>
                {a.nodes.map((nd) => (
                  <tr key={nd.name}><td className="text-strong">{nd.name}</td><td>{nd.is_local ? "local" : "remote"}</td>
                    <td className="font-mono text-xs">{nd.version ?? "-"}</td><td className="text-xs text-fg2">{fmtAgo(nd.last_seen)}</td></tr>
                ))}
              </tbody>
            </table>
          </Card>

          <Card title="Backend packages">
            <KV rows={Object.entries(a.packages).map(([k, v]) => [k, v ?? "not installed"])} />
          </Card>

          <Card title="Frontend packages">
            <KV rows={[["netsync-web", __APP_VERSION__], ...frontend.map(([k, v]) => [k, v] as [string, string])]} />
          </Card>

          <Card title="Plugins" className="xl:col-span-2">
            <table className="tbl">
              <tbody>
                {a.plugins.map((p) => (
                  <tr key={p.name}><td className="text-strong">{p.name}</td><td className="font-mono text-xs">{p.version}</td>
                    <td className="text-xs text-muted">{p.builtin ? "built-in" : "external"}</td></tr>
                ))}
              </tbody>
            </table>
          </Card>
        </div>

        <p className="text-xs text-muted text-center pt-2">
          Vendor logos by <a className="underline" href="https://simpleicons.org" target="_blank" rel="noopener noreferrer">Simple Icons</a> (CC0).
          Trademarks belong to their owners.
        </p>
      </Page>
    </>
  );
}
