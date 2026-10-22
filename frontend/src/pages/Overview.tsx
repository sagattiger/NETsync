import { ReactNode, useEffect, useRef, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { api, Dashboard, Device, fmtAgo, fmtElapsed, Me, prefs, Service } from "../api";
import { useAI } from "../components/AskAI";
import { useCommandPalette } from "../components/CommandPalette";
import { PinnedEvents } from "../components/EventComments";
import { Icon } from "../components/Icon";
import ServiceTable from "../components/ServiceTable";
import { osLabel, VendorLogo } from "../components/VendorLogo";
import { Card, Empty, StateBadge, stateText } from "../components/ui";

interface OverviewData { devices: Record<string, number>; services: Record<string, number>; unhandled: number }
interface Insight {
  job_id: number; device_id: number; hostname: string; service: string; state: number;
  event_time: string; finished_at: string; auto: boolean; excerpt: string;
}

const STRIP_KEY = "netsync_home_strip";

function greeting(name?: string | null) {
  const h = new Date().getHours();
  const part = h < 5 ? "Good night" : h < 12 ? "Good morning" : h < 18 ? "Good afternoon" : "Good evening";
  return `${part}${name ? `, ${name.split(" ")[0]}` : ""}`;
}

/** Big tool tile (Magnific-style): colored glyph on a soft square, label below. */
function Tool({ to, onClick, icon, label, color, badge }: { to?: string; onClick?: () => void; icon: string; label: string; color: string; badge?: number }) {
  const body = (
    <>
      <span className="relative w-14 h-14 rounded-2xl bg-surface border border-line flex items-center justify-center group-hover:-translate-y-0.5 group-hover:border-edge transition-all"
        style={{ color }}>
        <Icon name={icon} className="w-6 h-6" strokeWidth={2} />
        {!!badge && <span className="absolute -top-1.5 -right-1.5 min-w-[20px] h-5 px-1 rounded-full bg-crit text-white text-xxs font-bold flex items-center justify-center">{badge}</span>}
      </span>
      <span className="text-sm font-medium text-strong">{label}</span>
    </>
  );
  const cls = "group flex flex-col items-center gap-2.5 w-24";
  return to ? <Link to={to} className={cls}>{body}</Link> : <button onClick={onClick} className={cls}>{body}</button>;
}

function Strip() {
  const [hidden, setHidden] = useState(() => { try { return localStorage.getItem(STRIP_KEY) === "hidden"; } catch { return false; } });
  const ai = useAI();
  if (hidden) return null;
  const host = window.location.hostname;
  const items: [string, string, string, boolean?][] = [
    ["list", `Syslog → ${host}:514`, "/syslog"],
    ["globe", "API", "/api/docs", true],
    ["sparkles", ai?.enabled ? `AI · ${ai.model}` : "AI assistant", "/setup/plugins?configure=ai"],
    ["puzzle", "Plugins", "/setup/plugins"],
    ["terminal", "GitHub", "https://github.com/sagattiger/NETsync", true],
  ];
  return (
    <div className="card px-4 sm:px-5 py-3 flex flex-wrap items-center gap-x-6 gap-y-2">
      <span className="text-sm font-medium text-strong mr-auto">Use NETsync everywhere you work</span>
      {items.map(([icon, label, href, external]) => {
        const inner = <><span className="w-7 h-7 rounded-full bg-inset border border-line flex items-center justify-center"><Icon name={icon} className="w-3.5 h-3.5" /></span>{label}<Icon name="external" className="w-3 h-3 text-muted" /></>;
        const cls = "flex items-center gap-2 text-xs font-medium text-fg hover:text-strong";
        return external
          ? <a key={label} href={href} target="_blank" rel="noopener noreferrer" className={cls}>{inner}</a>
          : <Link key={label} to={href} className={cls}>{inner}</Link>;
      })}
      <button className="text-muted hover:text-strong" aria-label="Hide"
        onClick={() => { setHidden(true); try { localStorage.setItem(STRIP_KEY, "hidden"); } catch { /* ignore */ } }}>
        <Icon name="x" className="w-4 h-4" />
      </button>
    </div>
  );
}

const DOT = ["#5b8def", "#a78bfa", "#3dd68c", "#f5a524", "#ff57ae", "#2dd4bf"];

function DashboardsPanel({ dashboards }: { dashboards: Dashboard[] }) {
  return (
    <section className="card p-4 flex flex-col min-h-[16rem]">
      <div className="flex items-center justify-between mb-3">
        <Link to="/dashboards" className="text-sm font-medium text-strong flex items-center gap-1 hover:text-accent">Dashboards <Icon name="chevron" className="w-3.5 h-3.5" /></Link>
        <Link to="/dashboards?new=1" className="w-7 h-7 rounded-lg bg-inset border border-line flex items-center justify-center text-fg2 hover:text-strong" title="New dashboard">
          <Icon name="plus" className="w-3.5 h-3.5" />
        </Link>
      </div>
      {!dashboards.length && <div className="text-xs text-muted py-2">No dashboards yet.</div>}
      <ul className="space-y-0.5">
        {dashboards.slice(0, 7).map((d, i) => (
          <li key={d.id}>
            <Link to={`/dashboards/${d.id}`} className="flex items-center gap-3 px-2 py-2 rounded-lg hover:bg-inset">
              <span className="w-3.5 h-3.5 rounded" style={{ background: DOT[i % DOT.length] }} />
              <span className="flex-1 text-sm text-strong truncate">{d.name}</span>
              {d.shared ? <Icon name="users" className="w-3.5 h-3.5 text-muted" /> : <Icon name="lock" className="w-3.5 h-3.5 text-muted" />}
            </Link>
          </li>
        ))}
      </ul>
    </section>
  );
}

/** Line-art illustration for the "create" card (boxes joined by curves, as in the reference design). */
function Illustration() {
  return (
    <svg viewBox="0 0 220 110" className="w-56 h-28 text-edge" fill="none" stroke="currentColor" strokeWidth="1.5" aria-hidden>
      <rect x="40" y="4" width="50" height="34" rx="6" />
      <rect x="6" y="52" width="72" height="50" rx="6" />
      <path d="M16 64h40M16 72h28M16 80h34" />
      <rect x="120" y="36" width="94" height="66" rx="6" />
      <path d="M90 12c18 6 8 30 28 46M78 76c20 0 22-12 42-16" className="text-accent" stroke="currentColor" />
      <circle cx="90" cy="12" r="2.5" fill="currentColor" /><circle cx="120" cy="60" r="2.5" fill="currentColor" className="text-accent" />
    </svg>
  );
}

function GlancePanel({ ov, devices }: { ov?: OverviewData; devices: Device[] }) {
  const s = ov?.services ?? {};
  const down = devices.filter((d) => d.status === 2).length;
  const tiles: [string, ReactNode, number | undefined][] = [
    ["Devices", devices.length, undefined], ["Down", down, down ? 2 : 0],
    ["Services OK", s.OK ?? 0, 0], ["Warning", s.WARN ?? 0, (s.WARN ?? 0) ? 1 : undefined],
    ["Critical", s.CRIT ?? 0, (s.CRIT ?? 0) ? 2 : undefined], ["Unhandled", ov?.unhandled ?? 0, (ov?.unhandled ?? 0) ? 2 : undefined],
  ];
  return (
    <section className="card p-5 flex flex-col">
      <div className="text-sm font-medium text-strong mb-4">Network at a glance</div>
      <div className="grid grid-cols-2 sm:grid-cols-3 gap-3 flex-1">
        {tiles.map(([label, value, tone]) => (
          <div key={label} className="rounded-xl bg-inset/60 border border-line px-4 py-3">
            <div className="text-xs text-muted">{label}</div>
            <div className={`text-2xl font-semibold tabular-nums mt-0.5 ${tone !== undefined ? stateText(tone) : "text-strong"}`}>{value}</div>
          </div>
        ))}
      </div>
    </section>
  );
}

function CreatePanel() {
  const nav = useNavigate();
  return (
    <section className="card p-5 flex flex-col items-center justify-center text-center gap-3 min-h-[16rem]">
      <Illustration />
      <div>
        <div className="text-base font-medium text-strong">Create a dashboard</div>
        <div className="text-xs text-muted mt-1 max-w-xs">Put interface traffic, CPU, latency and TCP/UDP graphs of any device side by side.</div>
      </div>
      <button className="btn btn-primary" onClick={() => nav("/dashboards?new=1")}>New dashboard <Icon name="plus" className="w-3.5 h-3.5" /></button>
    </section>
  );
}

// --------------------------------------------------------------------------- carousel

const GRADIENT = [
  "linear-gradient(135deg, rgb(var(--ok) / 0.28), rgb(var(--ok) / 0.04))",
  "linear-gradient(135deg, rgb(var(--warn) / 0.30), rgb(var(--warn) / 0.04))",
  "linear-gradient(135deg, rgb(var(--crit) / 0.30), rgb(var(--crit) / 0.04))",
  "linear-gradient(135deg, rgb(var(--unknown) / 0.30), rgb(var(--unknown) / 0.04))",
];

function SlideCard({ tag, title, text, state, to, cta, device }: {
  tag: ReactNode; title: string; text: string; state: number; to: string; cta: string; device?: Device;
}) {
  return (
    <Link to={to} className="snap-start shrink-0 w-[85%] sm:w-[22rem] h-60 rounded-2xl border border-line overflow-hidden relative group flex flex-col justify-between p-5"
      style={{ background: GRADIENT[state] ?? GRADIENT[0] }}>
      <div className="flex items-start justify-between gap-3">
        <span className="inline-flex items-center gap-1 text-xxs font-medium px-2 py-1 rounded-md bg-surface/80 text-fg2 backdrop-blur">{tag}</span>
        {device && <VendorLogo device={device} size={36} />}
      </div>
      <div>
        <div className="text-xl font-semibold text-strong leading-tight tracking-tight line-clamp-2">{title}</div>
        <div className="text-xs text-fg2 mt-1.5 line-clamp-3">{text}</div>
      </div>
      <span className="self-start text-xs font-medium px-3 py-1.5 rounded-lg bg-primary text-on-primary group-hover:opacity-90">{cta}</span>
    </Link>
  );
}

function Carousel({ insights, problems, devices }: { insights: Insight[]; problems: Service[]; devices: Device[] }) {
  const ai = useAI();
  const tabs: [string, string][] = [
    ...(ai?.enabled ? [["ai", "AI insights"] as [string, string]] : []),
    ["problems", "Open problems"], ["devices", "Devices"],
  ];
  const [picked, setPicked] = useState<string | null>(null);
  // default to the first tab (AI insights once the AI status has loaded) until the user picks one
  const tab = picked && tabs.some(([t]) => t === picked) ? picked : tabs[0][0];
  const setTab = setPicked;
  const [page, setPage] = useState(0);
  const track = useRef<HTMLDivElement>(null);
  const byId = (id: number) => devices.find((d) => d.id === id);

  useEffect(() => { track.current?.scrollTo({ left: 0 }); setPage(0); }, [tab]);

  const slides: ReactNode[] =
    tab === "ai" ? insights.map((i) => (
      <SlideCard key={i.job_id} state={i.state} device={byId(i.device_id)} to={`/devices/${i.device_id}/events`} cta="Read analysis"
        tag={<><Icon name="sparkles" className="w-3 h-3 text-accent" /> {i.auto ? "AI · automatic" : "AI · asked"} · {fmtAgo(i.finished_at)}</>}
        title={`${i.hostname.split(".")[0]} · ${i.service}`} text={i.excerpt} />
    ))
    : tab === "problems" ? problems.filter((p) => !p.resolved).map((p) => (
      <SlideCard key={p.id} state={p.state} device={byId(p.device_id)} to={`/devices/${p.device_id}`} cta="Open device"
        tag={<><StateBadge state={p.state} small /> for {fmtElapsed(p.duration)}</>}
        title={`${(p.hostname ?? "").split(".")[0]} · ${p.name}`} text={p.output ?? ""} />
    ))
    : [...devices].sort((a, b) => b.id - a.id).slice(0, 12).map((d) => (
      <SlideCard key={d.id} state={d.status} device={d} to={`/devices/${d.id}`} cta="Open device"
        tag={<>{osLabel(d.os, d.version) || "Device"}</>} title={d.hostname.split(".")[0]}
        text={[d.ip ?? d.ip_addresses?.[0], d.hardware, d.sys_location].filter(Boolean).join(" · ")} />
    ));

  const pages = Math.max(1, Math.ceil(slides.length / 3));
  const scroll = (dir: number) => {
    const el = track.current;
    if (!el) return;
    el.scrollBy({ left: dir * el.clientWidth * 0.9, behavior: "smooth" });
  };
  const onScroll = () => {
    const el = track.current;
    if (el) setPage(Math.round((el.scrollLeft / Math.max(1, el.scrollWidth - el.clientWidth)) * (pages - 1)));
  };

  return (
    <section className="space-y-4">
      <div className="flex items-center justify-between gap-3">
        <div className="flex gap-1 overflow-x-auto">
          {tabs.map(([t, label]) => (
            <button key={t} onClick={() => setTab(t)}
              className={`px-3.5 py-1.5 rounded-lg text-sm whitespace-nowrap transition-colors ${tab === t ? "bg-active text-strong font-medium" : "text-muted hover:text-strong"}`}>
              {label}
            </button>
          ))}
        </div>
        <Link to={tab === "devices" ? "/devices" : "/problems"} className="text-sm font-medium text-strong flex items-center gap-1 hover:text-accent whitespace-nowrap">
          Explore all <Icon name="chevron" className="w-3.5 h-3.5" />
        </Link>
      </div>
      {slides.length ? (
        <>
          <div ref={track} onScroll={onScroll} className="flex gap-4 overflow-x-auto snap-x snap-mandatory pb-1 [scrollbar-width:none] [&::-webkit-scrollbar]:hidden">
            {slides}
          </div>
          <div className="flex items-center justify-center relative h-8">
            <div className="flex gap-1.5">
              {Array.from({ length: pages }).map((_, i) => (
                <span key={i} className={`h-1.5 rounded-full transition-all ${i === page ? "w-6 bg-strong" : "w-1.5 bg-faint"}`} />
              ))}
            </div>
            <div className="absolute right-0 flex gap-2">
              <button onClick={() => scroll(-1)} className="w-8 h-8 rounded-full border border-line text-fg2 hover:text-strong flex items-center justify-center" aria-label="Previous">
                <Icon name="chevron" className="w-4 h-4 rotate-180" />
              </button>
              <button onClick={() => scroll(1)} className="w-8 h-8 rounded-full bg-primary text-on-primary flex items-center justify-center" aria-label="Next">
                <Icon name="chevron" className="w-4 h-4" />
              </button>
            </div>
          </div>
        </>
      ) : (
        <div className="card"><Empty>{tab === "ai" ? "No AI analyses yet." : tab === "problems" ? "No open problems." : "No devices yet."}</Empty></div>
      )}
    </section>
  );
}

// --------------------------------------------------------------------------- page

export default function Overview() {
  const palette = useCommandPalette();
  const ai = useAI();
  const refresh = prefs.refreshMs(30_000);
  const { data: me } = useQuery({ queryKey: ["me"], queryFn: () => api<Me>("/auth/me") });
  const { data: ov } = useQuery({ queryKey: ["overview"], queryFn: () => api<OverviewData>("/overview"), refetchInterval: refresh });
  const { data: problems = [] } = useQuery({
    queryKey: ["problems", "unhandled"], queryFn: () => api<Service[]>("/problems?include_acked=false"), refetchInterval: refresh,
  });
  const { data: devices = [] } = useQuery({ queryKey: ["devices"], queryFn: () => api<Device[]>("/devices"), refetchInterval: refresh });
  const { data: dashboards = [] } = useQuery({ queryKey: ["dashboards"], queryFn: () => api<Dashboard[]>("/dashboards") });
  const { data: insights = [] } = useQuery({
    queryKey: ["ai-insights"], queryFn: () => api<Insight[]>("/plugins/ai/insights?limit=12"), enabled: !!ai?.enabled, refetchInterval: 60_000,
  });

  const open = problems.filter((p) => !p.resolved);
  const down = devices.filter((d) => d.status === 2).length;
  const summary = !devices.length ? "Add your first device to start monitoring."
    : open.length ? `${open.length} problem${open.length === 1 ? " needs" : "s need"} attention${down ? ` · ${down} device${down === 1 ? "" : "s"} down` : ""}`
    : `All ${devices.length} devices are healthy.`;

  return (
    <div className="px-4 sm:px-8 pb-12">
      {/* hero */}
      <div className="pt-6 sm:pt-10 pb-8 flex flex-col items-center text-center">
        <h1 className="text-3xl sm:text-4xl font-bold text-strong tracking-tight">{greeting(me?.full_name || me?.username)}</h1>
        <p className={`mt-2 text-sm ${open.length ? "text-fg2" : "text-muted"}`}>{summary}</p>
        <button onClick={() => palette.open()}
          className="mt-7 w-full max-w-3xl h-14 px-5 rounded-2xl bg-surface border border-edge hover:border-faint flex items-center gap-3 text-left transition-colors">
          <Icon name="search" className="w-5 h-5 text-muted" />
          <span className="flex-1 text-base text-muted">Search devices or jump to a page…</span>
          <kbd className="hidden sm:inline text-xs text-muted">Ctrl K</kbd>
        </button>

        <div className="mt-10 flex flex-wrap justify-center gap-x-4 gap-y-6">
          <Tool to="/devices" icon="server" label="Devices" color="#5b8def" />
          <Tool to="/problems" icon="alert" label="Problems" color="rgb(var(--crit))" badge={open.length} />
          <Tool to="/dashboards" icon="palette" label="Dashboards" color="#a78bfa" />
          <Tool to="/syslog" icon="list" label="Syslog" color="#2dd4bf" />
          {ai?.enabled !== undefined && <Tool to={me?.role === "admin" ? "/setup/plugins?configure=ai" : "/problems"} icon="sparkles" label="AI assistant" color="rgb(var(--accent))" />}
          {me?.role !== "viewer" && <Tool to="/devices?add=1" icon="plus" label="Add device" color="#3dd68c" />}
          <Tool onClick={() => palette.open()} icon="grid" label="All tools" color="rgb(var(--fg))" />
        </div>
      </div>

      <div className="space-y-5 max-w-[90rem] mx-auto">
        <Strip />

        <div className="grid lg:grid-cols-[minmax(0,1fr)_minmax(0,2fr)] gap-5">
          <DashboardsPanel dashboards={dashboards} />
          {dashboards.length ? <GlancePanel ov={ov} devices={devices} /> : <CreatePanel />}
        </div>

        <PinnedEvents showDevice />

        <Card title={`Unhandled problems · ${open.length}`} actions={
          <Link to="/problems" className="text-xs font-medium text-fg2 hover:text-strong flex items-center gap-1">All problems <Icon name="chevron" className="w-3 h-3" /></Link>
        }>
          {problems.length ? <ServiceTable services={problems} showHost problems /> : <Empty>Everything is OK.</Empty>}
        </Card>

        <div className="pt-4">
          <Carousel insights={insights} problems={problems} devices={devices} />
        </div>
      </div>
    </div>
  );
}
