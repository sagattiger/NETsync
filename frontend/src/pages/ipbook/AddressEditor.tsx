import { useState } from "react";
import { api } from "../../api";
import { Modal } from "../../components/ui";
import { Address, Book, Column, IPB } from "./types";

/** Edit one address of an IP book (admins). Only fields you change are sent, so discovery keeps filling the rest. */
export function AddressEditor({ book, address, columns, onClose, onSaved }: {
  book: Book; address: Address; columns: Column[]; onClose: () => void; onSaved: () => void;
}) {
  const [vals, setVals] = useState<Record<string, string>>(() => Object.fromEntries(columns.map((c) => {
    const v = address.values[c.key];
    return [c.key, v == null ? "" : c.type === "bool" ? (v ? "yes" : "no") : String(v)];
  })));
  const [dirty, setDirty] = useState<Set<string>>(new Set());
  const [reserved, setReserved] = useState(address.reserved);
  const [alert, setAlert] = useState(address.alert_when_down == null ? "inherit" : address.alert_when_down ? "on" : "off");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const set = (k: string, v: string) => { setVals((x) => ({ ...x, [k]: v })); setDirty((d) => new Set(d).add(k)); };

  async function save(clearAll = false) {
    setBusy(true); setError("");
    const values: Record<string, any> = {};
    const keys = clearAll ? columns.map((c) => c.key) : [...dirty];
    for (const k of keys) {
      const c = columns.find((x) => x.key === k)!;
      const v = clearAll ? "" : vals[k];
      values[k] = v === "" ? null : c.type === "bool" ? v === "yes" : v;
    }
    try {
      await api(`${IPB}/books/${book.id}/addresses/${address.ip}`, { method: "PUT", body: {
        values, reserved: clearAll ? false : reserved, alert_when_down: clearAll || alert === "inherit" ? null : alert === "on" } });
      onSaved();
    } catch (e: any) { setError(e.message); } finally { setBusy(false); }
  }

  return (
    <Modal title={`${address.ip} · ${book.title}`} onClose={onClose} wide>
      <div className="grid sm:grid-cols-2 gap-3 max-h-[60vh] overflow-y-auto pr-1">
        {columns.map((c) => (
          <div key={c.key} className={c.type === "longtext" ? "sm:col-span-2" : ""}>
            <label className="label" htmlFor={`ae-${c.key}`}>{c.label}</label>
            {c.type === "longtext" ? <textarea id={`ae-${c.key}`} className="input w-full" rows={2} value={vals[c.key]} onChange={(e) => set(c.key, e.target.value)} />
              : c.type === "bool" ? <select id={`ae-${c.key}`} className="input w-full" value={vals[c.key]} onChange={(e) => set(c.key, e.target.value)}><option value="">—</option><option value="yes">yes</option><option value="no">no</option></select>
              : c.type === "choice" ? <select id={`ae-${c.key}`} className="input w-full" value={vals[c.key]} onChange={(e) => set(c.key, e.target.value)}><option value="">—</option>{(c.options ?? []).map((o) => <option key={o}>{o}</option>)}</select>
              : <input id={`ae-${c.key}`} className={`input w-full ${c.type === "ip" ? "font-mono" : ""}`} value={vals[c.key]} onChange={(e) => set(c.key, e.target.value)} />}
          </div>))}
      </div>
      <div className="grid sm:grid-cols-2 gap-3 mt-4">
        <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={reserved} onChange={(e) => setReserved(e.target.checked)} /> Reserved (keep this address free)</label>
        <div className="flex items-center gap-2 text-sm"><label htmlFor="ae-alert">Alert when down</label>
          <select id="ae-alert" className="input py-1" value={alert} onChange={(e) => setAlert(e.target.value)}>
            <option value="inherit">As the book says</option><option value="on">On</option><option value="off">Off</option></select></div>
      </div>
      {address.learned && <p className="text-xs text-muted mt-2">● Discovery fills some fields; what you type here wins.</p>}
      {error && <div className="text-crit text-xs mt-3" role="alert">{error}</div>}
      <div className="mt-4 flex items-center justify-between gap-2">
        <button className="btn" disabled={busy} onClick={() => confirm(`Clear everything you wrote on ${address.ip}?`) && save(true)}>Clear address</button>
        <span className="flex gap-2"><button className="btn" onClick={onClose}>Cancel</button>
          <button className="btn btn-primary" onClick={() => save()} disabled={busy}>{busy ? "Saving…" : "Save"}</button></span>
      </div>
    </Modal>
  );
}
