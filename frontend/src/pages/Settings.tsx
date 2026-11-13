/** Settings: the setup pages behind one gear in the sidebar, as tabs, plus the chart look (per user). */
import { ReactNode, useEffect, useMemo, useRef, useState } from "react";
import { Link, useLocation } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api, Me, Series } from "../api";
import { Icon } from "../components/Icon";
import { Page, PageHeader } from "../components/Layout";
import { TimeChart } from "../components/MetricChart";
import { Card, LevelBar, StateBadge } from "../components/ui";
import { CHART_DEFAULTS, ChartPrefs, PALETTES, PaletteName, seriesPalette } from "../lib/chartTheme";

interface SettingsTab { to: string; label: string; icon: string; admin?: boolean; active: (path: string, search: string) => boolean }

export const SETTINGS_TABS: SettingsTab[] = [
  { to: "/settings/charts", label: "Charts", icon: "palette", active: (p) => p === "/settings" || p === "/settings/charts" },
  { to: "/settings/appearance", label: "Appearance", icon: "sliders", active: (p) => p === "/settings/appearance" },
  { to: "/setup/rules", label: "Threshold rules", icon: "sliders", active: (p) => p === "/setup/rules" },
  { to: "/setup/users", label: "Users & groups", icon: "users", admin: true, active: (p) => p === "/setup/users" },
  { to: "/setup/terminal", label: "Terminal access", icon: "lock", admin: true, active: (p) => p === "/setup/terminal" },
  { to: "/setup/plugins?configure=ai", label: "AI assistant", icon: "sparkles", admin: true, active: (p, s) => p === "/setup/plugins" && s.includes("configure=ai") },
  { to: "/setup/ai-tools", label: "AI tools & MCP", icon: "terminal", active: (p) => p === "/setup/ai-tools" },
  { to: "/setup/tokens", label: "API tokens", icon: "lock", admin: true, active: (p) => p === "/setup/tokens" },
  { to: "/setup/housekeeping", label: "Housekeeping", icon: "list", admin: true, active: (p) => p === "/setup/housekeeping" },
  { to: "/setup/plugins", label: "Plugins & nodes", icon: "puzzle", active: (p, s) => p === "/setup/plugins" && !s.includes("configure=ai") },
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
