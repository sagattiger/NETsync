import { Icon } from "../../components/Icon";
import { BookSummary } from "./types";

/** Top bar: IP books (with how full they are), then service books, "+ New book" for admins, and search on the right. */
export function BookList({ books, current, onPick, query, setQuery, onAdd }: {
  books: BookSummary[]; current: number | null; onPick: (id: number) => void; query: string; setQuery: (q: string) => void; onAdd?: () => void;
}) {
  const ip = books.filter((b) => b.kind === "ip");
  const svc = books.filter((b) => b.kind === "service");
  const item = (b: BookSummary) => {
    const pct = b.counts && b.counts.size ? Math.round(((b.counts.size - b.counts.available) * 100) / b.counts.size) : 0;
    const on = current === b.id && !query;
    return (
      <button key={b.id} type="button" onClick={() => onPick(b.id)} aria-current={on ? "page" : undefined}
        title={b.kind === "ip" ? `${b.counts?.used ?? 0} used, ${b.counts?.available ?? 0} available` : `${b.entries ?? 0} entries`}
        className={`shrink-0 max-w-[14rem] text-left pl-2.5 pr-3 py-1.5 rounded-lg border flex items-center gap-2 transition-colors ${on ? "border-accent bg-accent/15 text-strong" : "border-line hover:bg-inset text-fg"}`}>
        <Icon name={b.icon || (b.kind === "ip" ? "network" : "list")} className="w-4 h-4 shrink-0 text-fg2" />
        <span className="min-w-0">
          <span className="block truncate text-sm leading-tight">{b.title}</span>
          {b.kind === "ip" ? (
            <span className="flex items-center gap-1.5">
              {b.title !== b.cidr && <span className="font-mono text-xxs text-muted truncate">{b.cidr}</span>}
              <span className="block w-10 h-1 rounded-full bg-chip overflow-hidden shrink-0">
                <span className={`block h-full ${pct > 90 ? "bg-crit" : "bg-accent"}`} style={{ width: `${Math.min(100, pct)}%` }} />
              </span>
            </span>
          ) : <span className="block text-xxs text-muted">{b.entries ?? 0} entries · services</span>}
        </span>
      </button>
    );
  };
  return (
    <nav aria-label="Books" className="card p-2 flex flex-wrap items-center gap-2">
      {ip.map(item)}
      {ip.length > 0 && svc.length > 0 && <span className="w-px h-8 bg-line shrink-0" aria-hidden />}
      {svc.map(item)}
      {onAdd && <button type="button" onClick={onAdd} className="btn shrink-0"><Icon name="plus" className="w-3.5 h-3.5" /> New book</button>}
      <input className="input text-xs py-1.5 w-full sm:w-64 sm:ml-auto" placeholder="Search IP, host, service…" value={query}
        onChange={(e) => setQuery(e.target.value)} aria-label="Search IP Book" />
    </nav>
  );
}
