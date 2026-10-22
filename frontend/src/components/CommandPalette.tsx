import { createContext, ReactNode, useCallback, useContext, useEffect, useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { api, Device, Me } from "../api";
import { useTheme } from "../theme";
import { Icon } from "./Icon";
import { osLabel, VendorLogo } from "./VendorLogo";
import { StateDot } from "./ui";

interface Ctx { open: (query?: string) => void }
const PaletteCtx = createContext<Ctx>({ open: () => {} });
export const useCommandPalette = () => useContext(PaletteCtx);

interface Item { id: string; group: string; label: string; hint?: string; icon?: string; device?: Device; run: () => void }

/** "Ask NETsync or navigate" - Ctrl/Cmd+K anywhere: devices, pages and actions. */
export function CommandPaletteProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<{ open: boolean; query: string }>({ open: false, query: "" });
  const open = useCallback((query = "") => setState({ open: true, query }), []);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        setState((s) => ({ open: !s.open, query: "" }));
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  return (
    <PaletteCtx.Provider value={{ open }}>
      {children}
      {state.open && <Palette initial={state.query} onClose={() => setState({ open: false, query: "" })} />}
    </PaletteCtx.Provider>
  );
}

function Palette({ initial, onClose }: { initial: string; onClose: () => void }) {
  const nav = useNavigate();
  const { theme, toggle } = useTheme();
  const [q, setQ] = useState(initial);
  const [active, setActive] = useState(0);
  const listRef = useRef<HTMLDivElement>(null);
  const { data: devices = [] } = useQuery({ queryKey: ["devices"], queryFn: () => api<Device[]>("/devices") });
  const { data: me } = useQuery({ queryKey: ["me"], queryFn: () => api<Me>("/auth/me") });

  const items = useMemo<Item[]>(() => {
    const go = (path: string) => () => { nav(path); onClose(); };
    const pages: Item[] = [
      ["Overview", "/", "grid"], ["Dashboards", "/dashboards", "palette"], ["Problems", "/problems", "alert"],
      ["Devices", "/devices", "server"], ["Syslog", "/syslog", "list"], ["Threshold rules", "/setup/rules", "sliders"],
      ["Plugins & nodes", "/setup/plugins", "puzzle"], ["Profile & settings", "/profile", "user"], ["About", "/about", "info"],
      ...(me?.role === "admin" ? [["Notifications", "/setup/notifications", "bell"], ["Users & groups", "/setup/users", "users"],
        ["AI assistant settings", "/setup/plugins?configure=ai", "sparkles"]] : []),
    ].map(([label, path, icon]) => ({ id: `p:${path}`, group: "Go to", label, icon, run: go(path) }));
    const actions: Item[] = [
      ...(me?.role !== "viewer" ? [{ id: "a:add", group: "Actions", label: "Add device", icon: "plus", run: go("/devices?add=1") }] : []),
      { id: "a:dash", group: "Actions", label: "New dashboard", icon: "plus", run: go("/dashboards?new=1") },
      { id: "a:theme", group: "Actions", label: theme === "dark" ? "Switch to light mode" : "Switch to dark mode",
        icon: theme === "dark" ? "sun" : "moon", run: () => { toggle(); onClose(); } },
    ];
    const devs: Item[] = devices.map((d) => ({
      id: `d:${d.id}`, group: "Devices", label: d.hostname, device: d,
      hint: [d.ip ?? d.ip_addresses?.[0], osLabel(d.os, d.version)].filter(Boolean).join(" · "),
      run: go(`/devices/${d.id}`),
    }));
    const needle = q.trim().toLowerCase();
    const match = (i: Item) => !needle || `${i.label} ${i.hint ?? ""} ${i.device?.sys_name ?? ""}`.toLowerCase().includes(needle);
    return [...devs.filter(match).slice(0, needle ? 12 : 6), ...pages.filter(match), ...actions.filter(match)];
  }, [q, devices, me, theme, nav, onClose, toggle]);

  useEffect(() => setActive(0), [q]);
  useEffect(() => {
    listRef.current?.querySelector(`[data-index="${active}"]`)?.scrollIntoView({ block: "nearest" });
  }, [active]);

  const onKey = (e: React.KeyboardEvent) => {
    if (e.key === "ArrowDown") { e.preventDefault(); setActive((a) => Math.min(a + 1, items.length - 1)); }
    else if (e.key === "ArrowUp") { e.preventDefault(); setActive((a) => Math.max(a - 1, 0)); }
    else if (e.key === "Enter") { e.preventDefault(); items[active]?.run(); }
    else if (e.key === "Escape") onClose();
  };

  let lastGroup = "";
  return (
    <div className="fixed inset-0 z-[70] bg-black/50 backdrop-blur-[2px] flex items-start justify-center pt-[12vh] px-4" onClick={onClose}>
      <div className="w-full max-w-xl bg-surface border border-edge rounded-2xl shadow-2xl overflow-hidden" onClick={(e) => e.stopPropagation()}>
        <label className="flex items-center gap-3 px-4 border-b border-line">
          <Icon name="search" className="w-5 h-5 text-muted" />
          <input autoFocus value={q} onChange={(e) => setQ(e.target.value)} onKeyDown={onKey}
            placeholder="Search devices or jump to a page…" className="flex-1 bg-transparent py-4 text-base text-strong outline-none placeholder:text-muted" />
          <kbd className="text-xxs text-muted border border-line rounded px-1.5 py-0.5">Esc</kbd>
        </label>
        <div ref={listRef} className="max-h-[55vh] overflow-y-auto py-2">
          {!items.length && <div className="px-4 py-8 text-center text-sm text-muted">Nothing matches “{q}”</div>}
          {items.map((it, i) => {
            const header = it.group !== lastGroup ? (lastGroup = it.group) : null;
            return (
              <div key={it.id}>
                {header && <div className="px-4 pt-2.5 pb-1 text-xxs font-medium uppercase tracking-wider text-muted">{header}</div>}
                <button data-index={i} onMouseEnter={() => setActive(i)} onClick={it.run}
                  className={`w-full flex items-center gap-3 px-4 py-2 text-left ${i === active ? "bg-active" : ""}`}>
                  {it.device ? <VendorLogo device={it.device} size={26} /> : (
                    <span className="w-[26px] h-[26px] rounded-lg bg-inset border border-line flex items-center justify-center text-fg2">
                      <Icon name={it.icon ?? "arrow"} className="w-3.5 h-3.5" />
                    </span>
                  )}
                  <span className="flex-1 min-w-0">
                    <span className="block text-sm text-strong truncate">{it.label}</span>
                    {it.hint && <span className="block text-xs text-muted truncate">{it.hint}</span>}
                  </span>
                  {it.device && <StateDot state={it.device.status} />}
                  {i === active && <Icon name="arrow" className="w-3.5 h-3.5 text-muted" />}
                </button>
              </div>
            );
          })}
        </div>
        <div className="px-4 py-2 border-t border-line text-xxs text-muted flex gap-4">
          <span><kbd className="font-mono">↑↓</kbd> navigate</span><span><kbd className="font-mono">Enter</kbd> open</span>
          <span className="ml-auto"><kbd className="font-mono">Ctrl K</kbd> anywhere</span>
        </div>
      </div>
    </div>
  );
}
