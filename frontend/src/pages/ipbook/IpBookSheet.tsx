import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { api, fmtAgo } from "../../api";
import { Icon } from "../../components/Icon";
import { VendorLogo } from "../../components/VendorLogo";
import { Address, AddressStatus, Column, Health, IPB, IpBookView } from "./types";

const STATUS: Record<AddressStatus, string> = {
  available: "bg-ok/15 text-ok", used: "bg-accent/15 text-accent", live: "bg-accent/10 text-fg2 ring-1 ring-inset ring-accent/40",
  gateway: "bg-ns-purple/15 text-ns-purple", reserved: "bg-warn/15 text-warn", down: "bg-crit/15 text-crit",
  subnet: "bg-inset text-muted", broadcast: "bg-inset text-muted",
};
const STATUS_HINT: Partial<Record<AddressStatus, string>> = {
  live: "Answers ping, but nothing is written on it and no monitored device has it (found by the network scan)",
  down: "Something is written on it, but it stopped answering ping",
};
const MAX_PING = 256;
const selectable = (a: Address) => a.status !== "subnet" && a.status !== "broadcast";

/** Last ping of an address: a dot and the response time. */
function PingCell({ h }: { h: Health | null }) {
  if (!h) return <span className="text-muted">—</span>;
  const tone = h.state === "up" ? "bg-ok" : h.state === "down" ? "bg-crit" : "bg-muted";
  const text = h.state === "up" ? (h.rtt != null ? `${h.rtt} ms` : "up") : h.state === "down" ? "down" : "no answer";
  return (
    <span className="inline-flex items-center gap-1.5 whitespace-nowrap" title={`Last ping ${fmtAgo(h.at)}`}>
      <span className={`w-2 h-2 rounded-full ${tone}`} aria-hidden /><span className={h.state === "up" ? "" : "text-muted"}>{text}</span>
    </span>
  );
}

/** An IP book like a range sheet: banner, then one row per address with its status, last ping and columns.
 *  Ping and Edit work on a selection: pressing one shows a checkbox on every row. */
export function IpBookSheet({ view, columns, admin, onEdit, onEditBook, onToast, onChanged }: {
  view: IpBookView; columns: Column[]; admin: boolean; onEdit: (a: Address[]) => void; onEditBook?: () => void;
  onToast: (ok: boolean, text: string) => void; onChanged: () => void;
}) {
  const b = view.book;
  const cols = columns.filter((c) => !c.hidden);
  const [filter, setFilter] = useState<"all" | "used" | "available">("all");
  const [q, setQ] = useState("");
  const [mode, setMode] = useState<"ping" | "edit" | null>(null);
  const [picked, setPicked] = useState<Set<string>>(new Set());
  const [busy, setBusy] = useState(false);
  const rows = useMemo(() => {
    const s = q.trim().toLowerCase();
    return view.addresses.filter((a) =>
      (filter === "all" || (filter === "available" ? a.status === "available" : !["available", "subnet", "broadcast"].includes(a.status))) &&
      (!s || a.ip.includes(s) || (a.health?.name ?? "").toLowerCase().includes(s) || Object.values(a.values).some((v) => String(v).toLowerCase().includes(s))));
  }, [view.addresses, filter, q]);
  const choosable = rows.filter(selectable);
  const allPicked = choosable.length > 0 && choosable.every((a) => picked.has(a.ip));

  const start = (m: "ping" | "edit") => { setMode(m); setPicked(new Set()); };
  const stop = () => { setMode(null); setPicked(new Set()); };
  const toggle = (ip: string) => setPicked((p) => { const n = new Set(p); n.has(ip) ? n.delete(ip) : n.add(ip); return n; });
  const toggleAll = () => setPicked(allPicked ? new Set() : new Set(choosable.map((a) => a.ip)));

  async function go() {
    const chosen = view.addresses.filter((a) => picked.has(a.ip));
    if (!chosen.length) return;
    if (mode === "edit") { onEdit(chosen); stop(); return; }
    setBusy(true);
    try {
      const r = await api<{ ips: { ip: string; up: boolean; rtt_ms: number | null }[] }>(`${IPB}/books/${b.id}/ping`, { method: "POST", body: { ips: chosen.map((a) => a.ip) } });
      const up = r.ips.filter((x) => x.up);
      onToast(up.length > 0, r.ips.length === 1
        ? `${r.ips[0].ip} ${r.ips[0].up ? `answers in ${r.ips[0].rtt_ms?.toFixed(1)} ms` : "does not answer"}`
        : `${up.length} of ${r.ips.length} addresses answer`);
      stop(); onChanged();
    } catch (e: any) { onToast(false, e.message); } finally { setBusy(false); }
  }

  const cell = (a: Address, c: Column) => {
    const v = a.values[c.key];
    const text = v != null && v !== "" ? (c.type === "bool" ? (v ? "yes" : "no") : String(v)) : "";
    if (c.key !== "addr_hostname") return text;
    const dns = !text && a.health?.name ? a.health.name : "";
    return (
      <span className="inline-flex items-center gap-1.5">
        {a.device && <VendorLogo device={a.device} size={18} />}
        {a.device ? <Link to={`/devices/${a.device.id}`} className="hover:text-accent" onClick={(e) => mode && e.preventDefault()}>{text || a.device.hostname}</Link>
          : dns ? <span className="text-muted" title="Name from DNS (reverse lookup)">{dns}</span> : text}
      </span>
    );
  };

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
          {b.scan && <span title="Every address is pinged each round; one that answers shows as live">Scanning the network</span>}
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
        <span className="ml-auto flex flex-wrap items-center gap-2">
          {!mode ? <>
            <button type="button" className="btn" onClick={() => start("ping")}><Icon name="pulse" className="w-3.5 h-3.5" /> Ping</button>
            {admin && <button type="button" className="btn" onClick={() => start("edit")}><Icon name="edit" className="w-3.5 h-3.5" /> Edit</button>}
          </> : <>
            <span className="text-xs text-muted" role="status">
              {picked.size ? `${picked.size} selected` : `Tick the addresses to ${mode}`}
              {mode === "ping" && picked.size > MAX_PING && ` · up to ${MAX_PING} at a time`}
            </span>
            <button type="button" className="btn btn-primary" onClick={go}
              disabled={busy || !picked.size || (mode === "ping" && picked.size > MAX_PING)}>
              <Icon name={mode === "ping" ? "pulse" : "edit"} className="w-3.5 h-3.5" />
              {busy ? "Pinging…" : mode === "ping" ? `Ping${picked.size ? ` ${picked.size}` : ""}` : `Edit${picked.size ? ` ${picked.size}` : ""}`}
            </button>
            <button type="button" className="btn" onClick={stop} disabled={busy}>Cancel</button>
          </>}
        </span>
      </div>

      {/* Scrolls inside the window, so the sideways scrollbar and the header stay in reach on a /24 or larger. */}
      <div className="card overflow-auto max-h-[calc(100vh-13rem)] min-h-[16rem]">
        <table className="tbl text-xs">
          <thead className="sticky top-0 z-10 bg-surface"><tr>
            {mode && <th className="w-8"><input type="checkbox" checked={allPicked} onChange={toggleAll} aria-label="Select every address shown" /></th>}
            <th className="w-24">Status</th><th>Network</th><th>Ping</th>
            {cols.map((c) => <th key={c.key}><span className="inline-flex items-center gap-1">{c.icon && <Icon name={c.icon} className="w-3.5 h-3.5" />}{c.label}</span></th>)}
            <th>Last Change</th>
          </tr></thead>
          <tbody>
            {rows.map((a) => {
              const can = selectable(a);
              const on = picked.has(a.ip);
              return (
                <tr key={a.ip} onClick={mode && can ? () => toggle(a.ip) : undefined}
                  className={`${!can ? "text-muted" : ""} ${mode && can ? "cursor-pointer" : ""} ${on ? "bg-accent/10" : ""}`}>
                  {mode && <td onClick={(e) => e.stopPropagation()}>{can && <input type="checkbox" checked={on} onChange={() => toggle(a.ip)} aria-label={`Select ${a.ip}`} />}</td>}
                  <td><span className={`inline-block w-full text-center rounded px-1.5 py-0.5 text-xxs font-medium ${STATUS[a.status]}`} title={STATUS_HINT[a.status]}>{a.status}</span></td>
                  <td className="font-mono whitespace-nowrap">{a.ip}{a.learned && <span className="ml-1 text-xxs text-accent" title="Filled by discovery">●</span>}</td>
                  <td>{can ? <PingCell h={a.health} /> : null}</td>
                  {cols.map((c) => <td key={c.key} className="whitespace-nowrap max-w-[16rem] truncate" title={a.values[c.key] != null ? String(a.values[c.key]) : undefined}>{cell(a, c)}</td>)}
                  <td className="whitespace-nowrap text-muted" title={a.updated_by ? `by ${a.updated_by}` : undefined}>{a.updated_at ? fmtAgo(a.updated_at) : ""}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}
