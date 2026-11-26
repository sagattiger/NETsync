import { Icon } from "../../components/Icon";
import { NetworkSummary, Overview } from "./types";

/** Left column: search, "All rows", "No network", then every network with its usage and a warning dot. */
export function NetworkList({ ov, current, onPick, query, setQuery, onAdd }: {
  ov: Overview; current: string; onPick: (id: string) => void; query: string; setQuery: (q: string) => void; onAdd?: () => void;
}) {
  const item = (id: string, label: string, sub: string | null, icon: string, extra?: React.ReactNode, n?: NetworkSummary) => (
    <button key={id} type="button" onClick={() => onPick(id)} aria-current={current === id ? "page" : undefined}
      className={`w-full text-left px-2.5 py-2 rounded-lg flex items-start gap-2 transition-colors ${current === id ? "bg-accent/15 text-strong" : "hover:bg-inset text-fg"} ${n?.hidden ? "opacity-60" : ""}`}>
      <Icon name={icon} className="w-4 h-4 mt-0.5 shrink-0 text-fg2" />
      <span className="min-w-0 flex-1">
        <span className="flex items-center gap-1.5"><span className="truncate text-sm">{label}</span>{extra}</span>
        {sub && <span className="block font-mono text-xxs text-muted truncate">{sub}</span>}
        {n && (
          <span className="mt-1 block h-1 rounded-full bg-chip overflow-hidden" title={`${n.usage.used} of ${n.usage.size} used`}>
            <span className={`block h-full ${n.usage.pct > 90 ? "bg-crit" : "bg-accent"}`} style={{ width: `${Math.min(100, n.usage.pct)}%` }} />
          </span>
        )}
      </span>
    </button>
  );
  return (
    <nav aria-label="Networks" className="space-y-1">
      <input className="input w-full text-xs py-1.5 mb-2" placeholder="Search IP, host, service…" value={query}
        onChange={(e) => setQuery(e.target.value)} aria-label="Search IP Book" />
      {item("all", "All entries", `${ov.counts.all}`, "list")}
      {item("none", "No network", `${ov.counts.no_network}`, "alert")}
      <div className="text-xxs uppercase tracking-wide text-muted px-2.5 pt-3 pb-1">Networks</div>
      {ov.networks.map((n) => item(String(n.id), n.title || n.cidr, n.title && n.title !== n.cidr ? n.cidr : null, n.icon || "network",
        <>
          {n.source === "learned" && <span className="text-xxs text-accent" title="Learned from discovery">●</span>}
          {n.warning_count > 0 && <span className="text-xxs text-warn" title={`${n.warning_count} warnings`}>⚠ {n.warning_count}</span>}
          {n.hidden && <span className="text-xxs text-muted">(hidden)</span>}
        </>, n))}
      {!ov.networks.length && <p className="text-xs text-muted px-2.5">No networks yet. They are learned at the next discovery.</p>}
      {onAdd && <button type="button" onClick={onAdd} className="w-full text-left px-2.5 py-2 rounded-lg text-sm text-fg2 hover:bg-inset flex items-center gap-2"><Icon name="plus" className="w-4 h-4" /> Add network</button>}
    </nav>
  );
}
