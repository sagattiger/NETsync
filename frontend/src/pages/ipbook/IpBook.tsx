import { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../../api";
import { Page, PageHeader } from "../../components/Layout";
import { NetworkHeader } from "./NetworkHeader";
import { NetworkList } from "./NetworkList";
import { RowsTable } from "./RowsTable";
import { ColumnManager } from "./ColumnManager";
import { NetworkEditor } from "./NetworkEditor";
import { RowEditor } from "./RowEditor";
import { IPB, Network, NetworkView, Overview, Row } from "./types";

/** IP Book: networks on the left; the chosen network's header and its entries on the right. */
export default function IpBook() {
  const { networkId = "all" } = useParams();
  const nav = useNavigate();
  const qc = useQueryClient();
  const [editNet, setEditNet] = useState<Network | "new" | null>(null);
  const [editRow, setEditRow] = useState<Row | "new" | null>(null);
  const [colsOpen, setColsOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [q, setQ] = useState("");
  const [toast, setToast] = useState<{ ok: boolean; text: string } | null>(null);
  useEffect(() => { const t = window.setTimeout(() => setQ(query.trim()), 250); return () => window.clearTimeout(t); }, [query]);
  useEffect(() => { if (!toast) return; const t = window.setTimeout(() => setToast(null), 6000); return () => window.clearTimeout(t); }, [toast]);

  const { data: ov } = useQuery({ queryKey: ["ipbook", "overview"], queryFn: () => api<Overview>(`${IPB}/overview`), refetchInterval: 60_000 });
  const { data: view, error } = useQuery({
    queryKey: ["ipbook", "network", networkId], enabled: !q,
    queryFn: () => api<NetworkView>(`${IPB}/networks/${networkId}`), refetchInterval: 60_000,
  });
  const { data: found } = useQuery({ queryKey: ["ipbook", "search", q], enabled: !!q, queryFn: () => api<{ rows: Row[] }>(`${IPB}/search?q=${encodeURIComponent(q)}`) });
  const admin = !!ov?.is_admin;
  const pick = (id: string) => { setQuery(""); nav(id === "all" ? "/ipbook" : `/ipbook/${id}`); };
  const onToast = (ok: boolean, text: string) => setToast({ ok, text });
  const refresh = () => qc.invalidateQueries({ queryKey: ["ipbook"] });
  const { data: everything } = useQuery({ queryKey: ["ipbook", "network", "all"], enabled: !!editRow, queryFn: () => api<NetworkView>(`${IPB}/networks/all`) });

  return (
    <Page>
      <PageHeader title="IP Book" sub="Networks, IP addresses and what uses each one"
        actions={admin ? <>
          <button className="btn" onClick={() => setColsOpen(true)}>Columns</button>
          <button className="btn btn-primary" onClick={() => setEditRow("new")}>+ New entry</button>
        </> : undefined} />
      {toast && <div role="status" className={`text-sm ${toast.ok ? "text-ok" : "text-crit"}`}>{toast.text}</div>}
      {!ov ? <div className="text-sm text-muted">Loading…</div> : (
        <div className="flex flex-col lg:flex-row gap-4 items-start">
          <aside className="w-full lg:w-64 shrink-0">
            <div className="lg:hidden mb-2">
              <select className="input w-full" value={networkId} onChange={(e) => pick(e.target.value)} aria-label="Network">
                <option value="all">All entries ({ov.counts.all})</option>
                <option value="none">No network ({ov.counts.no_network})</option>
                {ov.networks.map((n) => <option key={n.id} value={n.id}>{n.title || n.cidr} · {n.cidr}</option>)}
              </select>
            </div>
            <div className="hidden lg:block card p-2 lg:sticky lg:top-16">
              <NetworkList ov={ov} current={networkId} onPick={pick} query={query} setQuery={setQuery} onAdd={admin ? () => setEditNet("new") : undefined} />
            </div>
            <input className="input w-full text-xs lg:hidden" placeholder="Search IP, host, service…" value={query} onChange={(e) => setQuery(e.target.value)} aria-label="Search IP Book" />
          </aside>
          <div className="min-w-0 flex-1 space-y-3 w-full">
            {q ? (
              <>
                <div className="text-xs text-muted">{found ? `${found.rows.length} entries match "${q}"` : "Searching…"}</div>
                {found && <RowsTable rows={found.rows} columns={ov.columns} admin={admin} onToast={onToast} onEdit={setEditRow} />}
              </>
            ) : error ? <div className="text-sm text-crit">{(error as Error).message}</div> : !view ? <div className="text-sm text-muted">Loading…</div> : (
              <>
                {view.network ? <NetworkHeader view={view} onEdit={admin ? () => setEditNet(view.network) : undefined} /> : (
                  <h2 className="text-base font-semibold text-strong">{networkId === "none" ? "Entries in no network" : "All entries"}</h2>
                )}
                <RowsTable rows={view.rows} columns={ov.columns} admin={admin} onToast={onToast} onEdit={setEditRow} />
              </>
            )}
          </div>
        </div>
      )}
      {editNet && <NetworkEditor network={editNet === "new" ? null : editNet} onClose={() => setEditNet(null)}
        onSaved={(id) => { setEditNet(null); refresh(); if (id && editNet === "new") pick(String(id)); }} />}
      {editRow && ov && <RowEditor row={editRow === "new" ? null : editRow} columns={ov.columns} rows={everything?.rows ?? []}
        onClose={() => setEditRow(null)} onSaved={() => { setEditRow(null); refresh(); }} />}
      {colsOpen && ov && <ColumnManager columns={ov.columns} onClose={() => setColsOpen(false)} onSaved={refresh} />}
    </Page>
  );
}
