import { Fragment, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { useQueryClient } from "@tanstack/react-query";
import { api, fmtAgo, fmtDateTime, fmtElapsed, Service } from "../api";
import { AskAIButton } from "./AskAI";
import { CommentSticker, CommentThread } from "./EventComments";
import { Icon } from "./Icon";
import { Empty, hideLg, hideMd, hideSm, Modal, StateBadge } from "./ui";

const RESOLVED_VISIBLE_MS = 120_000;

/** Re-render every few seconds so durations tick and resolved rows age out. */
function useNow(intervalMs = 5000) {
  const [now, setNow] = useState(Date.now());
  useEffect(() => {
    const t = window.setInterval(() => setNow(Date.now()), intervalMs);
    return () => window.clearInterval(t);
  }, [intervalMs]);
  return now;
}

/**
 * Service / problem list.
 * ``problems`` mode (Overview, Problems, device problems): start time, live duration, resolved rows
 * shown green for 120 s, comment/AI stickers and an expandable thread (comment, pin, Ask AI).
 */
export default function ServiceTable({ services, showHost, canAck = true, problems = false }: {
  services: Service[]; showHost?: boolean; canAck?: boolean; problems?: boolean;
}) {
  const qc = useQueryClient();
  const now = useNow(problems ? 5000 : 60_000);
  const [ackFor, setAckFor] = useState<Service | null>(null);
  const [comment, setComment] = useState("");
  const [open, setOpen] = useState<number | null>(null);

  const refresh = () => {
    for (const key of ["problems", "services", "overview"]) qc.invalidateQueries({ queryKey: [key] });
  };

  async function ack() {
    if (!ackFor) return;
    await api(`/services/${ackFor.id}/ack`, { body: { comment } });
    setAckFor(null);
    setComment("");
    refresh();
  }

  const rows = problems
    ? services.filter((s) => !s.resolved || !s.resolved_at || now - new Date(s.resolved_at).getTime() < RESOLVED_VISIBLE_MS)
    : services;
  const cols = 4 + (showHost ? 1 : 0) + (problems ? 2 : 2) + (canAck ? 1 : 0);

  if (!rows.length) return <Empty>{problems ? "No problems" : "No services"}</Empty>;
  return (
    <>
      <table className="tbl">
        <thead>
          <tr>
            <th className="w-28">State</th>
            {showHost && <th>Device</th>}
            <th>Service</th>
            <th className={hideMd}>Summary</th>
            {problems ? (
              <>
                <th className={`w-40 ${hideLg}`}>Started</th>
                <th className={`w-28 ${hideSm}`}>Duration</th>
              </>
            ) : (
              <>
                <th className={`w-24 ${hideLg}`}>Since</th>
                <th className={`w-24 ${hideLg}`}>Checked</th>
              </>
            )}
            <th className="w-24 text-right">{problems ? "Notes" : ""}</th>
            {canAck && <th className="w-44"></th>}
          </tr>
        </thead>
        <tbody>
          {rows.map((s) => {
            const resolved = problems && s.resolved;
            const isOpen = open === s.id && !!s.event;
            const live = s.problem_since && !resolved ? (now - new Date(s.problem_since).getTime()) / 1000 : s.duration;
            return (
              <Fragment key={s.id}>
                <tr className={`${problems && s.event ? "cursor-pointer group" : ""} ${resolved ? "bg-ok/[0.06] opacity-90" : ""}`}
                  onClick={() => problems && s.event && setOpen(isOpen ? null : s.id)}>
                  <td>
                    <div className="flex items-center gap-1.5">
                      {problems && s.event && (
                        <Icon name="chevron" className={`w-3.5 h-3.5 text-muted transition-transform shrink-0 ${isOpen ? "rotate-90" : ""}`} />
                      )}
                      {resolved ? <StateBadge state={0} small label="RESOLVED" /> : <StateBadge state={s.state} small />}
                    </div>
                  </td>
                  {showHost && (
                    <td className="whitespace-nowrap" onClick={(e) => e.stopPropagation()}>
                      <Link className="link" to={`/devices/${s.device_id}`}>{s.hostname}</Link>
                    </td>
                  )}
                  <td>
                    <div className="font-medium text-strong whitespace-nowrap flex items-center gap-2">
                      {s.name}
                      {resolved && s.problem_state ? <span className="text-xxs text-muted font-normal">was <StateBadge state={s.problem_state} small /></span> : null}
                      {s.acknowledged && !resolved && (
                        <span title={`${s.ack_by}: ${s.ack_comment ?? ""}`} className="text-xxs px-1.5 py-0.5 rounded-md bg-chip text-fg2 font-medium">ACK</span>
                      )}
                    </div>
                    <div className="md:hidden text-xs text-muted mt-0.5">{s.output}</div>
                    {problems && (
                      <div className="lg:hidden text-xxs text-muted mt-0.5">
                        {s.problem_since && <>since {fmtDateTime(s.problem_since)}</>}
                        {resolved && s.resolved_at && <> · resolved {fmtDateTime(s.resolved_at)}</>}
                      </div>
                    )}
                  </td>
                  <td className={`text-fg2 min-w-[16rem] ${hideMd}`}>{s.output}</td>
                  {problems ? (
                    <>
                      <td className={`text-xs whitespace-nowrap ${hideLg}`}>
                        <div className="text-fg2">{fmtDateTime(s.problem_since)}</div>
                        {resolved && s.resolved_at && <div className="text-ok">resolved {fmtDateTime(s.resolved_at)}</div>}
                      </td>
                      <td className={`text-xs whitespace-nowrap tabular-nums ${hideSm} ${resolved ? "text-ok" : "text-fg2"}`}>
                        {fmtElapsed(live)}{resolved && <div className="text-xxs text-muted">total</div>}
                      </td>
                    </>
                  ) : (
                    <>
                      <td className={`text-muted text-xs whitespace-nowrap ${hideLg}`}>{fmtAgo(s.last_change)}</td>
                      <td className={`text-muted text-xs whitespace-nowrap ${hideLg}`}>{fmtAgo(s.last_check)}</td>
                    </>
                  )}
                  <td className="text-right whitespace-nowrap">
                    {problems && s.ai_status && (
                      <span className="inline-flex items-center justify-center w-6 h-6 rounded-full bg-accent/15 text-accent mr-1" title="AI is analysing this problem">
                        <Icon name="sparkles" className="w-3.5 h-3.5 animate-pulse" />
                      </span>
                    )}
                    {problems && s.event && <CommentSticker event={s.event} />}
                  </td>
                  {canAck && (
                    <td className="text-right whitespace-nowrap" onClick={(e) => e.stopPropagation()}>
                      {!resolved && s.state > 0 && s.state < 3 && (
                        <AskAIButton target={{ kind: "service", service_id: s.id }} title={`AI · ${s.hostname ? `${s.hostname} · ` : ""}${s.name}`} />
                      )}
                      {!resolved && s.state > 0 && !s.acknowledged && (
                        <button className="btn btn-ghost px-2 py-1" onClick={() => setAckFor(s)}>Acknowledge</button>
                      )}
                      {!resolved && s.acknowledged && (
                        <button className="btn btn-ghost px-2 py-1 text-muted"
                          onClick={async () => { await api(`/services/${s.id}/ack`, { method: "DELETE" }); refresh(); }}>
                          Remove ack
                        </button>
                      )}
                    </td>
                  )}
                </tr>
                {isOpen && s.event && (
                  <tr><td colSpan={cols} className="bg-inset/40 px-4 sm:pl-10">
                    <CommentThread deviceId={s.device_id} event={s.event} />
                  </td></tr>
                )}
              </Fragment>
            );
          })}
        </tbody>
      </table>
      {ackFor && (
        <Modal title={`Acknowledge ${ackFor.name}`} onClose={() => setAckFor(null)}>
          <label className="label">Comment</label>
          <input className="input w-full" autoFocus value={comment} onChange={(e) => setComment(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && ack()} placeholder="Working on it…" />
          <div className="mt-5 flex justify-end gap-2">
            <button className="btn" onClick={() => setAckFor(null)}>Cancel</button>
            <button className="btn btn-primary" onClick={ack}>Acknowledge</button>
          </div>
        </Modal>
      )}
    </>
  );
}
