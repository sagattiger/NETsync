import { useState } from "react";
import { Link } from "react-router-dom";
import { useQueryClient } from "@tanstack/react-query";
import { api, fmtAgo, Service } from "../api";
import { Empty, Modal, StateBadge } from "./ui";

export default function ServiceTable({ services, showHost, canAck = true }: { services: Service[]; showHost?: boolean; canAck?: boolean }) {
  const qc = useQueryClient();
  const [ackFor, setAckFor] = useState<Service | null>(null);
  const [comment, setComment] = useState("");

  const refresh = () => {
    qc.invalidateQueries({ queryKey: ["problems"] });
    qc.invalidateQueries({ queryKey: ["services"] });
    qc.invalidateQueries({ queryKey: ["overview"] });
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
            <th className="w-16">State</th>
            {showHost && <th>Device</th>}
            <th>Service</th>
            <th>Summary</th>
            <th className="w-24">Age</th>
            <th className="w-24">Checked</th>
            {canAck && <th className="w-20"></th>}
          </tr>
        </thead>
        <tbody>
          {services.map((s) => (
            <tr key={s.id}>
              <td><StateBadge state={s.state} small /></td>
              {showHost && (
                <td><Link className="text-accent hover:underline" to={`/devices/${s.device_id}`}>{s.hostname}</Link></td>
              )}
              <td className="whitespace-nowrap">
                {s.name}
                {s.acknowledged && (
                  <span title={`${s.ack_by}: ${s.ack_comment ?? ""}`} className="ml-2 text-xxs px-1 rounded bg-line text-gray-300">ACK</span>
                )}
              </td>
              <td className="text-gray-300">{s.output}</td>
              <td className="text-muted text-xs whitespace-nowrap">{fmtAgo(s.last_change)}</td>
              <td className="text-muted text-xs whitespace-nowrap">{fmtAgo(s.last_check)}</td>
              {canAck && (
                <td className="text-right">
                  {s.state > 0 && !s.acknowledged && (
                    <button className="text-xs text-muted hover:text-accent" onClick={() => setAckFor(s)}>Acknowledge</button>
                  )}
                  {s.acknowledged && (
                    <button className="text-xs text-muted hover:text-accent"
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
        <Modal title={`Acknowledge: ${ackFor.name}`} onClose={() => setAckFor(null)}>
          <label className="label">Comment</label>
          <input className="input w-full" autoFocus value={comment} onChange={(e) => setComment(e.target.value)} />
          <div className="mt-4 flex justify-end gap-2">
            <button className="btn" onClick={() => setAckFor(null)}>Cancel</button>
            <button className="btn btn-primary" onClick={ack}>Acknowledge</button>
          </div>
        </Modal>
      )}
    </>
  );
}
