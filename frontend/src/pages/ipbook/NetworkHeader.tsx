import { Icon } from "../../components/Icon";
import { NetworkView, Warning } from "./types";

const GRID = { used: "bg-accent", down: "bg-crit", free: "bg-chip" } as Record<string, string>;

export function WarningBadges({ items }: { items: Warning[] }) {
  if (!items.length) return null;
  const byKind = new Map<string, Warning[]>();
  items.forEach((w) => byKind.set(w.kind, [...(byKind.get(w.kind) ?? []), w]));
  return (
    <span className="inline-flex flex-wrap gap-1">
      {[...byKind.values()].map((ws) => (
        <span key={ws[0].kind} title={ws.map((w) => w.text).join("\n")}
          className="text-xxs px-2 py-0.5 rounded-full border border-warn/40 text-warn bg-warn/10 whitespace-nowrap">
          ⚠ {ws.length > 1 ? `${ws.length} × ` : ""}{ws[0].text}
        </span>
      ))}
    </span>
  );
}

/** Network header: icon, title, CIDR, description, VLAN/gateway/DNS, how full it is, the address grid, warnings. */
export function NetworkHeader({ view, onEdit }: { view: NetworkView; onEdit?: () => void }) {
  const n = view.network!;
  const u = view.usage;
  return (
    <section className="card p-4 flex gap-3 items-start">
      <span className="w-10 h-10 rounded-xl bg-accent/15 text-accent flex items-center justify-center shrink-0">
        <Icon name={n.icon || "network"} className="w-5 h-5" />
      </span>
      <div className="min-w-0 flex-1 space-y-1.5">
        <div className="flex flex-wrap items-center gap-2">
          <h2 className="text-base font-semibold text-strong">{n.title || n.cidr}</h2>
          <span className="font-mono text-xs text-muted">{n.cidr}</span>
          <span className={`text-xxs px-2 py-0.5 rounded-full border ${n.source === "learned" ? "border-accent/40 text-accent" : "border-line text-muted"}`}>{n.source}</span>
          {n.alert_when_down && <span className="text-xxs px-2 py-0.5 rounded-full border border-line text-fg2" title="An IP in this network that stops answering becomes a problem (unless its entry says otherwise)">🔔 alerts when down</span>}
          <WarningBadges items={view.warnings ?? []} />
        </div>
        {n.description && <p className="text-sm text-fg2 whitespace-pre-line">{n.description}</p>}
        <div className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted">
          {n.vlan && <span>VLAN <b className="text-fg font-semibold">{n.vlan}</b></span>}
          {n.gateway && <span>Gateway <b className="text-fg font-mono font-semibold">{n.gateway}</b></span>}
          {n.dns && <span>DNS <b className="text-fg font-mono font-semibold">{n.dns}</b></span>}
          {u && <span>Used <b className="text-fg font-semibold">{u.used} / {u.size}</b> · free <b className="text-fg font-semibold">{u.free}</b></span>}
        </div>
        {view.grid && (
          <div className="grid gap-[2px] pt-1" style={{ gridTemplateColumns: `repeat(${view.grid.length > 64 ? 64 : 32}, minmax(0, 1fr))` }}
            role="img" aria-label={`Address map: ${u?.used ?? 0} used of ${u?.size ?? 0}`}>
            {view.grid.map((s, i) => <span key={i} className={`h-2 rounded-[2px] ${GRID[s] ?? GRID.used}`} title={`host ${i + 1}: ${s}`} />)}
          </div>
        )}
      </div>
      {onEdit && <button type="button" className="btn" onClick={onEdit}><Icon name="edit" className="w-3.5 h-3.5" /> Edit</button>}
    </section>
  );
}
