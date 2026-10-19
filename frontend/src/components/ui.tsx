import { ReactNode, useEffect } from "react";
import { STATES } from "../api";
import { Icon } from "./Icon";

const STATE_TONE = ["text-ok bg-ok/10", "text-warn bg-warn/15", "text-crit bg-crit/10", "text-unknown bg-unknown/15"];
const STATE_TEXT = ["text-ok", "text-warn", "text-crit", "text-unknown"];
const STATE_BG = ["bg-ok", "bg-warn", "bg-crit", "bg-unknown"];

export function StateBadge({ state, small }: { state: number; small?: boolean }) {
  return (
    <span className={`inline-flex items-center gap-1.5 rounded-full font-semibold tracking-wide ${STATE_TONE[state] ?? "text-muted bg-inset"} ${small ? "text-xxs px-2 py-0.5" : "text-xs px-2.5 py-1"}`}>
      <span className={`w-1.5 h-1.5 rounded-full ${STATE_BG[state] ?? "bg-muted"}`} />
      {STATES[state] ?? "PEND"}
    </span>
  );
}

export const stateText = (state: number) => STATE_TEXT[state] ?? "text-muted";
export const stateBg = (state: number) => STATE_BG[state] ?? "bg-muted";

export function StateDot({ state, className = "" }: { state: number; className?: string }) {
  return <span className={`inline-block w-2 h-2 rounded-full ${stateBg(state)} ${className}`} />;
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

export function Tile({ label, value, tone, hint }: { label: string; value: ReactNode; tone?: number; hint?: ReactNode }) {
  return (
    <div className="card px-4 py-3.5">
      <div className="text-xs text-muted">{label}</div>
      <div className={`text-2xl font-semibold mt-1 tabular-nums ${tone !== undefined ? stateText(tone) : "text-strong"}`}>{value}</div>
      {hint && <div className="text-xxs text-muted mt-0.5">{hint}</div>}
    </div>
  );
}

export function Empty({ children }: { children: ReactNode }) {
  return <div className="px-4 py-10 text-center text-muted text-sm">{children}</div>;
}

export function Bar({ pct }: { pct: number | null | undefined }) {
  const p = Math.max(0, Math.min(100, pct ?? 0));
  const color = p >= 90 ? "bg-crit" : p >= 80 ? "bg-warn" : "bg-fg/70";
  return (
    <div className="flex items-center gap-2.5 min-w-[9rem]">
      <div className="h-1.5 flex-1 max-w-[8rem] bg-chip rounded-full overflow-hidden">
        <div className={`h-full rounded-full ${color}`} style={{ width: `${p}%` }} />
      </div>
      <span className="text-xs tabular-nums text-fg2 w-12">{pct == null ? "-" : `${p.toFixed(1)}%`}</span>
    </div>
  );
}

export function Modal({ title, onClose, children }: { title: string; onClose: () => void; children: ReactNode }) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);
  return (
    <div className="fixed inset-0 z-50 bg-black/50 backdrop-blur-[2px] flex items-end sm:items-start justify-center sm:pt-20 sm:px-4" onClick={onClose}>
      <div className="bg-surface border border-edge w-full sm:max-w-lg rounded-t-2xl sm:rounded-2xl shadow-2xl max-h-[90vh] overflow-y-auto" onClick={(e) => e.stopPropagation()}>
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
