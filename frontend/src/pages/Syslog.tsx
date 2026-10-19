import { useState } from "react";
import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { api, SyslogMsg } from "../api";
import { PageHeader } from "../components/Layout";
import { Card, Empty } from "../components/ui";

const SEVERITY = ["emerg", "alert", "crit", "err", "warning", "notice", "info", "debug"];
const SEV_CLS = ["text-crit", "text-crit", "text-crit", "text-crit", "text-warn", "text-accent", "text-gray-300", "text-muted"];

export function SyslogTable({ rows, showDevice }: { rows: SyslogMsg[]; showDevice?: boolean }) {
  return (
    <table className="tbl font-mono text-xs">
      <thead><tr><th className="w-40">Time</th>{showDevice && <th>Source</th>}<th className="w-20">Severity</th><th className="w-36">Program</th><th>Message</th></tr></thead>
      <tbody>
        {rows.map((m) => (
          <tr key={m.id}>
            <td className="whitespace-nowrap text-muted">{new Date(m.time).toLocaleString()}</td>
            {showDevice && (
              <td className="whitespace-nowrap">
                {m.device_id ? <Link className="text-accent hover:underline" to={`/devices/${m.device_id}/syslog`}>{m.hostname ?? m.source_ip}</Link>
                  : <span className="text-muted">{m.hostname ?? m.source_ip}</span>}
              </td>
            )}
            <td className={SEV_CLS[m.severity]}>{SEVERITY[m.severity]}</td>
            <td className="truncate max-w-[9rem]">{m.program}</td>
            <td className="break-all">{m.message}</td>
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
            <select className="input text-xs" value={sev} onChange={(e) => setSev(+e.target.value)}>
              {SEVERITY.map((s, i) => <option key={s} value={i}>{s} and worse</option>)}
            </select>
            <form onSubmit={(e) => { e.preventDefault(); setSearch(q); }}>
              <input className="input text-xs w-64" placeholder="Search message…" value={q} onChange={(e) => setQ(e.target.value)} />
            </form>
          </>
        }
      />
      <div className="p-5">
        <Card>{isLoading ? <Empty>Loading…</Empty> : data.length ? <SyslogTable rows={data} showDevice /> : <Empty>No messages</Empty>}</Card>
      </div>
    </>
  );
}
