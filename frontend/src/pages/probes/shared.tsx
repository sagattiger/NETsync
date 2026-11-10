import { useQuery } from "@tanstack/react-query";
import { api, fmtDateTime, Heartbeat, Me, ProbeKind } from "../../api";
import { Icon } from "../../components/Icon";

export const useMe = () => useQuery({ queryKey: ["me"], queryFn: () => api<Me>("/auth/me") }).data;

export interface KindMeta { label: string; icon: string; target: string; placeholder: string; help: string }

/** UI metadata per probe kind. A kind only appears in the form once the backend registers it (GET /probes/kinds). */
export const KINDS: Record<ProbeKind, KindMeta> = {
  icmp: { label: "Ping", icon: "pulse", target: "Host or IP", placeholder: "8.8.8.8 or google.com", help: "ICMP echo: round-trip time, jitter and packet loss." },
  tcp: { label: "TCP port", icon: "network", target: "Host or IP", placeholder: "mail.example.com", help: "Connects to a port; optional TLS handshake and banner check (e.g. SMTP 220)." },
  http: { label: "HTTP(S)", icon: "globe", target: "URL", placeholder: "https://example.com/health", help: "Status code, keyword, response time; https also watches the certificate." },
  json: { label: "JSON API", icon: "terminal", target: "URL", placeholder: "https://api.example.com/status", help: "An HTTP request plus assertions on the JSON response." },
  dns: { label: "DNS", icon: "list", target: "Name to resolve", placeholder: "example.com", help: "Resolves a record and optionally checks the answer." },
  udp: { label: "UDP port", icon: "network", target: "Host or IP", placeholder: "10.0.0.1", help: "Sends a datagram and optionally expects a reply." },
  tls: { label: "TLS certificate", icon: "lock", target: "Host", placeholder: "example.com", help: "Certificate expiry, hostname match and chain validity." },
  push: { label: "Push (heartbeat)", icon: "bell", target: "", placeholder: "", help: "Your job calls a secret URL; DOWN when it stops calling." },
};

export const kindMeta = (k: string): KindMeta => KINDS[k as ProbeKind] ?? { label: k, icon: "pulse", target: "Target", placeholder: "", help: "" };

export function KindIcon({ kind, className = "w-4 h-4" }: { kind: string; className?: string }) {
  return <span title={kindMeta(kind).label} className="inline-flex text-muted"><Icon name={kindMeta(kind).icon} className={className} /></span>;
}

export const fmtMs = (v: number | null | undefined) => (v == null ? "–" : v < 10 ? `${v.toFixed(2)} ms` : v < 1000 ? `${v.toFixed(0)} ms` : `${(v / 1000).toFixed(2)} s`);
export const fmtLoss = (v: number | null | undefined) => (v == null ? "–" : `${v.toFixed(0)}%`);
export const fmtPct = (v: number | null | undefined) => (v == null ? "–" : v >= 99.995 ? "100%" : `${v.toFixed(v >= 99 ? 2 : 1)}%`);
export const uptimeTone = (v: number | null | undefined) => (v == null ? "text-muted" : v >= 99.9 ? "text-ok" : v >= 98 ? "text-warn" : "text-crit");
export const daysTone = (d: number | null | undefined) => (d == null ? "text-muted" : d < 7 ? "text-crit" : d < 21 ? "text-warn" : "text-fg2");

const BEAT_BG = ["bg-ok", "bg-warn", "bg-crit", "bg-unknown"];
const BEAT_LABEL = ["Up", "Up (warning)", "Down", "Pending"];

/** Uptime-Kuma style row of the last beats, newest on the right. */
export function HeartbeatBar({ beats, max = 100, height = "h-7" }: { beats: Heartbeat[]; max?: number; height?: string }) {
  const shown = beats.slice(-max);
  const pad = Math.max(0, max - shown.length);
  return (
    <div className={`flex items-end gap-[2px] ${height}`}>
      {Array.from({ length: pad }, (_, i) => <span key={`p${i}`} className="flex-1 min-w-[2px] h-full rounded-sm bg-chip" />)}
      {shown.map((b) => (
        <span key={b.time} className={`flex-1 min-w-[2px] h-full rounded-sm ${b.maintenance ? "bg-accent/50" : BEAT_BG[b.state] ?? "bg-chip"} hover:opacity-70`}
          title={`${fmtDateTime(b.time)} · ${b.maintenance ? "Maintenance" : BEAT_LABEL[b.state] ?? "?"}${b.response_ms != null ? ` · ${fmtMs(b.response_ms)}` : ""}${b.message ? `\n${b.message}` : ""}`} />
      ))}
    </div>
  );
}

export function StatusPill({ enabled, maintenance, state }: { enabled: boolean; maintenance?: boolean; state: number }) {
  if (!enabled) return <span className="text-xxs font-semibold uppercase px-2 py-0.5 rounded-full bg-chip text-muted">paused</span>;
  if (maintenance) return <span className="text-xxs font-semibold uppercase px-2 py-0.5 rounded-full bg-accent/15 text-accent">maintenance</span>;
  const tone = ["text-ok bg-ok/10", "text-warn bg-warn/15", "text-crit bg-crit/10", "text-unknown bg-unknown/15"][state] ?? "bg-chip text-muted";
  const label = ["UP", "WARN", "DOWN", "PENDING"][state] ?? "?";
  return <span className={`text-xxs font-semibold px-2 py-0.5 rounded-full ${tone}`}>{label}</span>;
}

export function Sparkline({ points, width = 120, height = 28 }: { points: [string, number][]; width?: number; height?: number }) {
  const vs = points.map((p) => p[1]).filter((v) => v != null);
  if (vs.length < 2) return <span className="text-xxs text-muted">–</span>;
  const min = Math.min(...vs), max = Math.max(...vs), span = max - min || 1;
  const d = points.map(([, v], i) => `${(i / (points.length - 1)) * width},${height - 2 - ((v - min) / span) * (height - 4)}`).join(" ");
  return (
    <svg width={width} height={height} className="text-accent overflow-visible" aria-hidden>
      <polyline points={d} fill="none" stroke="currentColor" strokeWidth={1.5} strokeLinejoin="round" strokeLinecap="round" />
    </svg>
  );
}
