import { ReactNode } from "react";
import { STATES } from "../api";

const STATE_BG = ["bg-ok text-black", "bg-warn text-black", "bg-crit text-white", "bg-unknown text-black"];
const STATE_TEXT = ["text-ok", "text-warn", "text-crit", "text-unknown"];

export function StateBadge({ state, small }: { state: number; small?: boolean }) {
  return (
    <span className={`inline-block rounded-sm font-bold text-center ${STATE_BG[state] ?? "bg-gray-600"} ${small ? "text-xxs px-1 min-w-[38px]" : "text-xs px-1.5 py-0.5 min-w-[52px]"}`}>
      {STATES[state] ?? "PEND"}
    </span>
  );
}

export function stateText(state: number) {
  return STATE_TEXT[state] ?? "text-muted";
}

export function Card({ title, actions, children, className = "" }: { title?: ReactNode; actions?: ReactNode; children: ReactNode; className?: string }) {
  return (
    <div className={`card ${className}`}>
      {title && (
        <div className="card-title flex items-center justify-between">
          <span>{title}</span>
          {actions}
        </div>
      )}
      {children}
    </div>
  );
}

export function Tile({ label, value, tone }: { label: string; value: ReactNode; tone?: number }) {
  return (
    <div className="card px-4 py-3">
      <div className="text-xxs uppercase tracking-wide text-muted">{label}</div>
      <div className={`text-2xl font-semibold mt-1 ${tone !== undefined ? stateText(tone) : ""}`}>{value}</div>
    </div>
  );
}

export function Empty({ children }: { children: ReactNode }) {
  return <div className="px-3 py-6 text-center text-muted text-xs">{children}</div>;
}

export function Bar({ pct }: { pct: number | null | undefined }) {
  const p = Math.max(0, Math.min(100, pct ?? 0));
  const color = p >= 90 ? "bg-crit" : p >= 80 ? "bg-warn" : "bg-ok";
  return (
    <div className="flex items-center gap-2">
      <div className="h-2 w-28 bg-bg rounded overflow-hidden border border-line">
        <div className={`h-full ${color}`} style={{ width: `${p}%` }} />
      </div>
      <span className="text-xs tabular-nums">{pct == null ? "-" : `${p.toFixed(1)}%`}</span>
    </div>
  );
}

export function Modal({ title, onClose, children }: { title: string; onClose: () => void; children: ReactNode }) {
  return (
    <div className="fixed inset-0 z-50 bg-black/60 flex items-start justify-center pt-20 px-4" onClick={onClose}>
      <div className="card w-full max-w-lg" onClick={(e) => e.stopPropagation()}>
        <div className="card-title flex justify-between">
          <span>{title}</span>
          <button onClick={onClose} className="text-muted hover:text-white">✕</button>
        </div>
        <div className="p-4">{children}</div>
      </div>
    </div>
  );
}
