import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api, fmtAgo } from "../../api";
import { Icon } from "../../components/Icon";
import { WidgetLogo } from "../dashboards/WidgetView";
import { WarningBadges } from "./Warnings";
import { Column, IPB, Row, rowHealth } from "./types";

const DOT = { up: "bg-ok", down: "bg-crit", unknown: "bg-unknown" } as Record<string, string>;
const SOURCE = { learned: "text-accent border-accent/40", manual: "text-muted border-line", imported: "text-fg2 border-line" } as Record<string, string>;

function Cell({ col, row, admin, revealed, onReveal, onCopy, highlight }: {
  col: Column; row: Row; admin: boolean; revealed?: string; onReveal: () => void; onCopy: () => void; highlight: boolean;
}) {
  if (col.type === "secret") {
    if (!row.secrets[col.key]?.set) return <span className="text-faint">—</span>;
    return (
      <span className="inline-flex items-center gap-1.5">
        <span className="font-mono">{revealed ?? "••••••"}</span>
        {admin && <>
          <button type="button" onClick={onReveal} className="text-muted hover:text-strong" title={revealed ? "Hide" : "Show (logged)"} aria-label={`Show ${col.label}`}>👁</button>
          <button type="button" onClick={onCopy} className="text-muted hover:text-strong" title="Copy (logged)" aria-label={`Copy ${col.label}`}>⧉</button>
        </>}
      </span>
    );
  }
  const v = row.values[col.key];
  if (v === undefined || v === null || v === "" || (Array.isArray(v) && !v.length)) return <span className="text-faint">—</span>;
  switch (col.type) {
    case "service":
      return <span className="inline-flex items-center gap-1.5 font-medium text-strong"><WidgetLogo logo={v.logo} className="w-4 h-4" />{v.name}</span>;
    case "device":
      return v.id ? <Link to={`/devices/${v.id}`} className="hover:text-accent">{v.name}</Link> : <span>{v.name}</span>;
    case "bool":
      return <span>{v ? "yes" : "no"}</span>;
    case "urls":
    case "url":
      return <span className="inline-flex flex-col">{(Array.isArray(v) ? v : [v]).map((u: string) => (
        <a key={u} href={u} target="_blank" rel="noopener noreferrer" className="text-accent hover:underline truncate max-w-[16rem]">{u.replace(/^https?:\/\//, "")}</a>))}</span>;
    case "ip":
      return <span className={`font-mono ${highlight ? "text-strong font-semibold bg-accent/10 rounded px-1 -mx-1" : ""}`}>{String(v)}</span>;
    case "longtext":
      return <span className="block max-w-[20rem] truncate" title={String(v)}>{String(v)}</span>;
    default:
      return <span className={col.type === "port" || col.type === "number" ? "tabular-nums" : ""}>{String(v)}</span>;
  }
}

/** The list of entries with its column icons, health, tags and (for admins) secrets on demand. */
export function RowsTable({ rows, columns, admin, onEdit, onToast }: {
  rows: Row[]; columns: Column[]; admin: boolean; onEdit?: (r: Row) => void; onToast: (ok: boolean, text: string) => void;
}) {
  const cols = columns.filter((c) => !c.hidden);
  const [revealed, setRevealed] = useState<Record<string, string>>({});
  const [pinging, setPinging] = useState<number | null>(null);
  useEffect(() => { // shown secrets hide themselves again
    if (!Object.keys(revealed).length) return;
    const t = window.setTimeout(() => setRevealed({}), 30_000);
    return () => window.clearTimeout(t);
  }, [revealed]);

  async function secret(r: Row, c: Column, action: "reveal" | "copy") {
    const k = `${r.id}:${c.key}`;
    if (action === "reveal" && revealed[k]) { setRevealed(({ [k]: _, ...rest }) => rest); return; }
    try {
      const { value } = await api<{ value: string | null }>(`${IPB}/rows/${r.id}/reveal`, { body: { column: c.key, action } });
      if (action === "copy") { await navigator.clipboard.writeText(value ?? ""); onToast(true, `${c.label} copied`); }
      else setRevealed((s) => ({ ...s, [k]: value ?? "" }));
    } catch (e: any) { onToast(false, e.message); }
  }
  async function ping(r: Row) {
    setPinging(r.id);
    try {
      const res = await api<{ ips: { ip: string; up: boolean; rtt_ms: number | null }[] }>(`${IPB}/rows/${r.id}/ping`, { method: "POST" });
      const text = res.ips.length ? res.ips.map((x) => `${x.ip} ${x.up ? `up ${x.rtt_ms?.toFixed(1)} ms` : "no answer"}`).join(" · ") : "No IP to ping";
      onToast(res.ips.every((x) => x.up), text);
    } catch (e: any) { onToast(false, e.message); } finally { setPinging(null); }
  }

  if (!rows.length) return <div className="card p-8 text-center text-sm text-muted">No entries here yet.</div>;
  return (
    <div className="card overflow-x-auto">
      <table className="tbl text-xs">
        <thead><tr>
          <th className="w-24">Health</th>
          {cols.map((c) => <th key={c.key}><span className="inline-flex items-center gap-1">{c.icon && <Icon name={c.icon} className="w-3.5 h-3.5" />}{c.label}</span></th>)}
          <th></th>
        </tr></thead>
        <tbody>
          {rows.map((r) => {
            const h = rowHealth(r);
            return (
              <tr key={r.id}>
                <td className="whitespace-nowrap" title={h ? `${h.state}${h.at ? `, ${fmtAgo(h.at)}` : ""}` : "Not pinged yet"}>
                  <span className={`inline-block w-2 h-2 rounded-full mr-1.5 ${DOT[h?.state ?? "unknown"]}`} />
                  <span className="text-muted">{h?.state === "up" && h.rtt != null ? `${h.rtt} ms` : h?.state === "down" ? "down" : "—"}</span>
                </td>
                {cols.map((c, i) => (
                  <td key={c.key} className="whitespace-nowrap">
                    {i === 0 && r.sensitive && <span className="mr-1" title="Sensitive: admins only">🔒</span>}
                    <Cell col={c} row={r} admin={admin} highlight={!!r.match_keys?.includes(c.key)} revealed={revealed[`${r.id}:${c.key}`]}
                      onReveal={() => secret(r, c, "reveal")} onCopy={() => secret(r, c, "copy")} />
                    {i === 0 && !!r.warnings?.length && <div className="mt-1"><WarningBadges items={r.warnings} /></div>}
                  </td>
                ))}
                <td className="text-right whitespace-nowrap">
                  <span className={`text-xxs px-1.5 py-0.5 rounded border mr-2 ${SOURCE[r.source]}`}>{r.source}</span>
                  <button type="button" className="btn h-7 text-xs mr-1" disabled={pinging === r.id} onClick={() => ping(r)}>{pinging === r.id ? "Pinging…" : "Ping"}</button>
                  {admin && onEdit && <button type="button" className="btn h-7 text-xs" onClick={() => onEdit(r)}>Edit</button>}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
