import { useMemo, useState } from "react";
import { api, fmtAgo } from "../../api";
import { Icon } from "../../components/Icon";
import { Address, AddressStatus, Column, IPB, IpBookView } from "./types";

const STATUS: Record<AddressStatus, string> = {
  available: "bg-ok/15 text-ok", used: "bg-accent/15 text-accent", gateway: "bg-ns-purple/15 text-ns-purple",
  reserved: "bg-warn/15 text-warn", down: "bg-crit/15 text-crit", subnet: "bg-inset text-muted", broadcast: "bg-inset text-muted",
};

/** An IP book like a range sheet: banner, then one row per address with its status and columns. */
export function IpBookSheet({ view, columns, admin, onEdit, onEditBook, onToast }: {
  view: IpBookView; columns: Column[]; admin: boolean; onEdit: (a: Address) => void; onEditBook?: () => void; onToast: (ok: boolean, text: string) => void;
}) {
  const b = view.book;
  const cols = columns.filter((c) => !c.hidden);
  const [filter, setFilter] = useState<"all" | "used" | "available">("all");
  const [q, setQ] = useState("");
  const [pinging, setPinging] = useState<string | null>(null);
  const rows = useMemo(() => {
    const s = q.trim().toLowerCase();
    return view.addresses.filter((a) =>
      (filter === "all" || (filter === "available" ? a.status === "available" : !["available", "subnet", "broadcast"].includes(a.status))) &&
      (!s || a.ip.includes(s) || Object.values(a.values).some((v) => String(v).toLowerCase().includes(s))));
  }, [view.addresses, filter, q]);

  async function ping(a: Address) {
    setPinging(a.ip);
    try {
      const r = await api<{ ips: { ip: string; up: boolean; rtt_ms: number | null }[] }>(`${IPB}/books/${b.id}/addresses/${a.ip}/ping`, { method: "POST" });
      const x = r.ips[0];
      onToast(x.up, `${x.ip} ${x.up ? `answers in ${x.rtt_ms?.toFixed(1)} ms` : "does not answer"}`);
    } catch (e: any) { onToast(false, e.message); } finally { setPinging(null); }
  }

  return (
    <div className="space-y-3">
      <section className="card overflow-hidden">
        <div className="bg-strong text-gap text-center px-4 py-2.5">
          {b.heading && <div className="text-sm font-semibold">{b.heading}</div>}
          <div className="text-sm font-semibold">Network : <span className="font-mono">{b.cidr}</span></div>
        </div>
        <div className="px-4 py-3 flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-muted">
          <span className="text-sm font-semibold text-strong">{b.title}</span>
          {b.vlan && <span>VLAN <b className="text-fg">{b.vlan}</b></span>}
          {b.gateway && <span>Gateway <b className="text-fg font-mono">{b.gateway}</b></span>}
          {b.dns && <span>DNS <b className="text-fg font-mono">{b.dns}</b></span>}
          <span>Used <b className="text-fg">{view.counts.used}</b> · available <b className="text-fg">{view.counts.available}</b>{view.counts.reserved ? <> · reserved <b className="text-fg">{view.counts.reserved}</b></> : null} of {view.counts.size}</span>
          {b.alert_when_down && <span title="A used address that stops answering becomes a problem">🔔 alerts when down</span>}
          {onEditBook && <button type="button" className="btn ml-auto" onClick={onEditBook}><Icon name="edit" className="w-3.5 h-3.5" /> Edit book</button>}
        </div>
        {b.description && <p className="px-4 pb-3 -mt-1 text-sm text-fg2 whitespace-pre-line">{b.description}</p>}
      </section>

      <div className="flex flex-wrap items-center gap-2">
        <div className="flex gap-1" role="tablist" aria-label="Show">
          {(["all", "used", "available"] as const).map((k) => (
            <button key={k} type="button" role="tab" aria-selected={filter === k} onClick={() => setFilter(k)}
              className={`px-2.5 py-1 rounded-md text-xs capitalize ${filter === k ? "bg-accent/15 text-strong font-medium" : "text-muted hover:text-fg hover:bg-inset"}`}>{k}</button>))}
        </div>
        <input className="input text-xs py-1.5 w-56" placeholder="Filter this book…" value={q} onChange={(e) => setQ(e.target.value)} aria-label="Filter addresses" />
        <span className="text-xs text-muted">{rows.length} rows</span>
      </div>

      <div className="card overflow-x-auto">
        <table className="tbl text-xs">
          <thead><tr>
            <th className="w-24">Status</th><th>Network</th>
            {cols.map((c) => <th key={c.key}><span className="inline-flex items-center gap-1">{c.icon && <Icon name={c.icon} className="w-3.5 h-3.5" />}{c.label}</span></th>)}
            <th>Last Change</th><th></th>
          </tr></thead>
          <tbody>
            {rows.map((a) => (
              <tr key={a.ip} className={a.status === "subnet" || a.status === "broadcast" ? "text-muted" : ""}>
                <td><span className={`inline-block w-full text-center rounded px-1.5 py-0.5 text-xxs font-medium ${STATUS[a.status]}`}
                  title={a.health ? `${a.health.state}${a.health.rtt != null ? ` ${a.health.rtt} ms` : ""}, ${fmtAgo(a.health.at)}` : undefined}>{a.status}</span></td>
                <td className="font-mono whitespace-nowrap">{a.ip}{a.learned && <span className="ml-1 text-xxs text-accent" title="Filled by discovery">●</span>}</td>
                {cols.map((c) => <td key={c.key} className="whitespace-nowrap max-w-[16rem] truncate" title={a.values[c.key] != null ? String(a.values[c.key]) : undefined}>
                  {a.values[c.key] != null && a.values[c.key] !== "" ? (c.type === "bool" ? (a.values[c.key] ? "yes" : "no") : String(a.values[c.key])) : ""}</td>)}
                <td className="whitespace-nowrap text-muted" title={a.updated_by ? `by ${a.updated_by}` : undefined}>{a.updated_at ? fmtAgo(a.updated_at) : ""}</td>
                <td className="text-right whitespace-nowrap">
                  {a.status !== "subnet" && a.status !== "broadcast" && <>
                    <button type="button" className="btn h-6 text-xxs mr-1" disabled={pinging === a.ip} onClick={() => ping(a)}>{pinging === a.ip ? "…" : "Ping"}</button>
                    {admin && <button type="button" className="btn h-6 text-xxs" onClick={() => onEdit(a)}>Edit</button>}
                  </>}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
