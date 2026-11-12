export const STATES = ["OK", "WARN", "CRIT", "UNKNOWN"] as const;
export type StateName = (typeof STATES)[number];

export interface Group { id: number; name: string; description?: string | null }

export interface Device {
  id: number; hostname: string; ip: string | null; node_id: number | null;
  snmp_version: string; snmp_port: number;
  sys_name: string | null; sys_descr: string | null; sys_object_id: string | null;
  sys_location: string | null; sys_contact: string | null; uptime: number | null;
  ip_addresses?: string[]; vendor: string | null; os: string | null; hardware: string | null; version: string | null;
  serial: string | null; device_type: string | null; virtualization: string | null; kernel: string | null;
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
  // problem list only
  resolved?: boolean; problem_state?: number; problem_since?: string | null; resolved_at?: string | null;
  duration?: number | null; event?: DeviceEvent | null; ai_status?: AIJobStatus | null;
}

export interface SyslogMsg {
  id: number; time: string; device_id: number | null; source_ip: string; facility: number;
  severity: number; hostname: string | null; program: string | null; message: string;
  ai?: { job_id: number; status: AIJobStatus } | null;
}

export interface Preferences {
  theme?: "dark" | "light" | "system";
  default_range?: string;
  time_format?: "24h" | "12h";
  refresh_interval?: string;
  landing_page?: string;
  table_density?: "comfortable" | "compact";
  sidebar?: "expanded" | "collapsed";
  dismissed_notice?: string;
  chart?: Partial<import("./lib/chartTheme").ChartPrefs>;
}

export interface Me {
  id: number; username: string; email: string | null; full_name: string | null; phone: string | null;
  job_title: string | null; timezone: string | null; role: string; groups: string[];
  preferences: Preferences; avatar_url: string | null;
  created_at: string; last_login: string | null; password_changed_at: string | null;
}

export interface EventComment {
  id: number; device_id: number; service_id: number; event_time: string; body: string; pinned: boolean;
  author: string; author_id: number | null; author_avatar: string | null; created_at: string; updated_at: string | null;
  ai?: boolean;
}

export interface DeviceEvent {
  time: string; service_id: number; service: string | null; old_state: number; new_state: number;
  output: string | null; comments: EventComment[]; pinned: boolean;
}

export interface PinnedEvent extends DeviceEvent { device_id: number; hostname: string; pinned_at: string }

export type WidgetType = "graph" | "device" | "problems" | "services" | "uptime" | "kpi" | "gauge" | "rings" | "donut" | "bars";
/** One ring of a rings widget (a device/component or probe metric, shown as 0–100 %). */
export interface RingItem {
  label?: string | null; device_id?: number | null; component_id?: number | null; probe_id?: number | null;
  preset: string; metric?: string | null; color?: string | null;
}
export interface Widget {
  id: string; type: WidgetType; title: string; size: "s" | "m" | "l";
  device_id: number | null; component_id: number | null; preset: string | null;
  public_title?: string | null;
  // optional appearance (omitted = today's look)
  probe_id?: number | null;
  colors?: string[] | null;
  labels?: Record<string, string> | null;
  logo?: string | null; // "di:<slug>" (Dashboard Icons) or https://
  cols?: WidgetCols | null;
  height?: "compact" | "normal" | "tall" | null;
  compact?: boolean | null;
  // UI kit widgets
  style?: "area" | "line" | "spike" | "range" | null; // graph
  metric?: string | null; // kpi/gauge/bars: series key of the preset (default: the first)
  stat?: "last" | "uptime" | null; // kpi
  window?: "24h" | "7d" | "30d" | null; // kpi uptime window
  caption?: string | null; // kpi
  min?: number | null; max?: number | null; warn?: number | null; crit?: number | null; // gauge
  items?: RingItem[] | null; // rings
  count?: "services" | "problems" | null; // donut
  limit?: number | null; // bars: top N
  probe_ids?: number[] | null; // bars of probes
}
export type WidgetCols = 3 | 4 | 6 | 8 | 12;
export const SIZE_COLS: Record<Widget["size"], WidgetCols> = { s: 4, m: 6, l: 12 };
export const widgetCols = (w: Widget): WidgetCols => w.cols ?? SIZE_COLS[w.size] ?? 6;
const DI_CDN = "https://cdn.jsdelivr.net/gh/homarr-labs/dashboard-icons";
export function logoSrc(logo: string | null | undefined): string | null {
  if (!logo) return null;
  if (logo.startsWith("di:")) {
    const [slug, fmt = "svg"] = logo.slice(3).split(".");
    return `${DI_CDN}/${fmt}/${slug}.${fmt}`;
  }
  return logo.startsWith("https://") ? logo : null;
}

export interface ProbeService { id: number; name: string; state: number; output: string | null; last_change: string | null; acknowledged: boolean }
export type ProbeKind = "icmp" | "tcp" | "udp" | "dns" | "http" | "json" | "tls" | "push";
export type Windows = { "24h": number | null; "7d": number | null; "30d": number | null; "1y": number | null };
export interface CertInfo {
  subject_cn: string | null; sans: string[]; issuer: string | null; issuer_org: string | null;
  not_before: string; not_after: string; days_left: number; hostname_match: boolean | null;
  chain_valid: boolean | null; tls_version: string | null; key_type: string; key_bits: number | null;
  serial: string; self_signed: boolean;
}
export interface Probe {
  id: number; name: string; kind: ProbeKind; kind_label: string; target: string; port: number | null;
  interval_s: number; timeout_s: number; retries: number; retry_interval_s: number | null; upside_down: boolean;
  resend_every: number; count: number; enabled: boolean; tags: string[]; description: string | null;
  config: Record<string, any>; secrets: Record<string, any>;
  created_at: string; last_run: string | null; next_run: string | null; last_error: string | null;
  last_state: number | null; last_message: string | null; last_response_ms: number | null; fail_count: number;
  device_id: number; group_ids: number[]; state: number; rtt_ms: number | null; loss_pct: number | null;
  cert: CertInfo | null; cert_days_left: number | null; uptime: Partial<Windows>; avg_ms: Partial<Windows>;
  maintenance: boolean; has_push_token: boolean;
  services: ProbeService[]; spark: [string, number][];
}
export interface Heartbeat { time: string; state: number; response_ms: number | null; message: string | null; maintenance: boolean }
export interface ProbeTestResult {
  up: boolean; effective_up: boolean; response_ms: number | null; state: string; message: string;
  metrics: Record<string, number>; cert: CertInfo | null; details?: Record<string, any>;
  checks: { name: string; state: string | null; value: number | null; output: string }[];
}
export interface Dashboard {
  id: number; name: string; description: string | null; owner: string; owner_id: number | null;
  shared: boolean; public: boolean; public_name: string | null;
  widgets: Widget[]; created_at: string; updated_at: string; can_edit: boolean;
}

export function fmtDuration(sec: number | null | undefined): string {
  if (sec == null) return "-";
  const d = Math.floor(sec / 86400), h = Math.floor((sec % 86400) / 3600), m = Math.floor((sec % 3600) / 60);
  return d ? `${d}d ${h}h` : h ? `${h}h ${m}m` : `${m}m`;
}

// Current user's UI preferences, set once /auth/me has loaded (see Layout).
let currentPrefs: Preferences = {};
export const prefs = {
  get: () => currentPrefs,
  set: (p: Preferences) => {
    currentPrefs = p;
    document.documentElement.setAttribute("data-density", p.table_density ?? "comfortable");
  },
  refreshMs: (fallback: number) => (currentPrefs.refresh_interval ? Number(currentPrefs.refresh_interval) * 1000 : fallback),
};

export function fmtDateTime(iso: string | null | undefined): string {
  if (!iso) return "-";
  return new Date(iso).toLocaleString(undefined, {
    year: "numeric", month: "short", day: "numeric", hour: "2-digit", minute: "2-digit",
    hour12: currentPrefs.time_format === "12h",
  });
}

export interface PluginInfo {
  name: string; label: string; version: string; description: string; builtin: boolean; enabled: boolean; configurable: boolean;
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

export type AIJobStatus = "pending" | "running" | "done" | "error";
export interface AIJob {
  id: number; kind: "event" | "syslog"; status: AIJobStatus; auto: boolean; model: string | null;
  result: string | null; error: string | null; duration: number | null; device_id: number | null;
  service_id: number | null; event_time: string | null; syslog_id: number | null;
  requested_by: string | null; created_at: string; finished_at: string | null;
}
export type AskTarget =
  | { kind: "service"; service_id: number }
  | { kind: "event"; service_id: number; event_time: string }
  | { kind: "syslog"; syslog_id: number; syslog_time: string };

export interface SettingField {
  key: string; label: string; type: "text" | "secret" | "number" | "bool" | "select" | "textarea" | "model";
  help?: string; section?: string; options?: [string, string][]; min?: number; max?: number; float?: boolean;
}
export interface PluginSettings {
  name: string; label: string; enabled: boolean; fields: SettingField[];
  actions: { id: string; label: string; method: string; path: string }[]; config: Record<string, any>;
}

/** "45s", "12m 5s", "3h 12m", "2d 4h" */
export function fmtElapsed(sec: number | null | undefined): string {
  if (sec == null) return "-";
  const s = Math.max(0, Math.floor(sec));
  if (s < 60) return `${s}s`;
  if (s < 3600) return `${Math.floor(s / 60)}m ${s % 60}s`;
  if (s < 86400) return `${Math.floor(s / 3600)}h ${Math.floor((s % 3600) / 60)}m`;
  return `${Math.floor(s / 86400)}d ${Math.floor((s % 86400) / 3600)}h`;
}
