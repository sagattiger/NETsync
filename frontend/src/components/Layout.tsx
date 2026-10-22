import { ReactNode, useCallback, useEffect, useState } from "react";
import { Link, NavLink, Outlet, useLocation, useNavigate } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api, auth, Me, prefs } from "../api";
import { useTheme } from "../theme";
import { useAI } from "./AskAI";
import { Avatar } from "./Avatar";
import { CommandPaletteProvider, useCommandPalette } from "./CommandPalette";
import { Icon } from "./Icon";

interface Overview { devices: Record<string, number>; services: Record<string, number>; unhandled: number }

const SIDEBAR_KEY = "netsync_sidebar";
// Shown once as a pill in the header until dismissed (dismissal is saved per user).
const NOTICE = { id: "ai-problems-2026-10", text: "AI assistant now explains problems and syslog", cta: "See problems", to: "/problems" };

function useLiveEvents() {
  const qc = useQueryClient();
  useEffect(() => {
    if (!auth.token) return;
    let ws: WebSocket | null = null;
    let retry: number | undefined;
    const connect = () => {
      const proto = location.protocol === "https:" ? "wss" : "ws";
      ws = new WebSocket(`${proto}://${location.host}/api/ws?token=${auth.token}`);
      ws.onmessage = () => {
        // state changes and finished AI analyses: refresh lists, threads and stickers
        for (const key of ["overview", "problems", "services", "devices", "device", "history", "pinned", "syslog", "ai-insights"]) qc.invalidateQueries({ queryKey: [key] });
      };
      ws.onclose = () => { retry = window.setTimeout(connect, 5000); };
    };
    connect();
    return () => { window.clearTimeout(retry); if (ws) { ws.onclose = null; ws.close(); } };
  }, [qc]);
}

/** Sidebar expanded/collapsed: local copy for an instant first paint, profile copy to follow the user. */
function useSidebar(me?: Me) {
  const [collapsed, setCollapsed] = useState(() => {
    try { return localStorage.getItem(SIDEBAR_KEY) === "collapsed"; } catch { return false; }
  });
  const qc = useQueryClient();
  useEffect(() => {
    if (me?.preferences.sidebar) setCollapsed(me.preferences.sidebar === "collapsed");
  }, [me?.preferences.sidebar]);
  const toggle = useCallback(() => {
    setCollapsed((c) => {
      const next = !c;
      const value = next ? "collapsed" : "expanded";
      try { localStorage.setItem(SIDEBAR_KEY, value); } catch { /* storage unavailable */ }
      api<Me>("/auth/me", { method: "PATCH", body: { preferences: { sidebar: value } } })
        .then((m) => qc.setQueryData(["me"], m)).catch(() => {});
      return next;
    });
  }, [qc]);
  return { collapsed, toggle };
}

type NavItem = { to: string; label: string; icon: string; admin?: boolean; badge?: number; end?: boolean };

function NavEntry({ item, collapsed, onNavigate }: { item: NavItem; collapsed: boolean; onNavigate?: () => void }) {
  return (
    <NavLink to={item.to} end={item.end} onClick={onNavigate} title={collapsed ? item.label : undefined}
      className={({ isActive }) =>
        `relative flex items-center gap-3 rounded-lg text-sm transition-colors ${collapsed ? "justify-center h-10 w-10 mx-auto" : "px-3 h-9"} ${
          isActive ? "bg-active text-strong font-medium" : "text-fg2 hover:bg-active/50 hover:text-strong"}`}>
      <Icon name={item.icon} className="w-[18px] h-[18px] shrink-0" />
      {!collapsed && <span className="truncate flex-1">{item.label}</span>}
      {!!item.badge && (
        collapsed
          ? <span className="absolute top-1.5 right-1.5 w-2 h-2 rounded-full bg-crit ring-2 ring-sidebar" />
          : <span className="text-xxs font-semibold tabular-nums px-1.5 rounded-full bg-crit/15 text-crit">{item.badge}</span>
      )}
    </NavLink>
  );
}

function Sidebar({ me, collapsed, onToggle, onNavigate, mobile }: {
  me?: Me; collapsed: boolean; onToggle?: () => void; onNavigate?: () => void; mobile?: boolean;
}) {
  const nav = useNavigate();
  const palette = useCommandPalette();
  const { theme, toggle: toggleTheme } = useTheme();
  const ai = useAI();
  const qc = useQueryClient();
  const { data: ov } = useQuery({ queryKey: ["overview"], queryFn: () => api<Overview>("/overview"), refetchInterval: 30_000 });
  const problems = ov?.unhandled ?? 0; // open, not acknowledged (same as the Home list)
  const isAdmin = me?.role === "admin";

  const main: NavItem[] = [
    { to: "/", label: "Home", icon: "grid", end: true },
    { to: "/dashboards", label: "Dashboards", icon: "palette" },
    { to: "/problems", label: "Problems", icon: "alert", badge: problems },
    { to: "/devices", label: "Devices", icon: "server" },
    { to: "/syslog", label: "Syslog", icon: "list" },
  ];
  const setup: NavItem[] = [
    { to: "/setup/rules", label: "Threshold rules", icon: "sliders" },
    { to: "/setup/notifications", label: "Notifications", icon: "bell", admin: true },
    { to: "/setup/users", label: "Users & groups", icon: "users", admin: true },
    { to: "/setup/plugins?configure=ai", label: "AI assistant", icon: "sparkles", admin: true },
    { to: "/setup/plugins", label: "Plugins & nodes", icon: "puzzle" },
  ];

  const themeToggle = () => {
    const next = theme === "dark" ? "light" : "dark";
    toggleTheme();
    api<Me>("/auth/me", { method: "PATCH", body: { preferences: { theme: next } } }).then((m) => qc.setQueryData(["me"], m)).catch(() => {});
  };
  const tool = "w-9 h-9 rounded-lg flex items-center justify-center text-fg2 hover:bg-active/60 hover:text-strong transition-colors";

  return (
    <div className={`h-full flex flex-col bg-sidebar ${mobile ? "" : "border border-line rounded-2xl"} overflow-hidden`}>
      {/* logo + collapse toggle */}
      <div className={`flex items-center h-16 shrink-0 ${collapsed ? "justify-center" : "px-4 justify-between"}`}>
        {collapsed ? (
          <button onClick={onToggle} title="Expand sidebar" className="group relative w-9 h-9">
            <span className="absolute inset-0 rounded-xl bg-accent text-white font-bold flex items-center justify-center group-hover:opacity-0 transition-opacity">N</span>
            <span className="absolute inset-0 rounded-xl bg-active text-strong flex items-center justify-center opacity-0 group-hover:opacity-100 transition-opacity">
              <Icon name="sidebar" className="w-[18px] h-[18px]" />
            </span>
          </button>
        ) : (
          <>
            <Link to="/" onClick={onNavigate} className="flex items-center gap-2.5 min-w-0">
              <span className="w-8 h-8 rounded-xl bg-accent text-white font-bold flex items-center justify-center shrink-0">N</span>
              <span className="text-lg font-semibold text-strong tracking-tight">NETsync</span>
            </Link>
            {onToggle && (
              <button onClick={onToggle} title="Collapse sidebar" className="p-1.5 rounded-lg text-muted hover:text-strong hover:bg-active/60">
                <Icon name={mobile ? "x" : "sidebar"} className="w-[18px] h-[18px]" />
              </button>
            )}
          </>
        )}
      </div>

      {/* primary action */}
      <div className={collapsed ? "px-0 flex justify-center pb-3" : "px-3 pb-3"}>
        {me?.role !== "viewer" ? (
          <button onClick={() => { nav("/devices?add=1"); onNavigate?.(); }} title={collapsed ? "Add device" : undefined}
            className={`flex items-center gap-3 rounded-lg text-sm font-medium text-strong hover:bg-active/50 transition-colors ${collapsed ? "w-10 h-10 justify-center" : "w-full px-1.5 h-10"}`}>
            <span className="w-7 h-7 rounded-lg bg-accent text-white flex items-center justify-center shrink-0"><Icon name="plus" className="w-4 h-4" strokeWidth={2.25} /></span>
            {!collapsed && "Add device"}
          </button>
        ) : null}
      </div>

      <nav className="flex-1 overflow-y-auto overflow-x-hidden px-3 space-y-1">
        <button onClick={() => { palette.open(); onNavigate?.(); }} title={collapsed ? "Search  (Ctrl K)" : undefined}
          className={`w-full flex items-center gap-3 rounded-lg text-sm text-fg2 hover:bg-active/50 hover:text-strong transition-colors ${collapsed ? "justify-center h-10 w-10 mx-auto" : "px-3 h-9"}`}>
          <Icon name="search" className="w-[18px] h-[18px] shrink-0" />
          {!collapsed && <><span className="flex-1 text-left">Search</span><kbd className="text-xxs text-muted border border-line rounded px-1">Ctrl K</kbd></>}
        </button>
        {main.map((i) => <NavEntry key={i.to} item={i} collapsed={collapsed} onNavigate={onNavigate} />)}

        <div className={`my-4 border-t border-line ${collapsed ? "mx-2" : "mx-3"}`} />

        {setup.filter((i) => !i.admin || isAdmin).map((i) => <NavEntry key={i.to} item={i} collapsed={collapsed} onNavigate={onNavigate} />)}
      </nav>

      {/* bottom tools */}
      <div className={`shrink-0 p-3 flex ${collapsed ? "flex-col items-center gap-1" : "items-center justify-between"}`}>
        {isAdmin && (
          <Link to="/setup/plugins?configure=ai" onClick={onNavigate} className={`${tool} ${ai?.enabled ? "text-accent" : ""}`}
            title={ai?.enabled ? `AI assistant · ${ai.model}` : "AI assistant (off)"}>
            <Icon name="sparkles" className="w-[18px] h-[18px]" />
          </Link>
        )}
        <Link to="/about" onClick={onNavigate} className={tool} title={`About NETsync v${__APP_VERSION__}`}><Icon name="info" className="w-[18px] h-[18px]" /></Link>
        <Link to="/problems" onClick={onNavigate} className={`${tool} relative`} title="Problems">
          <Icon name="bell" className="w-[18px] h-[18px]" />
          {problems > 0 && <span className="absolute top-1.5 right-1.5 w-2 h-2 rounded-full bg-crit" />}
        </Link>
        <button onClick={themeToggle} className={tool} title={theme === "dark" ? "Light mode" : "Dark mode"}>
          <Icon name={theme === "dark" ? "sun" : "moon"} className="w-[18px] h-[18px]" />
        </button>
        <Link to="/profile" onClick={onNavigate} className={tool} title="Profile & settings"><Icon name="user" className="w-[18px] h-[18px]" /></Link>
      </div>
    </div>
  );
}

function StatusPills() {
  const { data } = useQuery({ queryKey: ["overview"], queryFn: () => api<Overview>("/overview"), refetchInterval: 30_000 });
  const down = data?.devices.CRIT ?? 0;
  const crit = data?.services.CRIT ?? 0;
  const warn = data?.services.WARN ?? 0;
  const pill = (n: number, label: string, tone: string) => (
    <Link to="/problems" title={label}
      className={`flex items-center gap-1.5 px-2 h-8 rounded-lg text-xs font-semibold tabular-nums transition-colors ${n ? tone : "text-muted hover:bg-inset"}`}>
      <span className={`w-1.5 h-1.5 rounded-full ${n ? "bg-current" : "bg-faint"}`} />{n}
      <span className="hidden 2xl:inline font-normal">{label}</span>
    </Link>
  );
  return (
    <div className="flex items-center gap-0.5">
      {pill(down, "down", "text-crit bg-crit/10")}
      {pill(crit, "critical", "text-crit bg-crit/10")}
      {pill(warn, "warning", "text-warn bg-warn/15")}
    </div>
  );
}

function Notice({ me }: { me?: Me }) {
  const qc = useQueryClient();
  if (!me || me.preferences.dismissed_notice === NOTICE.id) return null;
  const dismiss = () => {
    qc.setQueryData(["me"], { ...me, preferences: { ...me.preferences, dismissed_notice: NOTICE.id } });
    api<Me>("/auth/me", { method: "PATCH", body: { preferences: { dismissed_notice: NOTICE.id } } }).catch(() => {});
  };
  return (
    <div className="hidden md:flex items-center gap-2.5 h-9 pl-1.5 pr-2 rounded-xl bg-surface border border-line text-sm max-w-full min-w-0">
      <span className="text-xxs font-bold px-1.5 py-0.5 rounded-md bg-accent/15 text-accent">NEW</span>
      <span className="text-strong truncate">{NOTICE.text}</span>
      <Link to={NOTICE.to} className="text-xxs font-semibold px-2 py-1 rounded-md bg-accent text-white whitespace-nowrap hover:bg-accent/90">{NOTICE.cta}</Link>
      <button onClick={dismiss} className="text-muted hover:text-strong p-0.5" aria-label="Dismiss"><Icon name="x" className="w-3.5 h-3.5" /></button>
    </div>
  );
}

function Shell() {
  useLiveEvents();
  const nav = useNavigate();
  const location = useLocation();
  const { setChoice } = useTheme();
  const [drawer, setDrawer] = useState(false);
  const { data: me } = useQuery({ queryKey: ["me"], queryFn: () => api<Me>("/auth/me") });
  const { collapsed, toggle } = useSidebar(me);
  const isAdmin = me?.role === "admin";

  useEffect(() => setDrawer(false), [location.pathname]);

  // Apply the user's saved UI settings (theme follows them across browsers).
  useEffect(() => {
    if (!me) return;
    prefs.set(me.preferences);
    if (me.preferences.theme) setChoice(me.preferences.theme);
  }, [me, setChoice]);

  const logout = () => { auth.set(null); nav("/login"); };
  const headerBtn = "h-8 w-8 rounded-lg flex items-center justify-center text-fg2 hover:bg-inset hover:text-strong border border-line";

  return (
    <div className="h-screen bg-bg flex lg:p-2 lg:gap-2">
      {/* desktop sidebar: floating panel, expanded or icon rail */}
      <aside className={`hidden lg:block shrink-0 transition-[width] duration-200 ease-out ${collapsed ? "w-[68px]" : "w-60"}`}>
        <Sidebar me={me} collapsed={collapsed} onToggle={toggle} />
      </aside>

      {/* mobile drawer */}
      {drawer && (
        <div className="lg:hidden fixed inset-0 z-50">
          <div className="absolute inset-0 bg-black/50" onClick={() => setDrawer(false)} />
          <div className="absolute left-0 top-0 bottom-0 w-72 max-w-[85vw] border-r border-line">
            <Sidebar me={me} collapsed={false} mobile onToggle={() => setDrawer(false)} onNavigate={() => setDrawer(false)} />
          </div>
        </div>
      )}

      {/* main panel: its own scroll container, header sticks to its top */}
      <main id="main-scroll" className="flex-1 min-w-0 h-full overflow-y-auto bg-gap lg:border lg:border-line lg:rounded-2xl">
        <header className="sticky top-0 z-30 h-14 px-3 sm:px-5 flex items-center gap-3 bg-gap/90 backdrop-blur">
          <button className="lg:hidden p-2 -ml-1 rounded-lg text-fg2 hover:bg-inset" onClick={() => setDrawer(true)} aria-label="Open menu">
            <Icon name="menu" className="w-5 h-5" />
          </button>
          <Link to="/" className="lg:hidden flex items-center gap-2">
            <span className="w-7 h-7 rounded-lg bg-accent text-white font-bold flex items-center justify-center text-sm">N</span>
          </Link>
          <div className="flex-1 min-w-0 flex justify-center"><Notice me={me} /></div>
          <div className="flex items-center gap-1.5 sm:gap-2">
            <StatusPills />
            {isAdmin && (
              <Link to="/setup/plugins?configure=ai" className="hidden md:inline text-sm font-semibold text-accent hover:opacity-80 px-1">AI assistant</Link>
            )}
            {me?.role !== "viewer" && (
              <Link to="/devices?add=1" className="hidden sm:inline-flex btn h-8"><Icon name="plus" className="w-3.5 h-3.5" /> Add device</Link>
            )}
            <Link to="/profile" className={headerBtn} title="Settings"><Icon name="gear" className="w-4 h-4" /></Link>
            <button onClick={logout} className={`${headerBtn} hidden sm:flex`} title="Log out"><Icon name="logout" className="w-4 h-4" /></button>
            <Link to="/profile" title={me?.full_name || me?.username} className="ml-0.5">
              <Avatar name={me?.full_name || me?.username} url={me?.avatar_url} size={30} />
            </Link>
          </div>
        </header>
        <Outlet />
      </main>
    </div>
  );
}

export default function Layout() {
  return (
    <CommandPaletteProvider>
      <Shell />
    </CommandPaletteProvider>
  );
}

export function PageHeader({ title, sub, actions }: { title: ReactNode; sub?: ReactNode; actions?: ReactNode }) {
  return (
    <div className="px-4 sm:px-8 pt-3 pb-5 flex flex-col sm:flex-row sm:items-end justify-between gap-3">
      <div className="min-w-0">
        <h1 className="text-2xl font-semibold text-strong tracking-tight">{title}</h1>
        {sub && <div className="text-sm text-muted mt-1">{sub}</div>}
      </div>
      {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
    </div>
  );
}

export function Page({ children }: { children: ReactNode }) {
  return <div className="px-4 sm:px-8 pb-10 space-y-4">{children}</div>;
}
