export const STATES = ["OK", "WARN", "CRIT", "UNKNOWN"] as const;
export type StateName = (typeof STATES)[number];

export interface Group { id: number; name: string; description?: string | null }

export interface Device {
  id: number; hostname: string; ip: string | null; node_id: number | null;
  snmp_version: string; snmp_port: number;
  sys_name: string | null; sys_descr: string | null; sys_object_id: string | null;
  sys_location: string | null; sys_contact: string | null; uptime: number | null;
  vendor: string | null; os: string | null; hardware: string | null; version: string | null;
  serial: string | null; device_type: string | null;
  status: number; status_reason: string | null; disabled: boolean;
  last_polled: string | null; last_discovered: string | null; poll_duration: number | null;
  groups: Group[];
  services_ok?: number; services_warn?: number; services_crit?: number; services_unknown?: number; ports?: number;
}

export interface Component {
  id: number; kind: string; index: string; module: string; name: string; descr: string | null;
  attrs: Record<string, any>; values: Record<string, any>; enabled: boolean;
}

export interface Service {
  id: number; device_id: number; component_id: number | null; check: string; name: string;
  state: number; output: string | null; perf: Record<string, number>;
  last_check: string | null; last_change: string | null;
  acknowledged: boolean; ack_comment: string | null; ack_by: string | null; hostname?: string;
}

export interface SyslogMsg {
  id: number; time: string; device_id: number | null; source_ip: string; facility: number;
  severity: number; hostname: string | null; program: string | null; message: string;
}

export interface Me { id: number; username: string; email: string | null; role: string; groups: string[] }

export interface PluginInfo {
  name: string; version: string; description: string; builtin: boolean;
  modules: string[]; channels: string[]; services: string[];
  ui_tabs: { id: string; label: string; view: string; metrics: string[]; url?: string | null }[];
}

export type Series = Record<string, [string, number, number, number][]>;

const TOKEN_KEY = "netsync_token";

export const auth = {
  get token(): string | null {
    try { return localStorage.getItem(TOKEN_KEY); } catch { return null; }
  },
  set(token: string | null) {
    try { token ? localStorage.setItem(TOKEN_KEY, token) : localStorage.removeItem(TOKEN_KEY); } catch { /* ignore */ }
  },
};

export class ApiError extends Error {
  constructor(public status: number, message: string) { super(message); }
}

export async function api<T = any>(path: string, opts: { method?: string; body?: unknown } = {}): Promise<T> {
  const headers: Record<string, string> = {};
  if (auth.token) headers.Authorization = `Bearer ${auth.token}`;
  if (opts.body !== undefined) headers["Content-Type"] = "application/json";
  const res = await fetch(`/api${path}`, {
    method: opts.method ?? (opts.body !== undefined ? "POST" : "GET"),
    headers,
    body: opts.body !== undefined ? JSON.stringify(opts.body) : undefined,
  });
  if (res.status === 401 && path !== "/auth/login") {
    auth.set(null);
    window.location.href = "/login";
  }
  if (!res.ok) {
    let detail = res.statusText;
    try { detail = (await res.json()).detail ?? detail; } catch { /* not json */ }
    throw new ApiError(res.status, typeof detail === "string" ? detail : JSON.stringify(detail));
  }
  return res.json();
}

export function fmtAgo(iso: string | null | undefined): string {
  if (!iso) return "never";
  const s = Math.max(0, (Date.now() - new Date(iso).getTime()) / 1000);
  if (s < 60) return `${Math.round(s)}s ago`;
  if (s < 3600) return `${Math.round(s / 60)}m ago`;
  if (s < 86400) return `${Math.round(s / 3600)}h ago`;
  return `${Math.round(s / 86400)}d ago`;
}

export function fmtUptime(sec: number | null): string {
  if (sec == null) return "-";
  const d = Math.floor(sec / 86400), h = Math.floor((sec % 86400) / 3600), m = Math.floor((sec % 3600) / 60);
  return `${d}d ${h}h ${m}m`;
}

export function fmtBps(bps: number | null | undefined): string {
  if (bps == null) return "-";
  const u = ["bps", "Kbps", "Mbps", "Gbps", "Tbps"];
  let i = 0;
  while (bps >= 1000 && i < u.length - 1) { bps /= 1000; i++; }
  return `${bps.toFixed(1)} ${u[i]}`;
}

export function fmtBytes(n: number | null | undefined): string {
  if (n == null) return "-";
  const u = ["B", "KB", "MB", "GB", "TB", "PB"];
  let i = 0;
  while (n >= 1024 && i < u.length - 1) { n /= 1024; i++; }
  return `${n.toFixed(1)} ${u[i]}`;
}
