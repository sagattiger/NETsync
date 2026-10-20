import { useState } from "react";
import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { api, fmtDateTime, SyslogMsg } from "../api";
import { AIModal, AskAIButton, useAI } from "../components/AskAI";
import { Icon } from "../components/Icon";
import { Page, PageHeader } from "../components/Layout";
import { Card, Empty, hideMd, hideSm } from "../components/ui";

const SEVERITY = ["emerg", "alert", "crit", "err", "warning", "notice", "info", "debug"];
const SEV_CLS = ["text-crit", "text-crit", "text-crit", "text-crit", "text-warn", "text-accent", "text-fg2", "text-muted"];

/** AI cell: sticker when an analysis exists, "Ask AI" for warning-or-worse lines. */
function SyslogAI({ m }: { m: SyslogMsg }) {
  const ai = useAI();
  const [open, setOpen] = useState(false);
  if (!ai?.enabled) return null;
  const title = `AI · ${m.hostname ?? m.source_ip} · ${SEVERITY[m.severity]}`;
  if (m.ai) {
    const busy = m.ai.status === "pending" || m.ai.status === "running";
    return (
      <>
        <button onClick={() => setOpen(true)} title={busy ? "AI is analysing" : m.ai.status === "error" ? "AI analysis failed" : "AI explanation"}
          className={`inline-flex items-center justify-center w-6 h-6 rounded-full ${m.ai.status === "error" ? "bg-crit/10 text-crit" : "bg-accent/15 text-accent"}`}>
          <Icon name="sparkles" className={`w-3.5 h-3.5 ${busy ? "animate-pulse" : ""}`} />
        </button>
        {open && <AIModal jobId={m.ai.job_id} title={title} onClose={() => setOpen(false)} />}
      </>
    );
  }
  if (m.severity > 4) return null;
  return <AskAIButton compact target={{ kind: "syslog", syslog_id: m.id, syslog_time: m.time }} title={title} />;
}

export function SyslogTable({ rows, showDevice }: { rows: SyslogMsg[]; showDevice?: boolean }) {
  const ai = useAI();
  return (
    <table className="tbl text-xs">
      <thead><tr>
        <th className="w-40">Time</th>{showDevice && <th className={hideSm}>Source</th>}
        <th className="w-20">Severity</th><th className={`w-36 ${hideMd}`}>Program</th><th>Message</th>
        {ai?.enabled && <th className="w-12 text-right">AI</th>}
      </tr></thead>
      <tbody>
        {rows.map((m) => (
          <tr key={m.id}>
            <td className="whitespace-nowrap text-muted tabular-nums">{fmtDateTime(m.time)}</td>
            {showDevice && (
              <td className={`whitespace-nowrap ${hideSm}`}>
                {m.device_id ? <Link className="link" to={`/devices/${m.device_id}/syslog`}>{m.hostname ?? m.source_ip}</Link>
                  : <span className="text-muted">{m.hostname ?? m.source_ip}</span>}
              </td>
            )}
            <td className={`font-medium ${SEV_CLS[m.severity]}`}>{SEVERITY[m.severity]}</td>
            <td className={`truncate max-w-[9rem] text-fg2 ${hideMd}`}>{m.program}</td>
            <td className="break-all font-mono text-fg">{m.message}</td>
            {ai?.enabled && <td className="text-right"><SyslogAI m={m} /></td>}
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
