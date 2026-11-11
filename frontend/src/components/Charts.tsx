/** Small SVG/HTML charts of the UI kit: arc gauge, ring %, donut, horizontal bars, KPI tile, sparkline.
 *  Data in, pixels out (no fetching). Colours come from the --ns-* tokens via CSS, so dark/light just work;
 *  the halo (.svg-glow) only shows in dark mode. Each one also prints its value as text, so colour is never
 *  the only signal. */
import { useId } from "react";

/** CSS colour of a --ns-* token, usable in SVG fill/stroke and style props. */
export const nsVar = (name: string, alpha?: number) => (alpha == null ? `rgb(var(--ns-${name}))` : `rgb(var(--ns-${name}) / ${alpha})`);
export const SERIES_VARS = ["orange", "pink", "purple", "teal", "amber", "red"].map((n) => nsVar(n));
/** OK, WARN, CRIT, UNKNOWN */
export const STATE_VARS = ["green", "amber", "red", "grey"].map((n) => nsVar(n));
export const STATE_WORDS = ["ok", "warning", "critical", "unknown"];

/** "12.3 Mbps" -> ["12.3", "Mbps"]; "42%" -> ["42", "%"]. */
export function splitUnit(text: string): [string, string] {
  const m = text.match(/^(-?[\d.,]+)\s*(.*)$/);
  return m ? [m[1], m[2]] : [text, ""];
}

/** 0 = ok, 1 = warn, 2 = crit. Thresholds work downwards when warn > crit (e.g. uptime %). */
export function thresholdLevel(v: number | null | undefined, warn?: number | null, crit?: number | null): 0 | 1 | 2 | null {
  if (v == null) return null;
  const down = warn != null && crit != null && warn > crit;
  const past = (t?: number | null) => t != null && (down ? v <= t : v >= t);
  return past(crit) ? 2 : past(warn) ? 1 : 0;
}

const polar = (cx: number, cy: number, r: number, deg: number) => [cx + r * Math.cos((deg * Math.PI) / 180), cy + r * Math.sin((deg * Math.PI) / 180)];

/** 270° arc gauge: round-capped track, purple→amber progress (amber/red past the thresholds), dot at the end. */
export function Gauge({ value, min = 0, max = 100, warn, crit, text, label, size = 168 }: {
  value: number | null | undefined; min?: number; max?: number; warn?: number | null; crit?: number | null;
  /** formatted value, e.g. "87%" or "12.4 ms" */
  text: string; label?: string; size?: number;
}) {
  const id = useId().replace(/:/g, "");
  const r = 62, cx = 80, cy = 80, C = 2 * Math.PI * r, arc = 0.75 * C;
  const frac = value == null ? 0 : Math.max(0, Math.min(1, (value - min) / (max - min || 1)));
  const level = thresholdLevel(value, warn, crit);
  const solid = level === 2 ? nsVar("red") : level === 1 ? nsVar("amber") : null;
  const [ex, ey] = polar(cx, cy, r, 135 + frac * 270);
  const [num, unit] = splitUnit(text);
  return (
    <svg viewBox="0 0 160 150" width="100%" style={{ maxWidth: size }} className="block mx-auto" role="img"
      aria-label={`${label ? `${label}: ` : ""}${text}${level ? ` (${level === 2 ? "critical" : "warning"})` : ""}`}>
      <defs>
        <linearGradient id={`g${id}`} gradientUnits="userSpaceOnUse" x1="20" y1="140" x2="140" y2="20">
          <stop offset="0" stopColor={nsVar("purple")} />
          <stop offset="1" stopColor={nsVar("amber")} />
        </linearGradient>
      </defs>
      <circle cx={cx} cy={cy} r={r} fill="none" stroke={nsVar("track")} strokeWidth={12} strokeLinecap="round"
        strokeDasharray={`${arc} ${C}`} transform={`rotate(135 ${cx} ${cy})`} />
      {value != null && frac > 0 && (
        <circle cx={cx} cy={cy} r={r} fill="none" stroke={solid ?? `url(#g${id})`} strokeWidth={12} strokeLinecap="round"
          strokeDasharray={`${frac * arc} ${C}`} transform={`rotate(135 ${cx} ${cy})`} className="svg-glow"
          style={{ color: solid ?? nsVar("purple") }} />
      )}
      {value != null && <circle cx={ex} cy={ey} r={6.5} fill={solid ?? nsVar("amber")} stroke={nsVar("card")} strokeWidth={2}
        className="svg-glow" style={{ color: solid ?? nsVar("amber") }} />}
      <text x={cx} y={cy + 10} textAnchor="middle" fill={nsVar("text")} fontSize={value == null ? 22 : num.length > 4 ? 28 : 34} fontWeight={700}>
        {value == null ? "–" : num}<tspan fontSize={15} fill={nsVar("muted")} dx={2}>{value == null ? "" : unit}</tspan>
      </text>
      {level ? <text x={cx} y={cy + 30} textAnchor="middle" fontSize={11} fontWeight={600} fill={solid!}>{level === 2 ? "critical" : "warning"}</text> : null}
      <text x={cx - 44} y={146} textAnchor="middle" fill={nsVar("muted")} fontSize={11}>{fmtShort(min)}</text>
      <text x={cx + 44} y={146} textAnchor="middle" fill={nsVar("muted")} fontSize={11}>{fmtShort(max)}</text>
    </svg>
  );
}

const fmtShort = (v: number) => (Math.abs(v) >= 1e9 ? `${+(v / 1e9).toFixed(1)}G` : Math.abs(v) >= 1e6 ? `${+(v / 1e6).toFixed(1)}M` : Math.abs(v) >= 1e3 ? `${+(v / 1e3).toFixed(1)}k` : `${+v.toFixed(2)}`);

/** Full ring with the track in the same colour at 20 %, value in the centre, label under it. */
export function Ring({ value, label, color, size = 120 }: { value: number | null | undefined; label: string; color: string; size?: number }) {
  const r = 52, C = 2 * Math.PI * r;
  const v = value == null ? null : Math.max(0, Math.min(100, value));
  return (
    <figure className="flex flex-col items-center gap-1.5 min-w-0" style={{ width: size }}>
      <svg viewBox="0 0 128 128" width="100%" role="img" aria-label={`${label}: ${v == null ? "no data" : `${v.toFixed(0)}%`}`}>
        <circle cx={64} cy={64} r={r} fill="none" stroke={color} strokeOpacity={0.2} strokeWidth={12} />
        {v != null && v > 0 && (
          <circle cx={64} cy={64} r={r} fill="none" stroke={color} strokeWidth={12} strokeLinecap="round"
            strokeDasharray={`${(v / 100) * C} ${C}`} transform="rotate(-90 64 64)" className="svg-glow" style={{ color }} />
        )}
        <text x={64} y={72} textAnchor="middle" fill={nsVar("text")} fontSize={24} fontWeight={700}>{v == null ? "–" : `${v.toFixed(0)}%`}</text>
      </svg>
      <figcaption className="text-xs text-muted truncate max-w-full" title={label}>{label}</figcaption>
    </figure>
  );
}

export interface DonutItem { label: string; value: number; color: string }

/** 2–4 segments, 18 px ring with small gaps, big centre number and a small label, legend below. */
export function Donut({ items, center, caption, size = 150 }: { items: DonutItem[]; center: number | string; caption: string; size?: number }) {
  const r = 62, C = 2 * Math.PI * r;
  const shown = items.filter((i) => i.value > 0);
  const total = shown.reduce((a, i) => a + i.value, 0);
  const gap = shown.length > 1 ? (3 / 360) * C : 0;
  let offset = 0;
  return (
    <div className="flex flex-col items-center gap-3">
      <svg viewBox="0 0 160 160" width="100%" style={{ maxWidth: size }} role="img"
        aria-label={`${center} ${caption}: ${shown.map((i) => `${i.label} ${i.value}`).join(", ") || "none"}`}>
        <circle cx={80} cy={80} r={r} fill="none" stroke={nsVar("track")} strokeWidth={18} />
        {shown.map((i) => {
          const len = Math.max(0, (i.value / total) * C - gap);
          const el = (
            <circle key={i.label} cx={80} cy={80} r={r} fill="none" stroke={i.color} strokeWidth={18}
              strokeDasharray={`${len} ${C}`} strokeDashoffset={-offset} transform="rotate(-90 80 80)" className="svg-glow" style={{ color: i.color }} />
          );
          offset += (i.value / total) * C;
          return el;
        })}
        <text x={80} y={86} textAnchor="middle" fill={nsVar("text")} fontSize={38} fontWeight={700}>{center}</text>
        <text x={80} y={106} textAnchor="middle" fill={nsVar("muted")} fontSize={11}>{caption}</text>
      </svg>
      <div className="flex flex-wrap justify-center gap-x-4 gap-y-1 text-xs text-muted">
        {items.map((i) => (
          <span key={i.label} className="inline-flex items-center gap-1.5">
            <span className="dot glow" style={{ background: i.color, color: i.color }} />{i.label} <span className="text-fg font-semibold tabular-nums">{i.value}</span>
          </span>
        ))}
      </div>
    </div>
  );
}

export interface BarItem { label: string; value: number | null; text: string }

/** Rounded bars with an orange→amber gradient on a dark track: label left, value right. */
export function HBars({ items }: { items: BarItem[] }) {
  const max = Math.max(0, ...items.map((i) => i.value ?? 0)) || 1;
  return (
    <ul className="space-y-2.5">
      {items.map((i) => (
        <li key={i.label} className="grid grid-cols-[minmax(2.5rem,6rem)_minmax(3rem,1fr)_auto] items-center gap-3 text-xs">
          <span className="text-muted truncate" title={i.label}>{i.label}</span>
          <span className="h-3.5 rounded-[5px] bg-ns-track overflow-hidden">
            <span className="block h-full rounded-[5px] bg-gradient-to-r from-ns-orange to-ns-amber svg-glow text-ns-orange"
              style={{ width: `${i.value == null ? 0 : Math.max(2, (i.value / max) * 100)}%` }} />
          </span>
          <span className="text-fg font-semibold tabular-nums text-right min-w-[3.5rem]">{i.text}</span>
        </li>
      ))}
    </ul>
  );
}

/** 2 px line, no axes (KPI tiles). */
export function Spark({ values, color = nsVar("orange"), width = 96, height = 28 }: { values: (number | null)[]; color?: string; width?: number; height?: number }) {
  const vs = values.filter((v): v is number => v != null);
  if (vs.length < 2) return null;
  const min = Math.min(...vs), max = Math.max(...vs), span = max - min || 1;
  const pts = vs.map((v, i) => `${((i / (vs.length - 1)) * width).toFixed(1)},${(height - 3 - ((v - min) / span) * (height - 6)).toFixed(1)}`).join(" ");
  return (
    <svg width={width} height={height} className="overflow-visible shrink-0 svg-glow" style={{ color }} aria-hidden>
      <polyline points={pts} fill="none" stroke={color} strokeWidth={2} strokeLinejoin="round" strokeLinecap="round" />
    </svg>
  );
}

/** Big number with the unit in muted text, a caption, and an optional sparkline top-right. */
export function Kpi({ text, caption, spark, color, tone }: {
  text: string; caption?: string; spark?: (number | null)[]; color?: string;
  /** optional state colour class for the number (text-warn, text-crit…) */
  tone?: string;
}) {
  const [num, unit] = splitUnit(text);
  return (
    // container query units: the 44 px number shrinks in narrow cards instead of being clipped
    <div className="px-5 pt-1 pb-5" style={{ containerType: "inline-size" }}>
      {spark && <div className="flex justify-end -mt-1 mb-1"><Spark values={spark} color={color} width={80} height={26} /></div>}
      <div className={`leading-none font-bold tracking-[-0.02em] tabular-nums whitespace-nowrap ${tone ?? "text-strong"} ${spark ? "" : "mt-2"}`}
        style={{ fontSize: "clamp(28px, 19cqw, 44px)" }}>
        {num}{unit && <span className="font-semibold text-muted ml-1" style={{ fontSize: "0.45em" }}>{unit}</span>}
      </div>
      {caption && <div className="text-xs text-muted mt-3 truncate">{caption}</div>}
    </div>
  );
}
