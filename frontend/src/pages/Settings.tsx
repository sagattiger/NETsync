/** Settings: the setup pages behind one gear in the sidebar, as tabs, plus the chart look (per user). */
import { ReactNode, useEffect, useMemo, useRef, useState } from "react";
import { Link, useLocation, useParams } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api, Me, PluginSettings, Series } from "../api";
import { Field } from "../components/PluginSettingsModal";
import { Icon } from "../components/Icon";
import { Page, PageHeader } from "../components/Layout";
import Housekeeping from "./Housekeeping";
import Tokens from "./Tokens";
import { IgnorePickerButton, PICKER_SECTIONS } from "./settings/IgnorePicker";
import { TimeChart } from "../components/MetricChart";
import { Card, LevelBar, StateBadge } from "../components/ui";
import { CHART_DEFAULTS, ChartPrefs, PALETTES, PaletteName, seriesPalette } from "../lib/chartTheme";

interface SettingsTab { to: string; label: string; icon: string; admin?: boolean; active: (path: string, search: string) => boolean }

export const SETTINGS_TABS: SettingsTab[] = [
  { to: "/settings/general/branding", label: "General", icon: "gear", admin: true, active: (p) => p.startsWith("/settings/general") },
  { to: "/settings/charts", label: "Charts", icon: "palette", active: (p) => p === "/settings" || p === "/settings/charts" },
  { to: "/settings/appearance", label: "Appearance", icon: "sliders", active: (p) => p === "/settings/appearance" },
  { to: "/settings/sites", label: "Sites", icon: "globe", active: (p) => p === "/settings/sites" },
  { to: "/setup/rules", label: "Threshold rules", icon: "sliders", active: (p) => p === "/setup/rules" },
  { to: "/setup/users", label: "Users & groups", icon: "users", admin: true, active: (p) => p === "/setup/users" },
  { to: "/setup/terminal", label: "Terminal access", icon: "lock", admin: true, active: (p) => p === "/setup/terminal" },
  { to: "/setup/ai-tools", label: "AI tools & MCP", icon: "terminal", active: (p) => p === "/setup/ai-tools" },
  { to: "/setup/plugins", label: "Plugins & nodes", icon: "puzzle", active: (p) => p === "/setup/plugins" },
];

export const isSettingsPath = (path: string) =>
  path.startsWith("/settings") || (path.startsWith("/setup/") && !["/setup/notifications", "/setup/store"].includes(path));

const useMeQuery = () => useQuery({ queryKey: ["me"], queryFn: () => api<Me>("/auth/me") });

/** Tab bar above every settings page. */
export function SettingsShell({ children }: { children: ReactNode }) {
  const { pathname, search } = useLocation();
  const me = useMeQuery().data;
  const tabs = SETTINGS_TABS.filter((t) => !t.admin || me?.role === "admin");
  return (
    <>
      <div className="px-4 sm:px-8 pt-3">
        <div className="flex items-center gap-2 text-xs text-muted mb-2"><Icon name="gear" className="w-3.5 h-3.5" /> Settings</div>
        <div className="flex gap-1 overflow-x-auto border-b border-line">
          {tabs.map((t) => {
            const on = t.active(pathname, search);
            return (
              <Link key={t.to} to={t.to}
                className={`flex items-center gap-1.5 px-3 py-2 -mb-px text-sm whitespace-nowrap border-b-2 transition-colors ${on ? "border-accent text-strong font-medium" : "border-transparent text-muted hover:text-fg"}`}>
                <Icon name={t.icon} className="w-3.5 h-3.5" />{t.label}
              </Link>
            );
          })}
        </div>
      </div>
      {children}
    </>
  );
}

// --------------------------------------------------------------------------- Charts tab

function demoSeries(): Series {
  const now = Date.now();
  const out: Series = { a: [], b: [], c: [] };
  for (let i = 0; i < 96; i++) {
    const t = new Date(now - (96 - i) * 15 * 60_000).toISOString();
    const w = Math.sin(i / 9);
    const spike = i % 31 === 0 ? 18 : 0;
    out.a.push([t, 32 + 10 * w + spike + (i % 7), 0, 0]);
    out.b.push([t, 18 + 6 * Math.cos(i / 7) + (i % 5), 0, 0]);
    out.c.push([t, 8 + 3 * Math.sin(i / 4) + (i % 3), 0, 0]);
  }
  return out;
}

function Choice<T extends string>({ value, options, onChange }: { value: T; options: [T, string][]; onChange: (v: T) => void }) {
  return (
    <div className="inline-flex rounded-lg border border-line p-0.5 bg-inset">
      {options.map(([k, l]) => (
        <button key={k} type="button" onClick={() => onChange(k)}
          className={`px-3 h-7 rounded-md text-xs ${value === k ? "bg-surface text-strong shadow-sm font-medium" : "text-muted hover:text-fg"}`}>{l}</button>
      ))}
    </div>
  );
}

function Row({ label, help, children }: { label: string; help?: string; children: ReactNode }) {
  return (
    <div className="flex flex-col sm:flex-row sm:items-center gap-2 py-3 border-b border-line last:border-0">
      <div className="sm:w-56 shrink-0"><div className="text-sm text-strong">{label}</div>{help && <div className="text-xs text-muted">{help}</div>}</div>
      <div className="flex-1 flex flex-wrap items-center gap-2">{children}</div>
    </div>
  );
}

export function ChartSettings() {
  const qc = useQueryClient();
  const me = useMeQuery().data;
  const saved = useMemo(() => ({ ...CHART_DEFAULTS, ...(me?.preferences.chart ?? {}) }), [me]);
  const [status, setStatus] = useState("");
  const timer = useRef<number>();
  const data = useMemo(demoSeries, []);

  // changes apply at once everywhere (through the cached profile) and are saved shortly after
  const change = (patch: Partial<ChartPrefs>) => {
    if (!me) return;
    const next = { ...saved, ...patch };
    qc.setQueryData(["me"], { ...me, preferences: { ...me.preferences, chart: next } });
    setStatus("Saving…");
    window.clearTimeout(timer.current);
    timer.current = window.setTimeout(() => {
      api<Me>("/auth/me", { method: "PATCH", body: { preferences: { chart: next } } })
        .then((m) => { qc.setQueryData(["me"], m); setStatus("Saved"); })
        .catch((e) => setStatus(`Not saved: ${e.message}`));
    }, 600);
  };
  useEffect(() => () => window.clearTimeout(timer.current), []);

  const palette = seriesPalette();
  const customColors = saved.colors.length ? saved.colors : palette.slice(0, 6);

  return (
    <Page>
      <PageHeader title="Charts" sub="How graphs look for you, on every device page and dashboard. Saved to your profile."
        actions={<>
          <span className="text-xs text-muted">{status}</span>
          <button className="btn" onClick={() => change({ ...CHART_DEFAULTS })}>Reset to defaults</button>
        </>} />
      <div className="grid xl:grid-cols-2 gap-4 items-start">
        <Card title="Look" flush={false}>
          <Row label="Colours" help="Order of the series colours">
            <select className="input h-8" value={saved.palette} onChange={(e) => change({ palette: e.target.value as PaletteName })}>
              {Object.entries(PALETTES).map(([k, p]) => <option key={k} value={k}>{p.label}</option>)}
            </select>
            <span className="flex gap-1">{palette.slice(0, 6).map((c, i) => <span key={i} className="w-4 h-4 rounded" style={{ background: c }} />)}</span>
          </Row>
          {saved.palette === "custom" && (
            <Row label="My colours" help="Series 1 to 6">
              {customColors.map((c, i) => (
                <input key={i} type="color" value={/^#[0-9a-f]{6}$/i.test(c) ? c : "#888888"} className="w-9 h-8 rounded border border-line bg-transparent cursor-pointer"
                  onChange={(e) => { const cs = [...customColors]; cs[i] = e.target.value; change({ colors: cs }); }} />
              ))}
            </Row>
          )}
          <Row label="Default style" help="Charts that let you choose">
            <Choice value={saved.style} options={[["area", "Area"], ["line", "Line only"]]} onChange={(style) => change({ style })} />
          </Row>
          <Row label="Fill under lines">
            <Choice value={saved.fill} options={[["gradient", "Fading"], ["solid", "Solid"], ["none", "None"]]} onChange={(fill) => change({ fill })} />
          </Row>
          {saved.fill !== "none" && (
            <Row label="Fill strength">
              <input type="range" min={0.05} max={0.6} step={0.05} value={saved.fill_opacity} onChange={(e) => change({ fill_opacity: Number(e.target.value) })} className="w-48 accent-accent" />
              <span className="text-xs text-muted tabular-nums">{Math.round(saved.fill_opacity * 100)}%</span>
            </Row>
          )}
          <Row label="Line width">
            <input type="range" min={0.75} max={3.5} step={0.25} value={saved.line_width} onChange={(e) => change({ line_width: Number(e.target.value) })} className="w-48 accent-accent" />
            <span className="text-xs text-muted tabular-nums">{saved.line_width} px</span>
          </Row>
          <Row label="Curves" help="Smooth curves or straight segments between points">
            <Choice value={saved.smooth ? "on" : "off"} options={[["on", "Smooth"], ["off", "Straight"]]} onChange={(v) => change({ smooth: v === "on" })} />
          </Row>
          <Row label="Grid lines">
            <Choice value={saved.grid ? "on" : "off"} options={[["on", "Show"], ["off", "Hide"]]} onChange={(v) => change({ grid: v === "on" })} />
          </Row>
          <Row label="Glow" help="Neon halo on lines and dots (dark mode)">
            <Choice value={saved.glow ? "on" : "off"} options={[["off", "Off"], ["on", "On"]]} onChange={(v) => change({ glow: v === "on" })} />
          </Row>
        </Card>
        <Card title="Preview" flush={false}>
          <TimeChart data={data} metrics={[{ name: "a", label: "Series 1" }, { name: "b", label: "Series 2" }, { name: "c", label: "Series 3" }]}
            unit="%" height={260} range="24h" />
        </Card>
      </div>
    </Page>
  );
}

// --------------------------------------------------------------------------- Appearance tab

type Corners = "rounded" | "medium" | "small" | "sharp";
type Pills = "round" | "soft" | "square";

export function AppearanceSettings() {
  const qc = useQueryClient();
  const me = useMeQuery().data;
  const [status, setStatus] = useState("");
  const corners: Corners = me?.preferences.corners ?? "rounded";
  const pills: Pills = me?.preferences.pills ?? "round";

  const change = (patch: { corners?: Corners; pills?: Pills }) => {
    if (!me) return;
    qc.setQueryData(["me"], { ...me, preferences: { ...me.preferences, ...patch } });  // applied by the layout at once
    setStatus("Saving…");
    api<Me>("/auth/me", { method: "PATCH", body: { preferences: patch } })
      .then((m) => { qc.setQueryData(["me"], m); setStatus("Saved"); })
      .catch((e) => setStatus(`Not saved: ${e.message}`));
  };

  return (
    <Page>
      <PageHeader title="Appearance" sub="Shape of cards, buttons, inputs and badges. Saved to your profile."
        actions={<>
          <span className="text-xs text-muted">{status}</span>
          <button className="btn" onClick={() => change({ corners: "rounded", pills: "round" })}>Reset to defaults</button>
        </>} />
      <div className="grid xl:grid-cols-2 gap-4 items-start">
        <Card title="Shape" flush={false}>
          <Row label="Corners" help="Cards, buttons, inputs, menus">
            <Choice value={corners} options={[["rounded", "Rounded"], ["medium", "Medium"], ["small", "Small"], ["sharp", "Sharp"]]}
              onChange={(c) => change({ corners: c })} />
          </Row>
          <Row label="Badges and pills" help="Status and count badges">
            <Choice value={pills} options={[["round", "Round"], ["soft", "Soft"], ["square", "Square"]]} onChange={(p) => change({ pills: p })} />
          </Row>
          <div className="text-xs text-muted pt-3">Table spacing, theme and time format are on your <Link to="/profile" className="text-accent underline">profile</Link>.</div>
        </Card>
        <Card title="Preview" flush={false}>
          <div className="space-y-4">
            <div className="flex flex-wrap gap-2 items-center">
              <StateBadge state={0} small label="21.0 °C" /><StateBadge state={1} small label="72.0 °C" /><StateBadge state={2} small label="88.0 °C" />
              <span className="pill text-xxs px-2 py-0.5 bg-chip border-line text-fg2">× 24 threads</span>
            </div>
            <div className="flex flex-wrap gap-2"><button className="btn btn-primary">Primary</button><button className="btn">Button</button>
              <input className="input h-8 w-40" placeholder="Input" /></div>
            <div className="card p-3 text-sm">A card</div>
            <LevelBar value={53} max={100} warn={70} crit={85} fmt={(v) => `${v.toFixed(1)} °C`} />
          </div>
        </Card>
      </div>
    </Page>
  );
}

// --------------------------------------------------------------------------- General tab (admins)

interface Autodiscovery {
  finished?: string; seconds?: number; scanned?: number; pinged?: number | null; answered?: number; running?: boolean; error?: string;
  added?: { id: number; hostname: string; ip: string }[]; skipped?: { ip: string; hostname?: string; reason: string }[];
}

/** Sub-tabs of Settings → General: the first six are the "general" settings, the last two are their own pages. */
const GENERAL_TABS: { slug: string; label: string; icon: string; tab?: string; sub?: string }[] = [
  { slug: "branding", label: "Branding", icon: "palette", tab: "Branding", sub: "Logo, colour, name and the default time format." },
  { slug: "discovery", label: "Discovery", icon: "search", tab: "Discovery", sub: "What discovery collects, what it ignores, and finding new devices." },
  { slug: "entities", label: "Entities", icon: "list", tab: "Entities", sub: "How ports, disks, sensors and the rest are kept once found." },
  { slug: "alerting", label: "Alerting", icon: "bell", tab: "Alerting", sub: "When notifications are held back. Who gets them is set in Notifications." },
  { slug: "authentication", label: "Authentication", icon: "lock", tab: "Authentication", sub: "Sign-in sessions and protection against password guessing." },
  { slug: "network", label: "Network", icon: "globe", tab: "Network", sub: "SNMP timing and the address NETsync is reached at." },
  { slug: "housekeeping", label: "Housekeeping", icon: "list" },
  { slug: "api-tokens", label: "API tokens", icon: "lock" },
];

function AutodiscoveryStatus({ onMsg }: { onMsg: (m: { ok: boolean; text: string }) => void }) {
  const qc = useQueryClient();
  const { data: scan } = useQuery({ queryKey: ["autodiscovery"], queryFn: () => api<Autodiscovery>("/plugins/general/autodiscovery"), refetchInterval: 10_000 });
  async function scanNow() {
    try {
      const r = await api<{ ok: boolean; message: string }>("/plugins/general/autodiscovery/run", { method: "POST" });
      onMsg({ ok: r.ok, text: r.message });
      qc.invalidateQueries({ queryKey: ["autodiscovery"] });
    } catch (e: any) { onMsg({ ok: false, text: e.message }); }
  }
  return (
    <div className="border-t border-line pt-3 space-y-2">
      <div className="flex items-center gap-2">
        <button className="btn" onClick={scanNow}><Icon name="refresh" className="w-3.5 h-3.5" /> Scan now</button>
        <span className="text-xs text-muted">Uses the saved settings: save your changes first.</span>
      </div>
      <div className="text-xs text-fg2 space-y-1">
        {scan?.running ? "Scanning…" : scan?.error ? <span className="text-crit">Last scan failed: {scan.error}</span>
          : scan?.finished ? (
            <>
              <div>Last scan {new Date(scan.finished).toLocaleString()}: {scan.scanned} addresses in {scan.seconds}s
                {scan.pinged != null && <>, {scan.pinged} answered ping</>}, {scan.answered} answered SNMP, {scan.added?.length ?? 0} added
                {scan.added?.length ? <>: {scan.added.map((d) => d.hostname).join(", ")}</> : null}</div>
              {!!scan.skipped?.length && <div className="text-muted">Skipped: {scan.skipped.map((d) => `${d.hostname ?? d.ip} (${d.reason})`).join(", ")}</div>}
            </>
          ) : "No scan yet."}
      </div>
    </div>
  );
}

function IpTypeTry() {
  const [addr, setAddr] = useState("");
  const [kind, setKind] = useState("");
  async function check() {
    if (!addr.trim()) return;
    try { setKind((await api<{ type: string }>("/plugins/general/ip-type", { method: "POST", body: { address: addr.trim() } })).type); }
    catch (e: any) { setKind(e.message); }
  }
  return (
    <div className="flex items-center gap-2 text-xs">
      <input className="input w-56 font-mono text-xs" placeholder="Try an address, e.g. fe80::1" value={addr}
        onChange={(e) => { setAddr(e.target.value); setKind(""); }} onKeyDown={(e) => e.key === "Enter" && check()} />
      <button type="button" className="btn text-xs" onClick={check}>Type?</button>
      {kind && <span className="text-strong">{kind}</span>}
    </div>
  );
}

export function GeneralSettings() {
  const { tab: slug = "branding" } = useParams();
  const current = GENERAL_TABS.find((t) => t.slug === slug) ?? GENERAL_TABS[0];
  return (
    <>
      <div className="px-4 sm:px-8 pt-3">
        <div className="flex flex-wrap gap-1">
          {GENERAL_TABS.map((t) => (
            <Link key={t.slug} to={`/settings/general/${t.slug}`}
              className={`flex items-center gap-1.5 px-2.5 py-1 rounded-md text-xs transition-colors ${t.slug === current.slug ? "bg-accent/15 text-strong font-medium" : "text-muted hover:text-fg hover:bg-inset"}`}>
              <Icon name={t.icon} className="w-3.5 h-3.5" />{t.label}
            </Link>
          ))}
        </div>
      </div>
      {current.slug === "housekeeping" ? <Housekeeping /> : current.slug === "api-tokens" ? <Tokens /> : <GeneralForm key={current.slug} tab={current.tab!} label={current.label} sub={current.sub!} />}
    </>
  );
}

function GeneralForm({ tab, label, sub }: { tab: string; label: string; sub: string }) {
  const qc = useQueryClient();
  const { data: settings } = useQuery({ queryKey: ["plugin-settings", "general"], queryFn: () => api<PluginSettings>("/plugins/general/settings") });
  const [config, setConfig] = useState<Record<string, any>>({});
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const [busy, setBusy] = useState(false);
  useEffect(() => { if (settings) setConfig(settings.config); }, [settings]);
  const fields = (settings?.fields ?? []).filter((f) => (f.tab ?? "Branding") === tab);
  const sections = [...new Set(fields.map((f) => f.section ?? "Settings"))];
  const dirty = !!settings && fields.some((f) => JSON.stringify(config[f.key]) !== JSON.stringify(settings.config[f.key]));

  async function save() {
    setBusy(true); setMsg(null);
    try {
      const saved = await api<PluginSettings & { notes?: string[] }>("/plugins/general/settings", { method: "PUT", body: { enabled: true, config } });
      qc.setQueryData(["plugin-settings", "general"], saved);
      qc.invalidateQueries({ queryKey: ["branding"] });
      qc.invalidateQueries({ queryKey: ["discovered"] });
      const notes = (saved.notes ?? []).join(" ");
      setMsg({ ok: true, text: tab === "Discovery" || tab === "Entities" ? `Saved. ${notes || "Applies at each device's next discovery."}` : "Saved." });
    } catch (e: any) { setMsg({ ok: false, text: e.message }); }
    setBusy(false);
  }

  return (
    <Page>
      <PageHeader title={label} sub={sub}
        actions={<button className="btn btn-primary" onClick={save} disabled={busy || !settings || !dirty}>{busy ? "Saving…" : dirty ? "Save" : "Saved"}</button>} />
      {msg && <div className={`text-sm ${msg.ok ? "text-ok" : "text-crit"}`}>{msg.text}</div>}
      <div className="grid xl:grid-cols-2 gap-4 items-start">
        {sections.map((sec) => (
          <Card key={sec} title={sec} flush={false}>
            <div className="space-y-4">
              {PICKER_SECTIONS[sec] && <IgnorePickerButton kind={PICKER_SECTIONS[sec]} config={config} set={(k, v) => setConfig((c) => ({ ...c, [k]: v }))} />}
              {fields.filter((f) => (f.section ?? "Settings") === sec).map((f) => (
                <Field key={f.key} f={f} plugin="general" config={config} set={(k, v) => setConfig((c) => ({ ...c, [k]: v }))} />
              ))}
              {sec === "What discovery collects" && <p className="text-xs text-muted">Switching one off stops collecting it. Ignored or switched-off entities already found are removed after the number of discoveries set in Entities.</p>}
              {sec === "IP address discovery" && <IpTypeTry />}
              {sec === "Device autodiscovery" && <AutodiscoveryStatus onMsg={setMsg} />}
              {sec === "Notifications" && <p className="text-xs text-muted">Channels, recipients and the minimum state are set per rule in <Link className="text-accent hover:underline" to="/setup/notifications">Notifications</Link>.</p>}
              {sec === "Sign-in protection" && <p className="text-xs text-muted">Counts failures per user name and address, so one person guessing doesn't lock everyone else out.</p>}
            </div>
          </Card>
        ))}
      </div>
    </Page>
  );
}
