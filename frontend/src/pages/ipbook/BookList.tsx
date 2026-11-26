import { Icon } from "../../components/Icon";
import { BookSummary } from "./types";

/** Left column: search, then IP books (with how full they are) and service books, and "+ New book" for admins. */
export function BookList({ books, current, onPick, query, setQuery, onAdd }: {
  books: BookSummary[]; current: number | null; onPick: (id: number) => void; query: string; setQuery: (q: string) => void; onAdd?: () => void;
}) {
  const ip = books.filter((b) => b.kind === "ip");
  const svc = books.filter((b) => b.kind === "service");
  const item = (b: BookSummary) => {
    const pct = b.counts && b.counts.size ? Math.round(((b.counts.size - b.counts.available) * 100) / b.counts.size) : 0;
    return (
      <button key={b.id} type="button" onClick={() => onPick(b.id)} aria-current={current === b.id ? "page" : undefined}
        className={`w-full text-left px-2.5 py-2 rounded-lg flex items-start gap-2 transition-colors ${current === b.id ? "bg-accent/15 text-strong" : "hover:bg-inset text-fg"}`}>
        <Icon name={b.icon || (b.kind === "ip" ? "network" : "list")} className="w-4 h-4 mt-0.5 shrink-0 text-fg2" />
        <span className="min-w-0 flex-1">
          <span className="block truncate text-sm">{b.title}</span>
          {b.kind === "ip" ? (
            <>
              {b.title !== b.cidr && <span className="block font-mono text-xxs text-muted truncate">{b.cidr}</span>}
              <span className="mt-1 block h-1 rounded-full bg-chip overflow-hidden" title={`${b.counts?.used ?? 0} used, ${b.counts?.available ?? 0} available`}>
                <span className={`block h-full ${pct > 90 ? "bg-crit" : "bg-accent"}`} style={{ width: `${Math.min(100, pct)}%` }} />
              </span>
            </>
          ) : <span className="block text-xxs text-muted">{b.entries ?? 0} entries</span>}
        </span>
      </button>
    );
  };
  return (
    <nav aria-label="Books" className="space-y-1">
      <input className="input w-full text-xs py-1.5 mb-2" placeholder="Search IP, host, service…" value={query}
        onChange={(e) => setQuery(e.target.value)} aria-label="Search IP Book" />
      <div className="text-xxs uppercase tracking-wide text-muted px-2.5 pt-1 pb-1">IP books</div>
      {ip.map(item)}
      {!ip.length && <p className="text-xs text-muted px-2.5">None yet.</p>}
      <div className="text-xxs uppercase tracking-wide text-muted px-2.5 pt-3 pb-1">Service books</div>
      {svc.map(item)}
      {!svc.length && <p className="text-xs text-muted px-2.5">None yet.</p>}
      {onAdd && <button type="button" onClick={onAdd} className="w-full text-left px-2.5 py-2 mt-2 rounded-lg text-sm text-fg2 hover:bg-inset flex items-center gap-2"><Icon name="plus" className="w-4 h-4" /> New book</button>}
    </nav>
  );
}
