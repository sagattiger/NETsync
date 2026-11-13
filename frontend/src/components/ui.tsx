import { ReactNode, useEffect } from "react";
import { STATES } from "../api";
import { Icon } from "./Icon";
import { Art, type ArtName } from "./Brand";

const STATE_PILL = ["pill-ok", "pill-warn", "pill-crit", "pill-unknown"];
const STATE_TEXT = ["text-ok", "text-warn", "text-crit", "text-unknown"];
const STATE_BG = ["bg-ok", "bg-warn", "bg-crit", "bg-unknown"];

/** Rounded pill: 12 % tint, 40 % border, dot + label (the label keeps colour from being the only signal). */
export function StateBadge({ state, small, label }: { state: number; small?: boolean; label?: string }) {
  return (
    <span className={`pill ${STATE_PILL[state] ?? "text-muted bg-inset border-line"} ${small ? "text-xxs px-2 py-0.5" : "text-xs px-2.5 py-1"}`}>
      <StateDot state={state} className={small ? "!w-1.5 !h-1.5" : ""} />
      {label ?? STATES[state] ?? "PEND"}
    </span>
  );
}

export const stateText = (state: number) => STATE_TEXT[state] ?? "text-muted";
export const stateBg = (state: number) => STATE_BG[state] ?? "bg-muted";
export const statePill = (state: number) => STATE_PILL[state] ?? "text-muted bg-inset border-line";

export function StateDot({ state, className = "" }: { state: number; className?: string }) {
  return <span aria-hidden className={`dot glow ${stateBg(state)} ${stateText(state)} ${className}`} />;
}

export function Card({ title, actions, children, className = "", flush = true }: { title?: ReactNode; actions?: ReactNode; children: ReactNode; className?: string; flush?: boolean }) {
  return (
    <section className={`card overflow-hidden ${className}`}>
      {title && (
        <header className="card-title flex items-center justify-between gap-3">
          <span className="truncate">{title}</span>
          {actions && <div className="flex items-center gap-2 shrink-0">{actions}</div>}
        </header>
      )}
      <div className={flush ? "overflow-x-auto" : "p-4"}>{children}</div>
    </section>
  );
}

/** Widget card header: state dot (or logo), 13 px uppercase title, optional "⋯" menu / controls on the right. */
export function WidgetHead({ lead, title, right }: { lead?: ReactNode; title: ReactNode; right?: ReactNode }) {
  return (
    <header className="px-4 pt-3 pb-2 flex items-center gap-2.5 min-h-[2.75rem]">
      {lead}
      <h3 className="card-caps truncate flex-1">{title}</h3>
      {right}
    </header>
  );
}

export function Tile({ label, value, tone, hint }: { label: string; value: ReactNode; tone?: number; hint?: ReactNode }) {
  return (
    <div className="card px-4 py-3.5">
      <div className="text-xxs font-semibold uppercase tracking-[0.08em] text-muted">{label}</div>
      <div className={`text-2xl font-semibold mt-1 tabular-nums ${tone !== undefined ? stateText(tone) : "text-strong"}`}>{value}</div>
      {hint && <div className="text-xxs text-muted mt-0.5">{hint}</div>}
    </div>
  );
}

export function Empty({ children, art }: { children: ReactNode; art?: ArtName }) {
  return (
    <div className="px-4 py-10 text-center text-muted text-sm">
      {art && <Art name={art} className="block mx-auto mb-3 w-full max-w-[16rem] h-auto" />}
      {children}
    </div>
  );
}

export function Bar({ pct, wide = false, warn = 80, crit = 90 }: { pct: number | null | undefined; wide?: boolean; warn?: number; crit?: number }) {
  if (wide) return <LevelBar value={pct ?? null} max={100} warn={warn} crit={crit} fmt={(v) => `${v.toFixed(1)}%`} />;
  const p = Math.max(0, Math.min(100, pct ?? 0));
  const color = p >= crit ? "bg-crit" : p >= warn ? "bg-warn" : "bg-gradient-to-r from-ns-orange to-ns-amber";
  return (
    <div className="flex items-center gap-2.5 min-w-[9rem]">
      <div className="h-1.5 flex-1 max-w-[8rem] bg-chip rounded-full overflow-hidden">
        <div className={`h-full rounded-full ${color}`} style={{ width: `${p}%` }} />
      </div>
      <span className="text-xs tabular-nums text-fg2 w-12">{pct == null ? "-" : `${p.toFixed(1)}%`}</span>
    </div>
  );
}

export function Modal({ title, onClose, children, wide }: { title: string; onClose: () => void; children: ReactNode; wide?: boolean }) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);
  return (
    <div className="fixed inset-0 z-50 bg-black/50 backdrop-blur-[2px] flex items-end sm:items-start justify-center sm:pt-20 sm:px-4" onClick={onClose}>
      <div className={`bg-surface border border-edge w-full ${wide ? "sm:max-w-2xl" : "sm:max-w-lg"} rounded-t-2xl sm:rounded-2xl shadow-2xl max-h-[90vh] overflow-y-auto`} onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center justify-between px-5 py-4 border-b border-line">
          <h2 className="font-semibold text-strong">{title}</h2>
          <button onClick={onClose} className="text-muted hover:text-strong p-1 -m-1" aria-label="Close"><Icon name="x" /></button>
        </div>
        <div className="p-5">{children}</div>
      </div>
    </div>
  );
}

export function Segmented<T extends string | number>({ value, options, onChange }: { value: T; options: [T, string][]; onChange: (v: T) => void }) {
  return (
    <div className="seg">
      {options.map(([v, label]) => (
        <button key={String(v)} data-active={v === value} onClick={() => onChange(v)}>{label}</button>
      ))}
    </div>
  );
}

/** Hide a table cell below a breakpoint. */
export const hideSm = "hidden sm:table-cell";
export const hideMd = "hidden md:table-cell";
export const hideLg = "hidden lg:table-cell";

/** A value on its scale with the warning and critical limits marked (Health sensors, storage, CPU threads).
 *  The fill takes the state colour: OK, warning, critical. ``below`` = limits are minimums (e.g. fan speed). */
export function LevelBar({ value, max, min = 0, warn, crit, below = false, fmt, state }: {
  value: number | null; max: number; min?: number; warn?: number | null; crit?: number | null; below?: boolean;
  fmt: (v: number) => string; state?: number;
}) {
  const span = Math.max(max - min, 1e-9);
  const pos = (v: number) => `${Math.max(0, Math.min(100, ((v - min) / span) * 100))}%`;
  const hit = (lim: number | null | undefined) => lim != null && value != null && (below ? value <= lim : value >= lim);
  const level = state ?? (hit(crit) ? 2 : hit(warn) ? 1 : 0);
  const fill = level >= 2 ? "bg-crit" : level === 1 ? "bg-warn" : "bg-ok";
  const limits = [warn != null && `warn ${fmt(warn)}`, crit != null && `crit ${fmt(crit)}`].filter(Boolean).join(" · ");
  return (
    <div className="flex items-center gap-3 w-full min-w-[10rem]">
      <div className="relative h-2 flex-1 bg-chip rounded-full" title={limits || undefined}>
        <div className={`absolute inset-y-0 left-0 rounded-full ${fill}`} style={{ width: value == null ? 0 : pos(value) }} />
        {warn != null && <span className="absolute -top-1 -bottom-1 w-0.5 rounded bg-warn" style={{ left: pos(warn) }} />}
        {crit != null && <span className="absolute -top-1 -bottom-1 w-0.5 rounded bg-crit" style={{ left: pos(crit) }} />}
      </div>
      <span className="text-xs tabular-nums text-strong w-[4.5rem] text-right shrink-0">{value == null ? "–" : fmt(value)}</span>
      <span className="text-xxs text-muted w-[7.5rem] shrink-0 hidden sm:inline truncate">{limits}</span>
    </div>
  );
}
