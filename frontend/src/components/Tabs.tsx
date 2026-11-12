/**
 * Browser-like tabs inside the app shell.
 *
 * - Every tab has its own history (back / forward) and renders the page routes against its own location,
 *   so switching tabs never reloads the sidebar or header and inactive tabs keep their state and scroll.
 * - A tab's page is mounted the first time the tab is shown and then kept alive (hidden) until it is closed.
 * - The URL always shows the active tab, so reload, bookmarks and copied links keep working.
 */
import { createContext, MouseEvent as ReactMouseEvent, ReactNode, useCallback, useContext, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { matchPath, Routes, useLocation, useNavigate } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { api, Dashboard, Device, Probe } from "../api";
import { Icon } from "./Icon";

/** visited: the page has been mounted; seen: when it was last shown (idle tabs are unloaded, see KEEP_ALIVE_MS). */
export interface Tab { id: string; history: string[]; idx: number; pinned?: boolean; reload: number; visited: boolean; seen?: number }
interface State { tabs: Tab[]; active: string; closed: Tab[] }
interface OpenOptions { activate?: boolean }

interface TabsApi {
  tabs: Tab[];
  active: string;
  canBack: boolean;
  canForward: boolean;
  closedCount: number;
  openTab: (path?: string, opts?: OpenOptions) => void;
  activate: (id: string) => void;
  close: (id?: string) => void;
  closeOthers: (id: string) => void;
  closeRight: (id: string) => void;
  duplicate: (id: string) => void;
  togglePin: (id: string) => void;
  reload: (id?: string) => void;
  back: () => void;
  forward: () => void;
  reopenClosed: () => void;
  move: (id: string, beforeId: string) => void;
  reset: () => void;
}

const KEY = "netsync_tabs_v1";
const MAX_TABS = 15;
const MAX_HISTORY = 50;
const MAX_CLOSED = 10;
const KEEP_ALIVE_MS = 15 * 60_000; // hidden tabs idle longer than this are unloaded (and their polling stops)

const newId = () => Math.random().toString(36).slice(2, 10);
export const tabPath = (t: Tab) => t.history[t.idx] ?? "/";
const mkTab = (path: string, visited = false): Tab => ({ id: newId(), history: [path], idx: 0, reload: 0, visited });

const Ctx = createContext<TabsApi | null>(null);
export const useTabs = () => useContext(Ctx);

function scroller() {
  return document.getElementById("main-scroll");
}

/** Keep at most MAX_TABS: drop the oldest tab that is neither pinned nor active. */
function cap(tabs: Tab[], active: string): Tab[] {
  const out = [...tabs];
  while (out.length > MAX_TABS) {
    const i = out.findIndex((t) => !t.pinned && t.id !== active);
    if (i < 0) break;
    out.splice(i, 1);
  }
  return out;
}

function load(path: string): State {
  let tabs: Tab[] = [];
  let active = "";
  try {
    const raw = JSON.parse(localStorage.getItem(KEY) || "null");
    if (raw && Array.isArray(raw.tabs)) {
      tabs = raw.tabs
        .filter((t: any) => t && typeof t.id === "string" && Array.isArray(t.history) && t.history.length)
        .map((t: any): Tab => {
          const history = t.history.filter((h: any) => typeof h === "string" && h.startsWith("/") && !h.startsWith("/login")).slice(-MAX_HISTORY);
          const idx = Math.min(Math.max(0, Number.isInteger(t.idx) ? t.idx : history.length - 1), history.length - 1);
          return { id: t.id, history, idx, pinned: !!t.pinned, reload: 0, visited: false };
        })
        .filter((t: Tab) => t.history.length);
      active = raw.active;
    }
  } catch { /* storage unavailable or corrupt: start fresh */ }
  // The URL wins: activate the tab that shows it, or open it in a new tab.
  const match = tabs.find((t) => t.id === active && tabPath(t) === path) ?? tabs.find((t) => tabPath(t) === path);
  if (match) {
    active = match.id;
  } else {
    const t = mkTab(path);
    const at = tabs.findIndex((x) => x.id === active);
    tabs.splice(at < 0 ? tabs.length : at + 1, 0, t);
    active = t.id;
  }
  tabs = cap(tabs, active).map((t) => (t.id === active ? { ...t, visited: true } : t));
  return { tabs, active, closed: [] };
}

export function TabsProvider({ children }: { children: ReactNode }) {
  const loc = useLocation();
  const nav = useNavigate();
  const path = loc.pathname + loc.search;
  const [state, setState] = useState<State>(() => load(path));
  const scrolls = useRef<Record<string, number>>({});
  const stateRef = useRef(state);
  stateRef.current = state;

  // Follow in-page navigation: a new URL becomes the next entry of the active tab's history.
  useEffect(() => {
    setState((s) => {
      const i = s.tabs.findIndex((t) => t.id === s.active);
      if (i < 0) {
        const t = mkTab(path, true);
        return { ...s, tabs: [...s.tabs, t], active: t.id };
      }
      const t = s.tabs[i];
      if (tabPath(t) === path) return s;
      const history = [...t.history.slice(0, t.idx + 1), path].slice(-MAX_HISTORY);
      const tabs = [...s.tabs];
      tabs[i] = { ...t, history, idx: history.length - 1 };
      scrolls.current[t.id] = 0; // a new page starts at the top
      return { ...s, tabs };
    });
  }, [path]);

  // Persist (without runtime-only fields).
  useEffect(() => {
    try {
      localStorage.setItem(KEY, JSON.stringify({
        active: state.active, tabs: state.tabs.map(({ id, history, idx, pinned }) => ({ id, history, idx, pinned })),
      }));
    } catch { /* storage unavailable */ }
  }, [state.tabs, state.active]);

  // Restore the scroll position of the tab that is shown.
  useLayoutEffect(() => {
    const el = scroller();
    if (el) el.scrollTop = scrolls.current[state.active] ?? 0;
  }, [state.active]);

  const saveScroll = () => {
    const el = scroller();
    if (el) scrolls.current[stateRef.current.active] = el.scrollTop;
  };

  /** Apply a state change and point the URL at the (possibly new) active tab without adding browser history. */
  const commit = useCallback((next: State) => {
    const a = next.tabs.find((t) => t.id === next.active);
    const prev = stateRef.current.active;
    if (next.active !== prev) saveScroll();
    const now = Date.now();
    next = { ...next, tabs: next.tabs.map((t) => (t.id === next.active || t.id === prev ? { ...t, visited: t.visited || t.id === next.active, seen: now } : t)) };
    stateRef.current = next;
    setState(next);
    if (a && tabPath(a) !== window.location.pathname + window.location.search) nav(tabPath(a), { replace: true });
  }, [nav]);

  const api_ = useMemo<TabsApi>(() => {
    const get = () => stateRef.current;
    const activeTab = () => get().tabs.find((t) => t.id === get().active);
    const withClosed = (s: State, removed: Tab[]) => ({ ...s, closed: [...removed.filter((t) => !t.pinned), ...s.closed].slice(0, MAX_CLOSED) });

    const removeTabs = (ids: Set<string>) => {
      const s = get();
      const remaining = s.tabs.filter((t) => !ids.has(t.id));
      const removed = s.tabs.filter((t) => ids.has(t.id));
      if (!remaining.length) remaining.push(mkTab("/", true));
      let active = s.active;
      if (ids.has(active)) {
        const i = s.tabs.findIndex((t) => t.id === active);
        const right = s.tabs.slice(i + 1).find((t) => !ids.has(t.id));
        const left = [...s.tabs.slice(0, i)].reverse().find((t) => !ids.has(t.id));
        active = (right ?? left ?? remaining[0]).id;
      }
      for (const t of removed) delete scrolls.current[t.id];
      commit(withClosed({ ...s, tabs: remaining, active }, removed));
    };

    const openTab = (p = "/", { activate = true }: OpenOptions = {}) => {
      const s = get();
      const t = mkTab(p, activate);
      const at = s.tabs.findIndex((x) => x.id === s.active);
      const tabs = [...s.tabs];
      tabs.splice(at < 0 ? tabs.length : at + 1, 0, t);
      const active = activate ? t.id : s.active;
      if (activate) scrolls.current[t.id] = 0;
      commit({ ...s, tabs: cap(tabs, active), active });
    };

    const step = (dir: -1 | 1) => {
      const s = get();
      const t = activeTab();
      if (!t) return;
      const idx = t.idx + dir;
      if (idx < 0 || idx >= t.history.length) return;
      scrolls.current[t.id] = 0;
      commit({ ...s, tabs: s.tabs.map((x) => (x.id === t.id ? { ...x, idx } : x)) });
    };

    return {
      tabs: state.tabs,
      active: state.active,
      canBack: (state.tabs.find((t) => t.id === state.active)?.idx ?? 0) > 0,
      canForward: (() => { const t = state.tabs.find((x) => x.id === state.active); return !!t && t.idx < t.history.length - 1; })(),
      closedCount: state.closed.length,
      openTab,
      activate: (id) => { const s = get(); if (s.active !== id && s.tabs.some((t) => t.id === id)) commit({ ...s, active: id }); },
      close: (id) => removeTabs(new Set([id ?? get().active])),
      closeOthers: (id) => removeTabs(new Set(get().tabs.filter((t) => t.id !== id && !t.pinned).map((t) => t.id))),
      closeRight: (id) => {
        const tabs = get().tabs;
        const i = tabs.findIndex((t) => t.id === id);
        removeTabs(new Set(tabs.slice(i + 1).filter((t) => !t.pinned).map((t) => t.id)));
      },
      duplicate: (id) => {
        const s = get();
        const src = s.tabs.find((t) => t.id === id);
        if (!src) return;
        const t: Tab = { ...src, id: newId(), pinned: false, reload: 0, visited: true };
        const i = s.tabs.findIndex((x) => x.id === id);
        const tabs = [...s.tabs];
        tabs.splice(i + 1, 0, t);
        commit({ ...s, tabs: cap(tabs, t.id), active: t.id });
      },
      togglePin: (id) => {
        const s = get();
        const tabs = s.tabs.map((t) => (t.id === id ? { ...t, pinned: !t.pinned } : t));
        // pinned tabs live on the left, in their order
        commit({ ...s, tabs: [...tabs.filter((t) => t.pinned), ...tabs.filter((t) => !t.pinned)] });
      },
      reload: (id) => {
        const s = get();
        const target = id ?? s.active;
        commit({ ...s, tabs: s.tabs.map((t) => (t.id === target ? { ...t, reload: t.reload + 1 } : t)) });
      },
      back: () => step(-1),
      forward: () => step(1),
      reopenClosed: () => {
        const s = get();
        const [t, ...rest] = s.closed;
        if (!t) return;
        const tab = { ...t, id: newId(), visited: true, reload: 0 };
        commit({ ...s, tabs: cap([...s.tabs, tab], tab.id), active: tab.id, closed: rest });
      },
      move: (id, beforeId) => {
        const s = get();
        if (id === beforeId) return;
        const moving = s.tabs.find((t) => t.id === id);
        const target = s.tabs.find((t) => t.id === beforeId);
        if (!moving || !target || !!moving.pinned !== !!target.pinned) return; // keep pinned and normal tabs apart
        const tabs = s.tabs.filter((t) => t.id !== id);
        const i = tabs.findIndex((t) => t.id === beforeId);
        const after = s.tabs.findIndex((t) => t.id === id) < s.tabs.findIndex((t) => t.id === beforeId);
        tabs.splice(after ? i + 1 : i, 0, moving);
        commit({ ...s, tabs });
      },
      reset: () => { try { localStorage.removeItem(KEY); } catch { /* ignore */ } },
    };
  }, [state, commit]);

  useTabShortcuts(api_);
  useOpenLinksInTabs(api_);

  return <Ctx.Provider value={api_}>{children}</Ctx.Provider>;
}

/** The pages of every opened tab; only the active one is visible. */
export function TabViews({ children }: { children: ReactNode }) {
  const t = useTabs();
  const loc = useLocation();
  if (!t) return null;
  const path = loc.pathname + loc.search;
  return (
    <>
      {t.tabs.filter((tab) => tab.id === t.active || (tab.visited && Date.now() - (tab.seen ?? 0) < KEEP_ALIVE_MS)).map((tab) => (
        <div key={`${tab.id}:${tab.reload}`} hidden={tab.id !== t.active} data-tab={tab.id}>
          <Routes location={tab.id === t.active ? path : tabPath(tab)}>{children}</Routes>
        </div>
      ))}
    </>
  );
}

// --------------------------------------------------------------------------- titles

const STATIC: [string, string, string][] = [
  ["/", "Home", "grid"], ["/problems", "Problems", "alert"], ["/devices", "Devices", "server"], ["/probes", "Probes", "pulse"],
  ["/syslog", "Syslog", "list"], ["/dashboards", "Dashboards", "palette"], ["/setup/rules", "Threshold rules", "sliders"],
  ["/setup/notifications", "Notifications", "bell"], ["/setup/users", "Users & groups", "users"],
  ["/setup/plugins", "Plugins & nodes", "puzzle"], ["/setup/store", "Plugin store", "puzzle"],
  ["/setup/terminal", "Terminal access", "lock"], ["/terminal", "Terminal", "terminal"],
  ["/settings", "Settings", "gear"], ["/settings/charts", "Chart settings", "palette"], ["/setup/housekeeping", "Housekeeping", "list"],
  ["/setup/ai-tools", "AI tools & MCP", "terminal"], ["/setup/tokens", "API tokens", "lock"], ["/profile", "Profile", "user"],
  ["/about", "About", "info"],
];

export interface TabInfo { title: string; icon: string; state?: number }

/** Title and icon for a path; detail pages use the cached device / probe / dashboard name. */
export function useTabInfo(path: string): TabInfo {
  const [pathname, search = ""] = path.split("?");
  const device = matchPath("/devices/:id/*", pathname)?.params.id;
  const probe = matchPath("/probes/:id", pathname)?.params.id;
  const dash = matchPath("/dashboards/:id", pathname)?.params.id;
  const opts = { staleTime: 30_000, retry: false } as const;
  const d = useQuery({ queryKey: ["device", Number(device)], queryFn: () => api<Device>(`/devices/${device}`), enabled: !!device, ...opts }).data;
  const p = useQuery({ queryKey: ["probe", Number(probe)], queryFn: () => api<Probe>(`/probes/${probe}`), enabled: !!probe, ...opts }).data;
  const b = useQuery({ queryKey: ["dashboard", Number(dash)], queryFn: () => api<Dashboard>(`/dashboards/${dash}`), enabled: !!dash, ...opts }).data;
  if (device) return { title: d?.hostname ?? "Device", icon: "server", state: d?.status };
  if (probe) return { title: p?.name ?? "Probe", icon: "pulse", state: p?.enabled ? p.state : undefined };
  if (dash) return { title: b?.name ?? "Dashboard", icon: "palette" };
  if (pathname === "/setup/plugins" && search.includes("configure=ai")) return { title: "AI assistant", icon: "sparkles" };
  const hit = STATIC.find(([p]) => p === pathname);
  return hit ? { title: hit[1], icon: hit[2] } : { title: pathname, icon: "grid" };
}

/** Keeps the browser tab title in step with the active NETsync tab. */
export function DocumentTitle() {
  const t = useTabs();
  const active = t?.tabs.find((x) => x.id === t.active);
  const info = useTabInfo(active ? tabPath(active) : "/");
  useEffect(() => { document.title = `${info.title} · NETsync`; }, [info.title]);
  return null;
}

// --------------------------------------------------------------------------- tab bar

const STATE_DOT = ["", "bg-warn", "bg-crit", ""];

function TabChip({ tab, active, onMenu, dragging, setDragging }: {
  tab: Tab; active: boolean; onMenu: (e: ReactMouseEvent, id: string) => void;
  dragging: string | null; setDragging: (id: string | null) => void;
}) {
  const t = useTabs()!;
  const info = useTabInfo(tabPath(tab));
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => { if (active) ref.current?.scrollIntoView({ block: "nearest", inline: "nearest" }); }, [active]);
  const dot = info.state != null ? STATE_DOT[info.state] : "";
  return (
    <div ref={ref} role="tab" aria-selected={active} title={info.title} draggable
      onClick={() => t.activate(tab.id)}
      onAuxClick={(e) => { if (e.button === 1) { e.preventDefault(); if (!tab.pinned) t.close(tab.id); } }}
      onMouseDown={(e) => { if (e.button === 1) e.preventDefault(); /* no autoscroll */ }}
      onContextMenu={(e) => onMenu(e, tab.id)}
      onDragStart={(e) => { setDragging(tab.id); e.dataTransfer.effectAllowed = "move"; e.dataTransfer.setData("text/plain", tab.id); }}
      onDragEnd={() => setDragging(null)}
      onDragOver={(e) => { if (dragging) e.preventDefault(); }}
      onDrop={(e) => { e.preventDefault(); if (dragging) t.move(dragging, tab.id); setDragging(null); }}
      className={`group relative flex items-center gap-2 h-8 shrink-0 rounded-lg border text-[13px] cursor-pointer select-none transition-colors
        ${tab.pinned ? "w-9 justify-center px-0" : "pl-2.5 pr-1.5 max-w-[12rem] min-w-[6.5rem]"}
        ${active ? "bg-surface border-edge text-strong shadow-sm" : "border-transparent text-fg2 hover:bg-inset hover:text-strong"}
        ${dragging === tab.id ? "opacity-40" : ""}`}>
      <span className="relative shrink-0">
        <Icon name={info.icon} className="w-3.5 h-3.5" />
        {dot && <span className={`absolute -top-1 -right-1 w-2 h-2 rounded-full ring-2 ring-gap ${dot}`} />}
      </span>
      {!tab.pinned && <span className="truncate flex-1">{info.title}</span>}
      {!tab.pinned && (
        <button onClick={(e) => { e.stopPropagation(); t.close(tab.id); }} title="Close tab (Alt+W)"
          className={`shrink-0 w-5 h-5 rounded flex items-center justify-center text-muted hover:text-strong hover:bg-active
            ${active ? "opacity-100" : "opacity-0 group-hover:opacity-100"}`}>
          <Icon name="x" className="w-3 h-3" />
        </button>
      )}
    </div>
  );
}

function TabMenu({ id, x, y, onClose }: { id: string; x: number; y: number; onClose: () => void }) {
  const t = useTabs()!;
  const tab = t.tabs.find((x) => x.id === id);
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const off = (e: MouseEvent) => { if (!ref.current?.contains(e.target as Node)) onClose(); };
    const esc = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("mousedown", off);
    window.addEventListener("keydown", esc);
    window.addEventListener("blur", onClose);
    return () => { window.removeEventListener("mousedown", off); window.removeEventListener("keydown", esc); window.removeEventListener("blur", onClose); };
  }, [onClose]);
  if (!tab) return null;
  const i = t.tabs.indexOf(tab);
  const item = (label: string, fn: () => void, opts: { disabled?: boolean; hint?: string } = {}) => (
    <button disabled={opts.disabled} onClick={() => { fn(); onClose(); }}
      className="w-full flex items-center justify-between gap-6 px-3 py-1.5 text-sm text-fg hover:bg-inset disabled:opacity-40 disabled:hover:bg-transparent text-left">
      <span>{label}</span>{opts.hint && <kbd className="text-xxs text-muted">{opts.hint}</kbd>}
    </button>
  );
  const copy = () => navigator.clipboard?.writeText(window.location.origin + tabPath(tab)).catch(() => {});
  return (
    <div ref={ref} className="fixed z-[60] min-w-[13rem] py-1 rounded-xl border border-edge bg-surface shadow-2xl"
      style={{ left: Math.min(x, window.innerWidth - 230), top: y }}>
      {item("New tab", () => t.openTab("/"), { hint: "Alt+T" })}
      {item("Reload tab", () => t.reload(id), { hint: "Alt+R" })}
      {item("Duplicate tab", () => t.duplicate(id))}
      {item(tab.pinned ? "Unpin tab" : "Pin tab", () => t.togglePin(id))}
      {item("Copy link", copy)}
      <div className="my-1 border-t border-line" />
      {item("Close tab", () => t.close(id), { disabled: tab.pinned, hint: "Alt+W" })}
      {item("Close other tabs", () => t.closeOthers(id), { disabled: t.tabs.length < 2 })}
      {item("Close tabs to the right", () => t.closeRight(id), { disabled: i === t.tabs.length - 1 })}
      {item("Reopen closed tab", () => t.reopenClosed(), { disabled: !t.closedCount, hint: "Alt+Shift+T" })}
    </div>
  );
}

export function TabBar() {
  const t = useTabs();
  const [menu, setMenu] = useState<{ id: string; x: number; y: number } | null>(null);
  const [dragging, setDragging] = useState<string | null>(null);
  const strip = useRef<HTMLDivElement>(null);
  const closeMenu = useCallback(() => setMenu(null), []);
  if (!t) return null;
  const nav = "w-8 h-8 shrink-0 rounded-lg flex items-center justify-center text-fg2 hover:bg-inset hover:text-strong disabled:opacity-30 disabled:hover:bg-transparent";
  return (
    <div className="hidden md:flex items-center gap-1 flex-1 min-w-0" role="tablist">
      <button className={nav} onClick={t.back} disabled={!t.canBack} title="Back (Alt+←)"><Icon name="chevron" className="w-4 h-4 rotate-180" /></button>
      <button className={nav} onClick={t.forward} disabled={!t.canForward} title="Forward (Alt+→)"><Icon name="chevron" className="w-4 h-4" /></button>
      <button className={nav} onClick={() => t.reload()} title="Reload tab (Alt+R)"><Icon name="refresh" className="w-3.5 h-3.5" /></button>
      <div className="w-px h-5 bg-line mx-1 shrink-0" />
      <div ref={strip} className="flex items-center gap-1 min-w-0 overflow-x-auto no-scrollbar"
        onWheel={(e) => { if (strip.current && Math.abs(e.deltaY) > Math.abs(e.deltaX)) strip.current.scrollLeft += e.deltaY; }}
        onDoubleClick={(e) => { if (e.target === strip.current) t.openTab("/"); }}>
        {t.tabs.map((tab) => (
          <TabChip key={tab.id} tab={tab} active={tab.id === t.active} dragging={dragging} setDragging={setDragging}
            onMenu={(e, id) => { e.preventDefault(); setMenu({ id, x: e.clientX, y: e.clientY }); }} />
        ))}
      </div>
      <button className={nav} onClick={() => t.openTab("/")} title="New tab (Alt+T) · Ctrl+click or middle-click a link to open it in a tab">
        <Icon name="plus" className="w-4 h-4" />
      </button>
      {menu && <TabMenu {...menu} onClose={closeMenu} />}
    </div>
  );
}

/** "← Back" for detail pages: the tab's own history when there is one, else the given list page. */
export function BackLink({ to, label }: { to: string; label: string }) {
  const t = useTabs();
  const nav = useNavigate();
  return (
    <button onClick={() => (t?.canBack ? t.back() : nav(to))}
      className="inline-flex items-center gap-1 text-xs font-medium text-muted hover:text-strong mb-1.5 -ml-0.5">
      <Icon name="chevron" className="w-3.5 h-3.5 rotate-180" /> {t?.canBack ? "Back" : label}
    </button>
  );
}

// --------------------------------------------------------------------------- shortcuts and links

function typing(e: KeyboardEvent) {
  const el = e.target as HTMLElement | null;
  return !!el && (el.isContentEditable || ["INPUT", "TEXTAREA", "SELECT"].includes(el.tagName));
}

function useTabShortcuts(t: TabsApi) {
  const ref = useRef(t);
  ref.current = t;
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (!e.altKey || e.ctrlKey || e.metaKey) return;
      const tabs = ref.current;
      const key = e.key.toLowerCase();
      // Alt+arrows also work while typing would be surprising: only outside inputs
      if (typing(e)) return;
      let handled = true;
      if (key === "t" && e.shiftKey) tabs.reopenClosed();
      else if (key === "t") tabs.openTab("/");
      else if (key === "w") tabs.close();
      else if (key === "r") tabs.reload();
      else if (e.key === "ArrowLeft") tabs.back();
      else if (e.key === "ArrowRight") tabs.forward();
      else if (e.key === "[" || e.key === "]") {
        const i = tabs.tabs.findIndex((x) => x.id === tabs.active);
        const n = tabs.tabs.length;
        tabs.activate(tabs.tabs[(i + (e.key === "]" ? 1 : -1) + n) % n].id);
      } else if (/^Digit[1-9]$/.test(e.code)) {
        const d = Number(e.code.slice(5));
        const target = d === 9 ? tabs.tabs[tabs.tabs.length - 1] : tabs.tabs[d - 1];
        if (target) tabs.activate(target.id);
      } else handled = false;
      if (handled) e.preventDefault();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);
}

/** Ctrl/Cmd+click or middle-click on any in-app link opens it in a background tab (Shift: and switch to it). */
function useOpenLinksInTabs(t: TabsApi) {
  const ref = useRef(t);
  ref.current = t;
  useEffect(() => {
    const handler = (e: MouseEvent) => {
      const middle = e.type === "auxclick" && e.button === 1;
      const mod = e.type === "click" && e.button === 0 && (e.ctrlKey || e.metaKey);
      if (!middle && !mod) return;
      const a = (e.target as Element | null)?.closest?.("a[href]") as HTMLAnchorElement | null;
      if (!a || a.target === "_blank" || a.hasAttribute("download") || a.closest("[role=tablist]")) return;
      const url = new URL(a.href, window.location.href);
      if (url.origin !== window.location.origin || url.pathname.startsWith("/api") || url.pathname === "/login") return;
      e.preventDefault();
      e.stopPropagation();
      ref.current.openTab(url.pathname + url.search, { activate: e.shiftKey });
    };
    document.addEventListener("click", handler, true);
    document.addEventListener("auxclick", handler, true);
    return () => { document.removeEventListener("click", handler, true); document.removeEventListener("auxclick", handler, true); };
  }, []);
}
