import { useState } from "react";
import { api } from "../../api";
import { Modal } from "../../components/ui";
import { Address, Book, Column, IPB } from "./types";

/** Edit one or more addresses of an IP book (admins). Only fields you change are sent, so discovery keeps filling
 *  the rest; with several addresses, what you change is written on all of them and the rest stays as it is. */
export function AddressEditor({ book, addresses, columns, onClose, onSaved }: {
  book: Book; addresses: Address[]; columns: Column[]; onClose: () => void; onSaved: () => void;
}) {
  const one = addresses.length === 1 ? addresses[0] : null;
  const [vals, setVals] = useState<Record<string, string>>(() => Object.fromEntries(columns.map((c) => {
    const v = one?.values[c.key];
    return [c.key, v == null ? "" : c.type === "bool" ? (v ? "yes" : "no") : String(v)];
  })));
  const [dirty, setDirty] = useState<Set<string>>(new Set());
  const [reserved, setReserved] = useState(one ? (one.reserved ? "yes" : "no") : "keep");
  const [alert, setAlert] = useState(one ? (one.alert_when_down == null ? "inherit" : one.alert_when_down ? "on" : "off") : "keep");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const set = (k: string, v: string) => { setVals((x) => ({ ...x, [k]: v })); setDirty((d) => new Set(d).add(k)); };

  async function save(clearAll = false) {
    setBusy(true); setError("");
    const failed: string[] = [];
    for (const a of addresses) {
      const values: Record<string, any> = {};
      const keys = clearAll ? columns.map((c) => c.key) : [...dirty];
      for (const k of keys) {
        const c = columns.find((x) => x.key === k)!;
        const v = clearAll ? "" : vals[k];
        values[k] = v === "" ? null : c.type === "bool" ? v === "yes" : v;
      }
      const res = clearAll ? false : reserved === "keep" ? a.reserved : reserved === "yes";
      const al = clearAll ? null : alert === "keep" ? a.alert_when_down : alert === "inherit" ? null : alert === "on";
      try {
        await api(`${IPB}/books/${book.id}/addresses/${a.ip}`, { method: "PUT", body: { values, reserved: res, alert_when_down: al } });
      } catch (e: any) { failed.push(`${a.ip}: ${e.message}`); }
    }
    setBusy(false);
    if (failed.length) setError(failed.slice(0, 3).join(" · ") + (failed.length > 3 ? ` · and ${failed.length - 3} more` : ""));
    else onSaved();
  }

  const title = one ? `${one.ip} · ${book.title}` : `${addresses.length} addresses · ${book.title}`;
  return (
    <Modal title={title} onClose={onClose} wide>
      {!one && <p className="text-xs text-muted mb-3 font-mono break-words">{addresses.map((a) => a.ip).join(", ")}</p>}
      {!one && <p className="text-xs text-muted mb-3">Fields you leave untouched keep each address's own value. What you type goes on every address listed.</p>}
      <div className="grid sm:grid-cols-2 gap-3 max-h-[60vh] overflow-y-auto pr-1">
        {columns.map((c) => (
          <div key={c.key} className={c.type === "longtext" ? "sm:col-span-2" : ""}>
            <label className="label" htmlFor={`ae-${c.key}`}>{c.label}{!one && dirty.has(c.key) && <span className="text-accent"> · will be set</span>}</label>
            {c.type === "longtext" ? <textarea id={`ae-${c.key}`} className="input w-full" rows={2} value={vals[c.key]} onChange={(e) => set(c.key, e.target.value)} />
              : c.type === "bool" ? <select id={`ae-${c.key}`} className="input w-full" value={vals[c.key]} onChange={(e) => set(c.key, e.target.value)}><option value="">—</option><option value="yes">yes</option><option value="no">no</option></select>
              : c.type === "choice" ? <select id={`ae-${c.key}`} className="input w-full" value={vals[c.key]} onChange={(e) => set(c.key, e.target.value)}><option value="">—</option>{(c.options ?? []).map((o) => <option key={o}>{o}</option>)}</select>
              : <input id={`ae-${c.key}`} className={`input w-full ${c.type === "ip" ? "font-mono" : ""}`} value={vals[c.key]} onChange={(e) => set(c.key, e.target.value)} />}
          </div>))}
      </div>
      <div className="grid sm:grid-cols-2 gap-3 mt-4">
        <div className="flex items-center gap-2 text-sm"><label htmlFor="ae-res">Reserved (keep free)</label>
          <select id="ae-res" className="input py-1" value={reserved} onChange={(e) => setReserved(e.target.value)}>
            {!one && <option value="keep">Leave as it is</option>}<option value="yes">Yes</option><option value="no">No</option></select></div>
        <div className="flex items-center gap-2 text-sm"><label htmlFor="ae-alert">Alert when down</label>
          <select id="ae-alert" className="input py-1" value={alert} onChange={(e) => setAlert(e.target.value)}>
            {!one && <option value="keep">Leave as it is</option>}
            <option value="inherit">As the book says</option><option value="on">On</option><option value="off">Off</option></select></div>
      </div>
      {addresses.some((a) => a.learned) && <p className="text-xs text-muted mt-2">● Discovery fills some fields; what you type here wins.</p>}
      {error && <div className="text-crit text-xs mt-3" role="alert">{error}</div>}
      <div className="mt-4 flex items-center justify-between gap-2">
        <button className="btn" disabled={busy} onClick={() => confirm(one ? `Clear everything you wrote on ${one.ip}?` : `Clear everything you wrote on these ${addresses.length} addresses?`) && save(true)}>
          {one ? "Clear address" : "Clear addresses"}</button>
        <span className="flex gap-2"><button className="btn" onClick={onClose}>Cancel</button>
          <button className="btn btn-primary" onClick={() => save()} disabled={busy}>{busy ? "Saving…" : one ? "Save" : `Save ${addresses.length}`}</button></span>
      </div>
    </Modal>
  );
}
