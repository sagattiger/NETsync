import { useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../../api";
import { Page, PageHeader } from "../../components/Layout";
import { AddressEditor } from "./AddressEditor";
import { BookEditor } from "./BookEditor";
import { BookList } from "./BookList";
import { ColumnManager } from "./ColumnManager";
import { ImportWizard } from "./ImportWizard";
import { IpBookSheet } from "./IpBookSheet";
import { RowEditor } from "./RowEditor";
import { RowsTable } from "./RowsTable";
import { Address, Book, IPB, IpBookView, Overview, Row, SearchResult, ServiceBookView } from "./types";

/** IP Book: books on the left (IP books for networks, service books for services); the chosen book on the right. */
export default function IpBook() {
  const { networkId } = useParams();
  const nav = useNavigate();
  const qc = useQueryClient();
  const [query, setQuery] = useState("");
  const [q, setQ] = useState("");
  const [toast, setToast] = useState<{ ok: boolean; text: string } | null>(null);
  const [editBook, setEditBook] = useState<Book | "new" | null>(null);
  const [editRow, setEditRow] = useState<Row | "new" | null>(null);
  const [editAddr, setEditAddr] = useState<Address | null>(null);
  const [colsOpen, setColsOpen] = useState(false);
  const [importing, setImporting] = useState(false);
  useEffect(() => { const t = window.setTimeout(() => setQ(query.trim()), 250); return () => window.clearTimeout(t); }, [query]);
  useEffect(() => { if (!toast) return; const t = window.setTimeout(() => setToast(null), 6000); return () => window.clearTimeout(t); }, [toast]);

  const { data: ov } = useQuery({ queryKey: ["ipbook", "overview"], queryFn: () => api<Overview>(`${IPB}/overview`), refetchInterval: 60_000 });
  const bookId = networkId ? Number(networkId) : ov?.books[0]?.id ?? null;
  const current = ov?.books.find((b) => b.id === bookId) ?? null;
  const { data: view, error } = useQuery({
    queryKey: ["ipbook", "book", bookId], enabled: !q && bookId != null && !!current,
    queryFn: () => api<IpBookView & ServiceBookView>(`${IPB}/books/${bookId}`), refetchInterval: 60_000,
  });
  const { data: found } = useQuery({ queryKey: ["ipbook", "search", q], enabled: !!q, queryFn: () => api<SearchResult>(`${IPB}/search?q=${encodeURIComponent(q)}`) });
  const refresh = () => qc.invalidateQueries({ queryKey: ["ipbook"] });
  const admin = !!ov?.is_admin;
  const pick = (id: number) => { setQuery(""); nav(`/ipbook/${id}`); };
  const onToast = (ok: boolean, text: string) => setToast({ ok, text });
  const isService = current?.kind === "service";

  return (
    <Page>
      <PageHeader title="IP Book" sub="IP books for your networks, service books for what runs on them"
        actions={admin && current ? <>
          {isService && <button className="btn" onClick={() => setImporting(true)}>Import</button>}
          <button className="btn" onClick={() => setColsOpen(true)}>Columns</button>
          {isService && <button className="btn btn-primary" onClick={() => setEditRow("new")}>+ New entry</button>}
        </> : undefined} />
      {toast && <div role="status" className={`text-sm ${toast.ok ? "text-ok" : "text-crit"}`}>{toast.text}</div>}
      {!ov ? <div className="text-sm text-muted">Loading…</div> : (
        <div className="flex flex-col lg:flex-row gap-4 items-start">
          <aside className="w-full lg:w-64 shrink-0">
            <div className="lg:hidden mb-2 flex gap-2">
              <select className="input flex-1" value={bookId ?? ""} onChange={(e) => pick(Number(e.target.value))} aria-label="Book">
                {ov.books.map((b) => <option key={b.id} value={b.id}>{b.kind === "ip" ? `${b.title} · ${b.cidr}` : `${b.title} (services)`}</option>)}
              </select>
              {admin && <button className="btn" onClick={() => setEditBook("new")}>+ Book</button>}
            </div>
            <div className="hidden lg:block card p-2 lg:sticky lg:top-16">
              <BookList books={ov.books} current={bookId} onPick={pick} query={query} setQuery={setQuery} onAdd={admin ? () => setEditBook("new") : undefined} />
            </div>
            <input className="input w-full text-xs lg:hidden" placeholder="Search IP, host, service…" value={query} onChange={(e) => setQuery(e.target.value)} aria-label="Search IP Book" />
          </aside>
          <div className="min-w-0 flex-1 space-y-3 w-full">
            {q ? (
              !found ? <div className="text-sm text-muted">Searching…</div> : (
                <>
                  <div className="text-xs text-muted">{found.addresses.length} addresses and {found.rows.length} services match "{q}"</div>
                  {found.addresses.length > 0 && (
                    <div className="card overflow-x-auto"><table className="tbl text-xs"><thead><tr><th>Address</th><th>Book</th><th>Hostname</th><th>Device</th><th>Info.</th></tr></thead>
                      <tbody>{found.addresses.map((a) => (
                        <tr key={`${a.book_id}:${a.ip}`}><td className="font-mono"><Link className="hover:text-accent" to={`/ipbook/${a.book_id}`} onClick={() => setQuery("")}>{a.ip}</Link></td>
                          <td>{a.book}</td><td>{a.values.addr_hostname ?? ""}</td><td>{a.values.addr_device ?? ""}</td><td className="max-w-[16rem] truncate">{a.values.addr_info ?? ""}</td></tr>))}</tbody></table></div>)}
                  {found.rows.length > 0 && <RowsTable rows={found.rows} columns={ov.columns.service} admin={admin} onToast={onToast} onEdit={setEditRow} />}
                </>)
            ) : !ov.books.length ? (
              <div className="card p-10 text-center space-y-3">
                <div className="text-base font-semibold text-strong">No books yet</div>
                <p className="text-sm text-muted max-w-md mx-auto">An <b>IP book</b> lists every address of one network, like a range sheet; discovery fills in what it finds.
                  A <b>service book</b> lists your services with their URLs, ports and logins.</p>
                {admin ? <button className="btn btn-primary" onClick={() => setEditBook("new")}>+ New book</button> : <p className="text-xs text-muted">An admin can create the first book.</p>}
              </div>
            ) : !current ? <div className="text-sm text-muted">This book doesn't exist any more. Pick one on the left.</div>
              : error ? <div className="text-sm text-crit">{(error as Error).message}</div> : !view ? <div className="text-sm text-muted">Loading…</div>
              : current.kind === "ip" ? (
                <IpBookSheet view={view} columns={ov.columns.ip} admin={admin} onEdit={setEditAddr} onToast={onToast}
                  onEditBook={admin ? () => setEditBook(current) : undefined} />
              ) : (
                <>
                  <div className="flex flex-wrap items-center gap-3">
                    <h2 className="text-base font-semibold text-strong">{current.title}</h2>
                    <span className="text-xs text-muted">{view.rows?.length ?? 0} entries{current.alert_when_down ? " · 🔔 alerts when down" : ""}</span>
                    {admin && <button className="btn ml-auto" onClick={() => setEditBook(current)}>Edit book</button>}
                  </div>
                  {current.description && <p className="text-sm text-fg2 whitespace-pre-line">{current.description}</p>}
                  <RowsTable rows={view.rows ?? []} columns={ov.columns.service} admin={admin} onToast={onToast} onEdit={setEditRow} />
                </>
              )}
          </div>
        </div>
      )}
      {editBook && <BookEditor book={editBook === "new" ? null : editBook} onClose={() => setEditBook(null)}
        onSaved={(id) => { const created = editBook === "new"; setEditBook(null); refresh(); if (id && created) pick(id); else if (!id) nav("/ipbook"); }} />}
      {editRow && ov && current && (
        <RowEditor row={editRow === "new" ? null : editRow} bookId={editRow === "new" ? current.id : editRow.book_id ?? current.id}
          columns={ov.columns.service} rows={view?.rows ?? []} onClose={() => setEditRow(null)} onSaved={() => { setEditRow(null); refresh(); }} />)}
      {editAddr && current && ov && <AddressEditor book={current} address={editAddr} columns={ov.columns.ip}
        onClose={() => setEditAddr(null)} onSaved={() => { setEditAddr(null); refresh(); }} />}
      {importing && current && <ImportWizard bookId={current.id} onClose={() => setImporting(false)} onDone={refresh} />}
      {colsOpen && ov && current && <ColumnManager kind={current.kind} columns={ov.columns[current.kind]} onClose={() => setColsOpen(false)} onSaved={refresh} />}
    </Page>
  );
}
