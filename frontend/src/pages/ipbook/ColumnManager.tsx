import { useState } from "react";
import { api } from "../../api";
import { Icon, ICON_NAMES } from "../../components/Icon";
import { Modal } from "../../components/ui";
import { Column, IPB } from "./types";

const CUSTOM_TYPES: [string, string][] = [
  ["text", "Text"], ["longtext", "Long text"], ["number", "Number"], ["url", "URL"], ["urls", "URLs"], ["ip", "IP address (pinged, checked)"],
  ["port", "Port"], ["secret", "Password / secret (encrypted, admins)"], ["bool", "Yes / no"], ["choice", "Choice from a list"],
];

/** Rename, re-icon, show/hide and reorder columns; add and delete your own (admins). */
export function ColumnManager({ kind, columns, onClose, onSaved }: { kind: "service" | "ip"; columns: Column[]; onClose: () => void; onSaved: () => void }) {
  const [cols, setCols] = useState(columns);
  const [error, setError] = useState("");
  const [add, setAdd] = useState({ label: "", type: "text", options: "" });
  const save = async (c: Column, patch: Partial<Column>) => {
    const next = { ...c, ...patch };
    setCols((cs) => cs.map((x) => (x.id === c.id ? next : x)));
    try { await api(`${IPB}/columns/${c.id}`, { method: "PUT", body: { label: next.label, type: next.type, icon: next.icon, options: next.options, hidden: next.hidden } }); onSaved(); }
    catch (e: any) { setError(e.message); }
  };
  async function move(i: number, d: -1 | 1) {
    const next = [...cols];
    const j = i + d;
    if (j < 0 || j >= next.length) return;
    [next[i], next[j]] = [next[j], next[i]];
    setCols(next);
    try { await api(`${IPB}/columns-order`, { method: "PUT", body: { ids: next.map((c) => c.id) } }); onSaved(); } catch (e: any) { setError(e.message); }
  }
  async function create() {
    setError("");
    try {
      await api(`${IPB}/columns`, { body: { kind, label: add.label, type: add.type, options: add.type === "choice" ? add.options.split(",").map((s) => s.trim()).filter(Boolean) : null } });
      setAdd({ label: "", type: "text", options: "" });
      onSaved();
      onClose();
    } catch (e: any) { setError(e.message); }
  }
  async function remove(c: Column) {
    setError("");
    try { await api(`${IPB}/columns/${c.id}`, { method: "DELETE" }); }
    catch (e: any) {
      if (!String(e.message).includes("entries have a value") || !confirm(`${e.message}. Delete it anyway?`)) { if (!String(e.message).includes("entries have a value")) setError(e.message); return; }
      try { await api(`${IPB}/columns/${c.id}?confirm=true`, { method: "DELETE" }); } catch (e2: any) { setError(e2.message); return; }
    }
    setCols((cs) => cs.filter((x) => x.id !== c.id));
    onSaved();
  }

  return (
    <Modal title={kind === "ip" ? "IP book columns" : "Service book columns"} onClose={onClose} wide>
      <ul className="divide-y divide-line border border-line rounded-lg max-h-[50vh] overflow-y-auto">
        {cols.map((c, i) => (
          <li key={c.id} className="flex flex-wrap items-center gap-2 px-3 py-2">
            <span className="flex flex-col">
              <button type="button" className="text-muted hover:text-strong text-xs leading-none" onClick={() => move(i, -1)} aria-label={`Move ${c.label} up`}>▲</button>
              <button type="button" className="text-muted hover:text-strong text-xs leading-none" onClick={() => move(i, 1)} aria-label={`Move ${c.label} down`}>▼</button>
            </span>
            <select className="input w-28 text-xs py-1" value={c.icon ?? ""} onChange={(e) => save(c, { icon: e.target.value || null })} aria-label={`Icon of ${c.label}`}>
              <option value="">no icon</option>{ICON_NAMES.map((n) => <option key={n} value={n}>{n}</option>)}
            </select>
            {c.icon && <Icon name={c.icon} className="w-4 h-4 text-fg2" />}
            <input className="input flex-1 min-w-[8rem] text-xs py-1" defaultValue={c.label} aria-label="Column name"
              onBlur={(e) => e.target.value.trim() && e.target.value !== c.label && save(c, { label: e.target.value.trim() })} />
            <span className="text-xxs text-muted w-16">{c.type}</span>
            <label className="text-xs flex items-center gap-1"><input type="checkbox" checked={!c.hidden} onChange={(e) => save(c, { hidden: !e.target.checked })} /> shown</label>
            {c.builtin ? <span className="text-xxs text-muted w-12 text-right">built-in</span>
              : <button type="button" className="text-xs text-muted hover:text-crit w-12 text-right" onClick={() => remove(c)}>Delete</button>}
          </li>))}
      </ul>
      <div className="mt-4 rounded-lg border border-line p-3 space-y-2">
        <div className="text-sm font-medium text-strong">Add a column</div>
        <div className="grid sm:grid-cols-3 gap-2">
          <input className="input" placeholder="Name, e.g. Rack" value={add.label} onChange={(e) => setAdd({ ...add, label: e.target.value })} aria-label="New column name" />
          <select className="input" value={add.type} onChange={(e) => setAdd({ ...add, type: e.target.value })} aria-label="New column type">
            {CUSTOM_TYPES.filter(([v]) => kind === "service" || v !== "secret").map(([v, l]) => <option key={v} value={v}>{l}</option>)}</select>
          {add.type === "choice" && <input className="input" placeholder="Options, comma separated" value={add.options} onChange={(e) => setAdd({ ...add, options: e.target.value })} aria-label="Choices" />}
        </div>
        <button className="btn btn-primary" disabled={!add.label.trim()} onClick={create}>Add column</button>
      </div>
      {error && <div className="text-crit text-xs mt-3" role="alert">{error}</div>}
      <div className="mt-4 flex justify-end"><button className="btn" onClick={onClose}>Done</button></div>
    </Modal>
  );
}
