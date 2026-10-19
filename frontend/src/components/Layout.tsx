import { useEffect, useState } from "react";
import { NavLink, Outlet, useNavigate } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api, auth, Me } from "../api";

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
        qc.invalidateQueries({ queryKey: ["overview"] });
        qc.invalidateQueries({ queryKey: ["problems"] });
        qc.invalidateQueries({ queryKey: ["services"] });
        qc.invalidateQueries({ queryKey: ["devices"] });
      };
      ws.onclose = () => { retry = window.setTimeout(connect, 5000); };
    };
    connect();
    return () => { window.clearTimeout(retry); if (ws) { ws.onclose = null; ws.close(); } };
  }, [qc]);
}

function Tactical() {
  const { data } = useQuery({
    queryKey: ["overview"],
    queryFn: () => api<{ devices: Record<string, number>; services: Record<string, number>; unhandled: number }>("/overview"),
    refetchInterval: 30_000,
  });
  const d = data?.devices ?? {}, s = data?.services ?? {};
  const total = (o: Record<string, number>) => Object.values(o).reduce((a, b) => a + b, 0);
  const cell = (n: number | undefined, cls: string) => (
    <td className={`text-center py-1 font-semibold tabular-nums ${n ? cls : "text-muted"}`}>{n ?? 0}</td>
  );
  return (
    <div className="mx-2 mb-3 rounded border border-line bg-panel">
      <div className="px-2 py-1 text-xxs uppercase tracking-wide text-muted border-b border-line">Overview</div>
      <table className="w-full text-xs">
        <thead>
          <tr className="text-xxs text-muted"><th></th><th>Total</th><th>Problems</th><th>Unhandled</th></tr>
        </thead>
        <tbody>
          <tr>
            <td className="pl-2 text-muted">Devices</td>
            {cell(total(d), "text-gray-200")}
            {cell((d.CRIT ?? 0) + (d.UNKNOWN ?? 0), "text-crit")}
            {cell(d.CRIT, "text-crit")}
          </tr>
          <tr>
            <td className="pl-2 text-muted">Services</td>
            {cell(total(s), "text-gray-200")}
            {cell((s.WARN ?? 0) + (s.CRIT ?? 0) + (s.UNKNOWN ?? 0), "text-warn")}
            {cell(data?.unhandled, "text-crit")}
          </tr>
        </tbody>
      </table>
    </div>
  );
}

const NAV: { section: string; items: [string, string, boolean?][] }[] = [
  { section: "Monitor", items: [["/", "Overview"], ["/problems", "Problems"], ["/devices", "Devices"], ["/syslog", "Syslog"]] },
  {
    section: "Setup",
    items: [["/setup/rules", "Threshold rules"], ["/setup/notifications", "Notifications", true],
      ["/setup/users", "Users & groups", true], ["/setup/plugins", "Plugins"]],
  },
];

export default function Layout() {
  useLiveEvents();
  const nav = useNavigate();
  const [q, setQ] = useState("");
  const { data: me } = useQuery({ queryKey: ["me"], queryFn: () => api<Me>("/auth/me") });

  return (
    <div className="flex h-full">
      <aside className="w-60 shrink-0 bg-[#15191d] border-r border-line flex flex-col">
        <div className="px-4 py-3 flex items-center gap-2 border-b border-line">
          <div className="w-7 h-7 rounded bg-accent text-black font-black flex items-center justify-center">N</div>
          <div className="font-semibold tracking-wide">NET<span className="text-accent">sync</span></div>
        </div>
        <form
          className="p-2"
          onSubmit={(e) => { e.preventDefault(); nav(`/devices?q=${encodeURIComponent(q)}`); }}
        >
          <input className="input w-full text-xs" placeholder="Search devices…" value={q} onChange={(e) => setQ(e.target.value)} />
        </form>
        <Tactical />
        <nav className="flex-1 overflow-y-auto">
          {NAV.map((sec) => (
            <div key={sec.section} className="mb-3">
              <div className="px-4 py-1 text-xxs uppercase tracking-wider text-muted">{sec.section}</div>
              {sec.items
                .filter(([, , admin]) => !admin || me?.role === "admin")
                .map(([to, label]) => (
                  <NavLink
                    key={to}
                    to={to}
                    end={to === "/"}
                    className={({ isActive }) =>
                      `block px-4 py-1.5 text-sm border-l-2 ${isActive ? "border-accent bg-panel text-white" : "border-transparent text-gray-300 hover:bg-panel/60"}`
                    }
                  >
                    {label}
                  </NavLink>
                ))}
            </div>
          ))}
        </nav>
        <div className="p-3 border-t border-line text-xs flex justify-between items-center">
          <span className="text-muted">{me?.username} · {me?.role}</span>
          <button className="text-muted hover:text-white" onClick={() => { auth.set(null); nav("/login"); }}>Logout</button>
        </div>
      </aside>
      <main className="flex-1 overflow-y-auto">
        <Outlet />
      </main>
    </div>
  );
}

export function PageHeader({ title, sub, actions }: { title: React.ReactNode; sub?: React.ReactNode; actions?: React.ReactNode }) {
  return (
    <div className="px-5 py-3 border-b border-line bg-panel/50 flex items-center justify-between">
      <div>
        <h1 className="text-lg font-semibold">{title}</h1>
        {sub && <div className="text-xs text-muted mt-0.5">{sub}</div>}
      </div>
      <div className="flex gap-2">{actions}</div>
    </div>
  );
}
