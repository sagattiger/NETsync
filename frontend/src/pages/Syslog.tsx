import { useState } from "react";
import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { api, SyslogMsg } from "../api";
import { Page, PageHeader } from "../components/Layout";
import { Card, Empty, hideMd, hideSm } from "../components/ui";

const SEVERITY = ["emerg", "alert", "crit", "err", "warning", "notice", "info", "debug"];
const SEV_CLS = ["text-crit", "text-crit", "text-crit", "text-crit", "text-warn", "text-accent", "text-fg2", "text-muted"];

export function SyslogTable({ rows, showDevice }: { rows: SyslogMsg[]; showDevice?: boolean }) {
  return (
    <table className="tbl text-xs">
      <thead><tr>
        <th className="w-40">Time</th>{showDevice && <th className={hideSm}>Source</th>}
        <th className="w-20">Severity</th><th className={`w-36 ${hideMd}`}>Program</th><th>Message</th>
      </tr></thead>
      <tbody>
        {rows.map((m) => (
          <tr key={m.id}>
            <td className="whitespace-nowrap text-muted tabular-nums">{new Date(m.time).toLocaleString()}</td>
            {showDevice && (
              <td className={`whitespace-nowrap ${hideSm}`}>
                {m.device_id ? <Link className="link" to={`/devices/${m.device_id}/syslog`}>{m.hostname ?? m.source_ip}</Link>
                  : <span className="text-muted">{m.hostname ?? m.source_ip}</span>}
              </td>
            )}
            <td className={`font-medium ${SEV_CLS[m.severity]}`}>{SEVERITY[m.severity]}</td>
            <td className={`truncate max-w-[9rem] text-fg2 ${hideMd}`}>{m.program}</td>
            <td className="break-all font-mono text-fg">{m.message}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

export default function Syslog() {
  const [q, setQ] = useState("");
  const [search, setSearch] = useState("");
  const [sev, setSev] = useState(7);
  const { data = [], isLoading } = useQuery({
    queryKey: ["syslog", "all", search, sev],
    queryFn: () => api<SyslogMsg[]>(`/syslog?limit=500&max_severity=${sev}${search ? `&q=${encodeURIComponent(search)}` : ""}`),
    refetchInterval: 10_000,
  });

  return (
    <>
      <PageHeader
        title="Syslog"
        sub="Messages received on UDP/TCP 514"
        actions={
          <>
            <select className="input py-1.5 text-xs" value={sev} onChange={(e) => setSev(+e.target.value)}>
              {SEVERITY.map((s, i) => <option key={s} value={i}>{s} and worse</option>)}
            </select>
            <form onSubmit={(e) => { e.preventDefault(); setSearch(q); }} className="w-full sm:w-auto">
              <input className="input py-1.5 text-xs w-full sm:w-64" placeholder="Search messages…" value={q} onChange={(e) => setQ(e.target.value)} />
            </form>
          </>
        }
      />
      <Page>
        <Card>{isLoading ? <Empty>Loading…</Empty> : data.length ? <SyslogTable rows={data} showDevice /> : <Empty>No messages</Empty>}</Card>
      </Page>
    </>
  );
}
