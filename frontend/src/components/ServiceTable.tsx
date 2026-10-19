import { useState } from "react";
import { Link } from "react-router-dom";
import { useQueryClient } from "@tanstack/react-query";
import { api, fmtAgo, Service } from "../api";
import { Empty, hideLg, hideMd, Modal, StateBadge } from "./ui";

export default function ServiceTable({ services, showHost, canAck = true }: { services: Service[]; showHost?: boolean; canAck?: boolean }) {
  const qc = useQueryClient();
  const [ackFor, setAckFor] = useState<Service | null>(null);
  const [comment, setComment] = useState("");

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

  if (!services.length) return <Empty>No services</Empty>;
  return (
    <>
      <table className="tbl">
        <thead>
          <tr>
            <th className="w-24">State</th>
            {showHost && <th>Device</th>}
            <th>Service</th>
            <th className={hideMd}>Summary</th>
            <th className={`w-24 ${hideLg}`}>Since</th>
            <th className={`w-24 ${hideLg}`}>Checked</th>
            {canAck && <th className="w-24"></th>}
          </tr>
        </thead>
        <tbody>
          {services.map((s) => (
            <tr key={s.id}>
              <td><StateBadge state={s.state} small /></td>
              {showHost && (
                <td className="whitespace-nowrap"><Link className="link" to={`/devices/${s.device_id}`}>{s.hostname}</Link></td>
              )}
              <td>
                <div className="font-medium text-strong whitespace-nowrap">
                  {s.name}
                  {s.acknowledged && (
                    <span title={`${s.ack_by}: ${s.ack_comment ?? ""}`} className="ml-2 text-xxs px-1.5 py-0.5 rounded-md bg-chip text-fg2 font-medium">ACK</span>
                  )}
                </div>
                <div className="md:hidden text-xs text-muted mt-0.5">{s.output}</div>
              </td>
              <td className={`text-fg2 ${hideMd}`}>{s.output}</td>
              <td className={`text-muted text-xs whitespace-nowrap ${hideLg}`}>{fmtAgo(s.last_change)}</td>
              <td className={`text-muted text-xs whitespace-nowrap ${hideLg}`}>{fmtAgo(s.last_check)}</td>
              {canAck && (
                <td className="text-right whitespace-nowrap">
                  {s.state > 0 && !s.acknowledged && (
                    <button className="btn btn-ghost px-2 py-1" onClick={() => setAckFor(s)}>Acknowledge</button>
                  )}
                  {s.acknowledged && (
                    <button className="btn btn-ghost px-2 py-1 text-muted"
                      onClick={async () => { await api(`/services/${s.id}/ack`, { method: "DELETE" }); refresh(); }}>
                      Remove ack
                    </button>
                  )}
                </td>
              )}
            </tr>
          ))}
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
