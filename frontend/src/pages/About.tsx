/** About: what this NETsync is running on, statistics, the team, and how to support the project. */
import { ReactNode, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api, fmtAgo, fmtBytes, fmtDateTime, fmtDuration } from "../api";
import { Icon } from "../components/Icon";
import { Page, PageHeader } from "../components/Layout";
import { Card } from "../components/ui";
import { LogoIcon } from "../components/Brand";
import { useTheme } from "../theme";

interface About {
  product: string; version: string;
  links: Record<"github" | "docs" | "plugins" | "deploy" | "issues" | "api", string>;
  runtime: {
    python: string; platform: string; kernel: string; arch: string; os: string | null; container: string | null;
    timezone: string; db_timezone: string | null; ollama: string | null;
    api_uptime_seconds: number; node_name: string; poll_interval: number; discovery_interval: number;
  };
  packages: Record<string, string | null>;
  database: { postgres: string | null; timescaledb: string | null; size: number | null;
    tables: { name: string; retention: string; size: number | null; rows: number | null; chunks: number | null }[] };
  redis: { version?: string; memory?: string; uptime_seconds?: number };
  counts: Record<string, number>;
  plugins: { name: string; version: string; builtin: boolean }[];
  nodes: { name: string; is_local: boolean; version: string | null; last_seen: string | null }[];
}

const PIX_KEY = "elison.carriel@qsync.net";
const COMPANY_URL = "https://qsync.net";
const n = (v: number | null | undefined) => (v == null ? "-" : v >= 100_000 ? `${Math.round(v / 1000)}k` : v.toLocaleString());

/** GitHub mark (Simple Icons, CC0) */
function GitHubMark({ className = "" }: { className?: string }) {
  return (
    <svg viewBox="0 0 24 24" className={className} fill="currentColor" aria-hidden>
      <path d="M12 .297c-6.63 0-12 5.373-12 12 0 5.303 3.438 9.8 8.205 11.385.6.113.82-.258.82-.577 0-.285-.01-1.04-.015-2.04-3.338.724-4.042-1.61-4.042-1.61C4.422 18.07 3.633 17.7 3.633 17.7c-1.087-.744.084-.729.084-.729 1.205.084 1.838 1.236 1.838 1.236 1.07 1.835 2.809 1.305 3.495.998.108-.776.417-1.305.76-1.605-2.665-.3-5.466-1.332-5.466-5.93 0-1.31.465-2.38 1.235-3.22-.135-.303-.54-1.523.105-3.176 0 0 1.005-.322 3.3 1.23.96-.267 1.98-.399 3-.405 1.02.006 2.04.138 3 .405 2.28-1.552 3.285-1.23 3.285-1.23.645 1.653.24 2.873.12 3.176.765.84 1.23 1.91 1.23 3.22 0 4.61-2.805 5.625-5.475 5.92.42.36.81 1.096.81 2.22 0 1.606-.015 2.896-.015 3.286 0 .315.21.69.825.57C20.565 22.092 24 17.592 24 12.297c0-6.627-5.373-12-12-12" />
    </svg>
  );
}

function KV({ rows, mono = false }: { rows: [string, ReactNode][]; mono?: boolean }) {
  return (
    <table className="tbl"><tbody>
      {rows.map(([k, v]) => (
        <tr key={k}><td className="text-strong font-medium w-44 whitespace-nowrap">{k}</td>
          <td className={`text-fg ${mono ? "font-mono text-xs" : "text-sm"} break-words`}>{v ?? "-"}</td></tr>
      ))}
    </tbody></table>
  );
}

function Stat({ icon, label, value }: { icon: string; label: string; value: ReactNode }) {
  return (
    <div className="flex items-center gap-2.5 px-4 py-2.5 border-b border-line">
      <Icon name={icon} className="w-4 h-4 text-accent shrink-0" />
      <span className="text-sm text-strong font-medium flex-1 truncate">{label}</span>
      <span className="text-sm tabular-nums text-fg2">{value}</span>
    </div>
  );
}

function browserName(ua: string): string {
  const m = ua.match(/(Edg|OPR|Firefox|Chrome|Safari)\/(\d+)/);
  const names: Record<string, string> = { Edg: "Edge", OPR: "Opera", Firefox: "Firefox", Chrome: "Chrome", Safari: "Safari" };
  const os = /Android/.test(ua) ? "Android" : /iPhone|iPad/.test(ua) ? "iOS" : /Windows/.test(ua) ? "Windows" : /Mac OS/.test(ua) ? "macOS" : /Linux/.test(ua) ? "Linux" : "";
  return m ? `${names[m[1]]} ${m[2]}${os ? ` (${os})` : ""}` : ua;
}

function offset(minutes: number): string {
  const sign = minutes <= 0 ? "+" : "-";
  const m = Math.abs(minutes);
  return `${sign}${String(Math.floor(m / 60)).padStart(2, "0")}:${String(m % 60).padStart(2, "0")}`;
}
const fromZ = (z: string | undefined | null) => (z && /^[+-]\d{4}$/.test(z) ? `${z.slice(0, 3)}:${z.slice(3)}` : z ?? "-");

const TEAM: [string, string, string][] = [
  ["Elison Carriel", "Project lead & developer", "user"],
  ["Claude Code", "AI pair programmer (Anthropic)", "sparkles"],
  ["Betinho", "Chief cat officer: keyboard testing, nap-driven code review", "pulse"],
];
const THANKS: [string, string][] = [
  ["Observium & LibreNMS", "Inspiration for graphs, health and port views"],
  ["Checkmk", "The rules and service model"],
  ["Termix", "Ideas for the browser SSH terminal"],
  ["Muxus", "Desktop SSH client that works with the bastion"],
  ["Net-SNMP, TimescaleDB, PostgreSQL, Redis", "The foundations"],
  ["Ollama & Qwen", "Local AI"],
  ["Simple Icons", "Vendor logos (CC0)"],
];

export default function AboutPage() {
  const { theme } = useTheme();
  const { data: a } = useQuery({ queryKey: ["about"], queryFn: () => api<About>("/about"), refetchInterval: 60_000 });
  const [copied, setCopied] = useState(false);
  if (!a) return null;
  const c = a.counts;
  const r = a.runtime;
  const mode = theme === "dark" ? "dark" : "light";
  const tzUser = Intl.DateTimeFormat().resolvedOptions().timeZone;
  const copyPix = () => navigator.clipboard.writeText(PIX_KEY).then(() => { setCopied(true); setTimeout(() => setCopied(false), 1600); });

  return (
    <>
      <PageHeader title="About" sub="NETsync, what it runs on, and the people behind it" />
      <Page>
        {/* product */}
        <div className="card p-6 flex flex-col lg:flex-row lg:items-center gap-6">
          <div className="flex items-center gap-4 flex-1">
            <LogoIcon className="w-14 h-14" />
            <div>
              <div className="text-2xl font-semibold text-strong tracking-tight">{a.product}</div>
              <div className="text-sm text-muted">Version {a.version} · SNMP network monitoring with a local AI coworker</div>
              <div className="text-xs text-muted mt-1">API up {fmtDuration(r.api_uptime_seconds)} · UI built {fmtDateTime(__BUILD_TIME__)}</div>
            </div>
          </div>
          <div className="flex flex-wrap gap-2">
            <a href={a.links.github} target="_blank" rel="noopener noreferrer" className="btn"><GitHubMark className="w-4 h-4" /> GitHub</a>
            <a href={a.links.docs} target="_blank" rel="noopener noreferrer" className="btn"><Icon name="note" className="w-3.5 h-3.5" /> Docs</a>
            <a href={a.links.issues} target="_blank" rel="noopener noreferrer" className="btn"><Icon name="alert" className="w-3.5 h-3.5" /> Report an issue</a>
            <a href={a.links.api} target="_blank" rel="noopener noreferrer" className="btn"><Icon name="list" className="w-3.5 h-3.5" /> API</a>
          </div>
        </div>

        <div className="grid xl:grid-cols-2 gap-4 items-start">
          <div className="space-y-4">
            <Card title="Version information">
              <KV rows={[
                ["NETsync", `${a.version} (UI ${__APP_VERSION__})`],
                ["OS", `${r.os ?? "-"} · Linux ${r.kernel} [${r.arch}]`],
                ["Runs in", r.container ?? "host"],
                ["Python", r.python],
                ["PostgreSQL", a.database.postgres],
                ["TimescaleDB", a.database.timescaledb],
                ["Redis", a.redis.version],
                ["SNMP", a.packages.pysnmp ? `pysnmp ${a.packages.pysnmp}` : null],
                ["Web framework", a.packages.fastapi ? `FastAPI ${a.packages.fastapi} · React ${(__APP_DEPS__ as Record<string, string>).react ?? ""}` : null],
                ["AI (Ollama)", r.ollama ?? "not configured"],
              ]} />
            </Card>

            <Card title="Browser & time zone">
              <KV rows={[
                ["User agent", <span key="ua" className="text-xs">{navigator.userAgent}</span>],
                ["Browser", browserName(navigator.userAgent)],
                ["Screen", `${screen.width}×${screen.height}`],
                ["Time zone", `${fromZ(r.timezone)} (server), ${r.db_timezone ?? "-"} (database), ${offset(new Date().getTimezoneOffset())} (you, ${tzUser})`],
              ]} />
            </Card>

            <Card title="Development team">
              <table className="tbl"><tbody>
                {TEAM.map(([name, role, icon]) => (
                  <tr key={name}><td className="w-48 whitespace-nowrap"><span className="flex items-center gap-2 text-strong font-medium">
                    <Icon name={icon} className="w-4 h-4 text-accent" />{name}</span></td><td className="text-sm text-fg2">{role}</td></tr>
                ))}
              </tbody></table>
            </Card>

            <Card title="Acknowledgements">
              <table className="tbl"><tbody>
                {THANKS.map(([name, why]) => (
                  <tr key={name}><td className="w-64 text-strong font-medium">{name}</td><td className="text-sm text-fg2">{why}</td></tr>
                ))}
              </tbody></table>
            </Card>
          </div>

          <div className="space-y-4">
            <Card title="Support the project" flush={false}>
              <div className="space-y-5">
                <a href={COMPANY_URL} target="_blank" rel="noopener noreferrer" className="block" title="qsync networks">
                  <img src={`/brand/qsync-networks-gray-${mode}.svg`} alt="qsync networks" className="h-10 w-auto" />
                </a>
                <p className="text-sm text-fg2">NETsync is built by <b className="text-strong">qsync networks</b> and shared on GitHub.
                  If it saves you time, a coffee keeps it going.</p>
                <div className="flex flex-wrap items-center gap-4">
                  <button type="button" onClick={copyPix} title="Copy the Pix key" className="shrink-0">
                    <img src={`/brand/buy-me-a-coffee-${mode}.svg`} alt="Buy me a coffee" className="h-11 w-auto" />
                  </button>
                  <div className="text-sm">
                    <div className="text-xs text-muted">Pix key</div>
                    <div className="flex items-center gap-2">
                      <code className="text-strong">{PIX_KEY}</code>
                      <button className="btn h-7" onClick={copyPix}>{copied ? <><Icon name="check" className="w-3.5 h-3.5" /> Copied</> : "Copy"}</button>
                    </div>
                  </div>
                </div>
                <a href={a.links.github} target="_blank" rel="noopener noreferrer"
                  className="flex items-center gap-3 rounded-xl border border-line p-3 hover:bg-active/40 transition-colors">
                  <GitHubMark className="w-8 h-8 text-strong" />
                  <div className="min-w-0">
                    <div className="text-sm font-semibold text-strong">sagattiger/NETsync</div>
                    <div className="text-xs text-muted truncate">{a.links.github}: star it, report issues, send ideas</div>
                  </div>
                  <Icon name="external" className="w-4 h-4 text-muted ml-auto shrink-0" />
                </a>
              </div>
            </Card>

            <Card title="Statistics">
              <div className="grid sm:grid-cols-2 -mb-px">
                <Stat icon="list" label="Database size" value={fmtBytes(a.database.size)} />
                <Stat icon="pulse" label="Graph data" value={fmtBytes(c.metrics_size)} />
                <Stat icon="server" label="Devices" value={n(c.devices)} />
                <Stat icon="network" label="Ports" value={n(c.ports)} />
                <Stat icon="globe" label="IPv4 addresses" value={n(c.ipv4_addresses)} />
                <Stat icon="globe" label="IPv4 networks" value={n(c.ipv4_networks)} />
                <Stat icon="globe" label="IPv6 addresses" value={n(c.ipv6_addresses)} />
                <Stat icon="globe" label="IPv6 networks" value={n(c.ipv6_networks)} />
                <Stat icon="check" label="Services" value={n(c.services)} />
                <Stat icon="pulse" label="Probes" value={n(c.probes)} />
                <Stat icon="sliders" label="Processors" value={n(c.processors)} />
                <Stat icon="grid" label="Memory pools" value={n(c.mempools)} />
                <Stat icon="list" label="Storage entries" value={n(c.storage)} />
                <Stat icon="list" label="Disk I/O entries" value={n(c.disks)} />
                <Stat icon="sun" label="Sensors" value={n(c.sensors)} />
                <Stat icon="alert" label="Event log entries" value={n(c.events)} />
                <Stat icon="list" label="Syslog entries" value={n(c.syslog)} />
                <Stat icon="message" label="Comments" value={n(c.comments)} />
                <Stat icon="sparkles" label="AI answers" value={n(c.ai_answers)} />
                <Stat icon="terminal" label="Terminal sessions" value={n(c.terminal_sessions)} />
                <Stat icon="palette" label="Dashboards" value={n(c.dashboards)} />
                <Stat icon="users" label="Users" value={n(c.users)} />
                <Stat icon="puzzle" label="Plugins" value={`${a.plugins.length} built-in · ${n(c.container_plugins)} containers`} />
                <Stat icon="server" label="Polling nodes" value={n(a.nodes.length)} />
              </div>
            </Card>
          </div>
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
          <Card title="Runtime">
            <KV mono rows={[
              ["Platform", r.platform], ["Node name", r.node_name], ["Poll interval", `${r.poll_interval} s`],
              ["Discovery interval", fmtDuration(r.discovery_interval)], ["Redis memory", a.redis.memory],
              ["Redis uptime", fmtDuration(a.redis.uptime_seconds)],
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
          <Card title="Plugins">
            <table className="tbl"><tbody>
              {a.plugins.map((p) => (
                <tr key={p.name}><td className="text-strong">{p.name}</td><td className="font-mono text-xs">{p.version}</td>
                  <td className="text-xs text-muted">{p.builtin ? "built-in" : "external"}</td></tr>
              ))}
            </tbody></table>
          </Card>
          <Card title="Backend packages">
            <KV mono rows={Object.entries(a.packages).map(([k, v]) => [k, v ?? "not installed"])} />
          </Card>
          <Card title="Frontend packages">
            <KV mono rows={[["netsync-web", __APP_VERSION__], ...Object.entries(__APP_DEPS__).map(([k, v]) => [k, v] as [string, string])]} />
          </Card>
        </div>

        <p className="text-xs text-muted text-center pt-2">
          © qsync networks · Vendor logos by <a className="underline" href="https://simpleicons.org" target="_blank" rel="noopener noreferrer">Simple Icons</a> (CC0).
          Trademarks belong to their owners.
        </p>
      </Page>
    </>
  );
}
