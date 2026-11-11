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
export const daysTone = (d: number | null | undefined) => (d == null ? "text-muted" : d < 7 ? "text-crit" : d < 14 ? "text-warn" : "text-fg2");

const BEAT_BG = ["bg-ok/90", "bg-warn", "bg-crit", "bg-ns-grey/60"];
const BEAT_LABEL = ["Up", "Up (warning)", "Down", "Pending"];

/** Uptime-Kuma style row of the last beats, newest on the right: rounded pills (green / amber / red / grey). */
export function HeartbeatBar({ beats, max = 100, height = "h-7" }: { beats: Heartbeat[]; max?: number; height?: string }) {
  const shown = beats.slice(-max);
  const pad = Math.max(0, max - shown.length);
  return (
    <div className={`flex items-end ${height}`} role="img"
      aria-label={`Last ${shown.length} checks: ${shown.filter((b) => b.state === 2).length} down, ${shown.filter((b) => b.state === 1).length} warning`}>
      {/* each beat gets an equal slot; the pill is at most 5 px wide and never overflows narrow cards */}
      {Array.from({ length: pad }, (_, i) => <span key={`p${i}`} className="flex-1 min-w-0 h-full flex justify-center"><span className="w-[70%] max-w-[5px] h-full rounded-full bg-chip" /></span>)}
      {shown.map((b) => (
        <span key={b.time} className="flex-1 min-w-0 h-full flex justify-center group"
          title={`${fmtDateTime(b.time)} · ${b.maintenance ? "Maintenance" : BEAT_LABEL[b.state] ?? "?"}${b.response_ms != null ? ` · ${fmtMs(b.response_ms)}` : ""}${b.message ? `
${b.message}` : ""}`}>
          <span className={`w-[70%] max-w-[5px] h-full rounded-full ${b.maintenance ? "bg-accent/50" : BEAT_BG[b.state] ?? "bg-chip"} group-hover:opacity-70`} />
        </span>
      ))}
    </div>
  );
}

export function StatusPill({ enabled, maintenance, state }: { enabled: boolean; maintenance?: boolean; state: number }) {
  const cls = "pill text-xxs px-2 py-0.5";
  if (!enabled) return <span className={`${cls} uppercase bg-chip text-muted border-line`}>paused</span>;
  if (maintenance) return <span className={`${cls} uppercase bg-accent/[.12] border-accent/40 text-accent`}>maintenance</span>;
  const tone = ["pill-ok", "pill-warn", "pill-crit", "pill-unknown"][state] ?? "bg-chip text-muted border-line";
  const label = ["UP", "WARN", "DOWN", "PENDING"][state] ?? "?";
  return <span className={`${cls} ${tone}`}><span aria-hidden className="dot glow !w-1.5 !h-1.5 bg-current" />{label}</span>;
}

export function Sparkline({ points, width = 120, height = 28 }: { points: [string, number][]; width?: number; height?: number }) {
  const vs = points.map((p) => p[1]).filter((v) => v != null);
  if (vs.length < 2) return <span className="text-xxs text-muted">–</span>;
  const min = Math.min(...vs), max = Math.max(...vs), span = max - min || 1;
  const d = points.map(([, v], i) => `${(i / (points.length - 1)) * width},${height - 2 - ((v - min) / span) * (height - 4)}`).join(" ");
  return (
    <svg width={width} height={height} className="text-accent overflow-visible glow-soft" aria-hidden>
      <polyline points={d} fill="none" stroke="currentColor" strokeWidth={2} strokeLinejoin="round" strokeLinecap="round" />
    </svg>
  );
}
