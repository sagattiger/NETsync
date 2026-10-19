import { ReactNode, useEffect, useState } from "react";
import { Link, NavLink, Outlet, useLocation, useNavigate } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api, auth, Me, prefs } from "../api";
import { useTheme } from "../theme";
import { Avatar } from "./Avatar";
import { Icon } from "./Icon";

interface Overview { devices: Record<string, number>; services: Record<string, number>; unhandled: number }

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
        for (const key of ["overview", "problems", "services", "devices", "device"]) qc.invalidateQueries({ queryKey: [key] });
      };
      ws.onclose = () => { retry = window.setTimeout(connect, 5000); };
    };
    connect();
    return () => { window.clearTimeout(retry); if (ws) { ws.onclose = null; ws.close(); } };
  }, [qc]);
}

const NAV: { section: string; items: { to: string; label: string; icon: string; admin?: boolean }[] }[] = [
  {
    section: "Monitor",
    items: [
      { to: "/", label: "Overview", icon: "grid" },
      { to: "/dashboards", label: "Dashboards", icon: "palette" },
      { to: "/problems", label: "Problems", icon: "alert" },
      { to: "/devices", label: "Devices", icon: "server" },
      { to: "/syslog", label: "Syslog", icon: "list" },
    ],
  },
  {
    section: "Setup",
    items: [
      { to: "/setup/rules", label: "Threshold rules", icon: "sliders" },
      { to: "/setup/notifications", label: "Notifications", icon: "bell", admin: true },
      { to: "/setup/users", label: "Users & groups", icon: "users", admin: true },
      { to: "/setup/plugins", label: "Plugins & nodes", icon: "puzzle" },
    ],
  },
];

function StatusPills() {
  const { data } = useQuery({ queryKey: ["overview"], queryFn: () => api<Overview>("/overview"), refetchInterval: 30_000 });
  const down = data?.devices.CRIT ?? 0;
  const crit = data?.services.CRIT ?? 0;
  const warn = data?.services.WARN ?? 0;
  const pill = (n: number, label: string, tone: string) => (
    <Link to="/problems" title={label}
      className={`flex items-center gap-1.5 px-2 py-1 rounded-lg text-xs font-semibold tabular-nums transition-colors ${n ? tone : "text-muted hover:bg-inset"}`}>
      <span className={`w-1.5 h-1.5 rounded-full ${n ? "bg-current" : "bg-faint"}`} />{n}
      <span className="hidden xl:inline font-normal">{label}</span>
    </Link>
  );
  return (
    <div className="flex items-center gap-1">
      {pill(down, "down", "text-crit bg-crit/10")}
      {pill(crit, "critical", "text-crit bg-crit/10")}
      {pill(warn, "warning", "text-warn bg-warn/15")}
    </div>
  );
}

function SidebarNav({ me, onNavigate }: { me?: Me; onNavigate?: () => void }) {
  return (
    <nav className="flex-1 overflow-y-auto px-3 py-4 space-y-6">
      {NAV.map((sec) => (
        <div key={sec.section}>
          <div className="px-3 mb-1.5 text-xxs font-medium uppercase tracking-wider text-muted">{sec.section}</div>
          <div className="space-y-0.5">
            {sec.items.filter((i) => !i.admin || me?.role === "admin").map((i) => (
              <NavLink key={i.to} to={i.to} end={i.to === "/"} onClick={onNavigate}
                className={({ isActive }) =>
                  `flex items-center gap-3 px-3 py-2 rounded-lg text-sm transition-colors ${isActive ? "bg-active text-strong font-medium" : "text-fg2 hover:bg-active/50 hover:text-strong"}`}>
                <Icon name={i.icon} className="w-[18px] h-[18px] shrink-0" />
                {i.label}
              </NavLink>
            ))}
          </div>
        </div>
      ))}
    </nav>
  );
}

export default function Layout() {
  useLiveEvents();
  const nav = useNavigate();
  const location = useLocation();
  const { theme, toggle, setChoice } = useTheme();
  const [q, setQ] = useState("");
  const [drawer, setDrawer] = useState(false);
  const { data: me } = useQuery({ queryKey: ["me"], queryFn: () => api<Me>("/auth/me") });

  useEffect(() => setDrawer(false), [location.pathname]);

  // Apply the user's saved UI settings (theme follows them across browsers).
  useEffect(() => {
    if (!me) return;
    prefs.set(me.preferences);
    if (me.preferences.theme) setChoice(me.preferences.theme);
  }, [me, setChoice]);

  const logout = () => { auth.set(null); nav("/login"); };
  const qc = useQueryClient();
  const toggleTheme = () => {
    const next = theme === "dark" ? "light" : "dark";
    toggle();
    api<Me>("/auth/me", { method: "PATCH", body: { preferences: { theme: next } } })
      .then((m) => qc.setQueryData(["me"], m))
      .catch(() => { /* keep the local choice */ });
  };

  return (
    <div className="min-h-full bg-gap">
      {/* fixed top navigation bar */}
      <header className="fixed top-0 inset-x-0 z-40 h-14 bg-sidebar/90 backdrop-blur border-b border-line">
        <div className="h-full px-3 sm:px-4 flex items-center gap-2 sm:gap-4">
          <button className="lg:hidden p-2 -ml-1 rounded-lg text-fg2 hover:bg-inset" onClick={() => setDrawer(true)} aria-label="Open menu">
            <Icon name="menu" className="w-5 h-5" />
          </button>
          <Link to="/" className="flex items-center gap-2.5 shrink-0">
            <span className="w-7 h-7 rounded-lg bg-accent text-white font-bold flex items-center justify-center text-sm">N</span>
            <span className="font-semibold text-strong tracking-tight hidden sm:inline">NETsync</span>
          </Link>

          <form className="hidden md:block flex-1 max-w-md ml-4" onSubmit={(e) => { e.preventDefault(); nav(`/devices?q=${encodeURIComponent(q)}`); }}>
            <label className="relative block">
              <Icon name="search" className="w-4 h-4 absolute left-3 top-1/2 -translate-y-1/2 text-muted" />
              <input className="input w-full pl-9 py-1.5 bg-inset/60" placeholder="Search devices…" value={q} onChange={(e) => setQ(e.target.value)} />
            </label>
          </form>

          <div className="ml-auto flex items-center gap-1 sm:gap-2">
            <StatusPills />
            <span className="w-px h-6 bg-line mx-1 hidden sm:block" />
            <button onClick={toggleTheme} className="p-2 rounded-lg text-fg2 hover:bg-inset hover:text-strong" title={theme === "dark" ? "Light mode" : "Dark mode"} aria-label="Toggle theme">
              <Icon name={theme === "dark" ? "sun" : "moon"} className="w-[18px] h-[18px]" />
            </button>
            <Link to="/profile" title="Your profile" className="flex items-center gap-2 pl-1 pr-1.5 py-1 rounded-lg hover:bg-inset">
              <Avatar name={me?.full_name || me?.username} url={me?.avatar_url} size={28} />
              <div className="leading-tight hidden lg:block">
                <div className="text-xs font-medium text-strong">{me?.full_name || me?.username}</div>
                <div className="text-xxs text-muted capitalize">{me?.role}</div>
              </div>
            </Link>
            <button onClick={logout} className="p-2 rounded-lg text-fg2 hover:bg-inset hover:text-strong" title="Log out" aria-label="Log out">
              <Icon name="logout" className="w-[18px] h-[18px]" />
            </button>
          </div>
        </div>
      </header>

      {/* desktop sidebar: floating panel with a gap around it */}
      <aside className="hidden lg:flex fixed left-0 top-14 bottom-0 w-64 p-2">
        <div className="flex-1 flex flex-col bg-sidebar border border-line rounded-xl overflow-hidden">
          <SidebarNav me={me} />
          <Link to="/about" className="px-5 py-3 border-t border-line text-xxs text-muted hover:text-strong flex items-center justify-between">
            <span>NETsync v{__APP_VERSION__}</span><span>About</span>
          </Link>
        </div>
      </aside>

      {/* mobile drawer */}
      {drawer && (
        <div className="lg:hidden fixed inset-0 z-50">
          <div className="absolute inset-0 bg-black/50" onClick={() => setDrawer(false)} />
          <div className="absolute left-0 top-0 bottom-0 w-72 max-w-[85vw] bg-sidebar border-r border-line flex flex-col">
            <div className="h-14 px-4 flex items-center justify-between border-b border-line">
              <span className="font-semibold text-strong">Menu</span>
              <button className="p-2 -mr-2 text-fg2" onClick={() => setDrawer(false)} aria-label="Close menu"><Icon name="x" className="w-5 h-5" /></button>
            </div>
            <form className="p-3 border-b border-line md:hidden" onSubmit={(e) => { e.preventDefault(); nav(`/devices?q=${encodeURIComponent(q)}`); }}>
              <input className="input w-full" placeholder="Search devices…" value={q} onChange={(e) => setQ(e.target.value)} />
            </form>
            <SidebarNav me={me} onNavigate={() => setDrawer(false)} />
            <Link to="/about" className="px-5 py-2.5 border-t border-line text-xs text-muted hover:text-strong">About NETsync v{__APP_VERSION__}</Link>
            <Link to="/profile" className="px-4 py-3 border-t border-line flex items-center gap-3 hover:bg-active/50">
              <Avatar name={me?.full_name || me?.username} url={me?.avatar_url} size={32} />
              <div className="leading-tight">
                <div className="text-sm font-medium text-strong">{me?.full_name || me?.username}</div>
                <div className="text-xs text-muted">View profile</div>
              </div>
            </Link>
          </div>
        </div>
      )}

      <main className="pt-14 lg:pl-64 min-h-full">
        <div className="lg:py-2 lg:pr-2">
          <div className="bg-bg lg:border lg:border-line lg:rounded-xl min-h-[calc(100vh-4.5rem)]">
            <Outlet />
          </div>
        </div>
      </main>
    </div>
  );
}

export function PageHeader({ title, sub, actions }: { title: ReactNode; sub?: ReactNode; actions?: ReactNode }) {
  return (
    <div className="px-4 sm:px-6 pt-5 pb-4 flex flex-col sm:flex-row sm:items-end justify-between gap-3">
      <div className="min-w-0">
        <h1 className="text-xl font-semibold text-strong tracking-tight">{title}</h1>
        {sub && <div className="text-sm text-muted mt-0.5">{sub}</div>}
      </div>
      {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
    </div>
  );
}

export function Page({ children }: { children: ReactNode }) {
  return <div className="px-4 sm:px-6 pb-8 space-y-4">{children}</div>;
}
