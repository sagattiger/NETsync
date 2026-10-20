import { Fragment, useState } from "react";
import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { api, fmtDateTime, SyslogMsg } from "../api";
import { AIResult, AskAIButton, useAI, useAIJob } from "../components/AskAI";
import { Icon } from "../components/Icon";
import { Page, PageHeader } from "../components/Layout";
import { Card, Empty, hideMd, hideSm } from "../components/ui";

const SEVERITY = ["emerg", "alert", "crit", "err", "warning", "notice", "info", "debug"];
const SEV_CLS = ["text-crit", "text-crit", "text-crit", "text-crit", "text-warn", "text-accent", "text-fg2", "text-muted"];

/** AI cell: sticker when an analysis exists, "Ask AI" for warning-or-worse lines. */
function SyslogAI({ m, onOpen }: { m: SyslogMsg; onOpen: () => void }) {
  const ai = useAI();
  if (!ai?.enabled) return null;
  const title = `AI · ${m.hostname ?? m.source_ip} · ${SEVERITY[m.severity]}`;
  if (m.ai) {
    const busy = m.ai.status === "pending" || m.ai.status === "running";
    return (
      <>
        <button onClick={onOpen} title={busy ? "AI is analysing" : m.ai.status === "error" ? "AI analysis failed" : "AI explanation"}
          className={`inline-flex items-center justify-center w-6 h-6 rounded-full ${m.ai.status === "error" ? "bg-crit/10 text-crit" : "bg-accent/15 text-accent"}`}>
          <Icon name="sparkles" className={`w-3.5 h-3.5 ${busy ? "animate-pulse" : ""}`} />
        </button>
      </>
    );
  }
  if (m.severity > 4) return null;
  return <AskAIButton compact target={{ kind: "syslog", syslog_id: m.id, syslog_time: m.time }} title={title} />;
}

/** Inline AI explanation under a syslog row. */
function SyslogAIDetail({ jobId }: { jobId: number }) {
  const { data: job } = useAIJob(jobId);
  return (
    <div className="max-w-3xl py-2 flex gap-3">
      <span className="w-7 h-7 rounded-full bg-accent/15 text-accent inline-flex items-center justify-center shrink-0">
        <Icon name="sparkles" className="w-3.5 h-3.5" />
      </span>
      <div className="flex-1 min-w-0">
        <div className="text-xs mb-1.5"><span className="font-medium text-strong">NETsync AI</span>
          <span className="ml-2 text-xxs font-semibold px-1.5 rounded bg-accent/15 text-accent">AI</span></div>
        <AIResult job={job} />
      </div>
    </div>
  );
}

export function SyslogTable({ rows, showDevice }: { rows: SyslogMsg[]; showDevice?: boolean }) {
  const ai = useAI();
  const [open, setOpen] = useState<number | null>(null);
  const cols = 4 + (showDevice ? 1 : 0) + (ai?.enabled ? 1 : 0);
  return (
    <table className="tbl text-xs">
      <thead><tr>
        <th className="w-40">Time</th>{showDevice && <th className={hideSm}>Source</th>}
        <th className="w-20">Severity</th><th className={`w-36 ${hideMd}`}>Program</th><th>Message</th>
        {ai?.enabled && <th className="w-12 text-right">AI</th>}
      </tr></thead>
      <tbody>
        {rows.map((m) => {
          const hasAI = !!m.ai && ai?.enabled;
          const isOpen = hasAI && open === m.id;
          return (
            <Fragment key={m.id}>
              <tr className={hasAI ? "cursor-pointer" : ""} onClick={() => hasAI && setOpen(isOpen ? null : m.id)}>
                <td className="whitespace-nowrap text-muted tabular-nums">
                  <div className="flex items-center gap-1.5">
                    {hasAI && <Icon name="chevron" className={`w-3 h-3 transition-transform ${isOpen ? "rotate-90" : ""}`} />}
                    {fmtDateTime(m.time)}
                  </div>
                </td>
                {showDevice && (
                  <td className={`whitespace-nowrap ${hideSm}`} onClick={(e) => e.stopPropagation()}>
                    {m.device_id ? <Link className="link" to={`/devices/${m.device_id}/syslog`}>{m.hostname ?? m.source_ip}</Link>
                      : <span className="text-muted">{m.hostname ?? m.source_ip}</span>}
                  </td>
                )}
                <td className={`font-medium ${SEV_CLS[m.severity]}`}>{SEVERITY[m.severity]}</td>
                <td className={`truncate max-w-[9rem] text-fg2 ${hideMd}`}>{m.program}</td>
                <td className="break-all font-mono text-fg">{m.message}</td>
                {ai?.enabled && <td className="text-right" onClick={(e) => e.stopPropagation()}><SyslogAI m={m} onOpen={() => setOpen(m.id)} /></td>}
              </tr>
              {isOpen && m.ai && (
                <tr><td colSpan={cols} className="bg-inset/40 px-4 sm:pl-10"><SyslogAIDetail jobId={m.ai.job_id} /></td></tr>
              )}
            </Fragment>
          );
        })}
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
