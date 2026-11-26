import { useState } from "react";
import { api } from "../../api";
import { Modal } from "../../components/ui";
import { IPB } from "./types";

interface Plan { create: Record<string, any>[]; merge: { row_id: number; values: Record<string, any>; conflicts: Record<string, any> }[]; skip: number; networks: string[] }
interface Preview { sheets: string[]; header_row: number; header: string[]; mapping: (string | null)[]; columns: { key: string; label: string }[]; plan: Plan }
const NEW_TYPES: [string, string][] = [["text", "text"], ["longtext", "long text"], ["number", "number"], ["url", "URL"], ["ip", "IP"], ["port", "port"], ["secret", "secret"], ["bool", "yes/no"]];

function b64(file: File): Promise<string> {
  return new Promise((res, rej) => {
    const r = new FileReader();
    r.onload = () => res(String(r.result).split(",")[1] ?? "");
    r.onerror = () => rej(new Error("Can't read the file"));
    r.readAsDataURL(file);
  });
}
const slug = (s: string) => "c_" + (s.toLowerCase().replace(/[^a-z0-9]+/g, "_").replace(/^_|_$/g, "") || "column").slice(0, 40);
const label = (r: Record<string, any>) => r.service?.name || r.hostname || r.ip_mgmt || r.ip_lan || "(no name)";

/** Import a spreadsheet (admins): upload → match columns → preview → import. Nothing is saved before the last step. */
export function ImportWizard({ bookId, onClose, onDone }: { bookId: number; onClose: () => void; onDone: () => void }) {
  const [file, setFile] = useState<{ name: string; data: string } | null>(null);
  const [sheet, setSheet] = useState<string | null>(null);
  const [pv, setPv] = useState<Preview | null>(null);
  const [mapping, setMapping] = useState<(string | null)[]>([]);
  const [newCols, setNewCols] = useState<Record<string, { label: string; type: string }>>({});
  const [step, setStep] = useState<"upload" | "map" | "preview" | "done">("upload");
  const [result, setResult] = useState<Record<string, number> | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const body = (extra: Record<string, any> = {}) => ({ book_id: bookId, filename: file!.name, content_b64: file!.data, sheet, mapping: mapping.length ? mapping : null, new_columns: newCols, ...extra });
  async function preview(first = false) {
    setBusy(true); setError("");
    try {
      const out = await api<Preview>(`${IPB}/import/preview`, { body: first ? { book_id: bookId, filename: file!.name, content_b64: file!.data, sheet } : body() });
      setPv(out);
      if (first) { setMapping(out.mapping); setStep("map"); } else setStep("preview");
    } catch (e: any) { setError(e.message); } finally { setBusy(false); }
  }
  async function commit() {
    setBusy(true); setError("");
    try {
      setResult(await api<Record<string, number>>(`${IPB}/import/commit`, { body: body() }));
      setStep("done"); onDone();
    } catch (e: any) { setError(e.message); } finally { setBusy(false); }
  }
  function mapTo(i: number, value: string) {
    const next = [...mapping];
    if (value === "__new") {
      const key = slug(pv!.header[i] || `column ${i + 1}`);
      next[i] = key;
      setNewCols((c) => ({ ...c, [key]: { label: pv!.header[i] || key, type: "text" } }));
    } else next[i] = value || null;
    setMapping(next);
  }

  return (
    <Modal title="Import a spreadsheet" onClose={onClose} wide>
      {step === "upload" && (
        <div className="space-y-3">
          <p className="text-sm text-fg2">A CSV or Excel (.xlsx) file, up to 5 MB, with one row per service or host. A title or banner above the column names is fine. Passwords are encrypted as they come in.</p>
          <input type="file" accept=".csv,.xlsx,.xlsm" className="text-sm" aria-label="Spreadsheet file" onChange={async (e) => {
            const f = e.target.files?.[0]; if (!f) return;
            try { setFile({ name: f.name, data: await b64(f) }); setError(""); } catch (err: any) { setError(err.message); }
          }} />
          <div className="flex justify-end"><button className="btn btn-primary" disabled={!file || busy} onClick={() => preview(true)}>{busy ? "Reading…" : "Next"}</button></div>
        </div>
      )}

      {step === "map" && pv && (
        <div className="space-y-3">
          {pv.sheets.length > 1 && (
            <div className="flex items-center gap-2 text-sm"><label htmlFor="iw-sheet">Sheet</label>
              <select id="iw-sheet" className="input" value={sheet ?? pv.sheets[0]} onChange={(e) => { setSheet(e.target.value); setPv(null); setStep("upload"); }}>
                {pv.sheets.map((s) => <option key={s}>{s}</option>)}</select></div>)}
          <p className="text-sm text-fg2">Column names found on row {pv.header_row + 1}. Match each one to an IP Book column, make it a new column, or skip it.</p>
          <ul className="divide-y divide-line border border-line rounded-lg max-h-[50vh] overflow-y-auto">
            {pv.header.map((h, i) => (!h && !mapping[i]) ? null : (
              <li key={i} className="flex flex-wrap items-center gap-2 px-3 py-2 text-sm">
                <span className="w-48 truncate font-medium text-strong" title={h}>{h || <span className="text-muted">(no name)</span>}</span>
                <span className="text-muted">→</span>
                <select className="input text-xs py-1" value={mapping[i] && newCols[mapping[i]!] ? "__new" : mapping[i] ?? ""} onChange={(e) => mapTo(i, e.target.value)} aria-label={`Column for ${h}`}>
                  <option value="">skip</option>
                  {pv.columns.map((c) => <option key={c.key} value={c.key}>{c.label}</option>)}
                  <option value="__new">+ new column "{h}"</option>
                </select>
                {mapping[i] && newCols[mapping[i]!] && (
                  <select className="input text-xs py-1" value={newCols[mapping[i]!].type} aria-label="New column type"
                    onChange={(e) => setNewCols((c) => ({ ...c, [mapping[i]!]: { ...c[mapping[i]!], type: e.target.value } }))}>
                    {NEW_TYPES.map(([v, l]) => <option key={v} value={v}>{l}</option>)}</select>)}
              </li>))}
          </ul>
          <div className="flex justify-between"><button className="btn" onClick={() => setStep("upload")}>Back</button>
            <button className="btn btn-primary" disabled={busy} onClick={() => preview(false)}>{busy ? "Checking…" : "Preview"}</button></div>
        </div>
      )}

      {step === "preview" && pv && (
        <div className="space-y-3 max-h-[65vh] overflow-y-auto pr-1">
          <div className="flex flex-wrap gap-3 text-sm">
            <span className="px-2 py-1 rounded bg-ok/10 text-ok">{pv.plan.create.length} new</span>
            <span className="px-2 py-1 rounded bg-accent/10 text-accent">{pv.plan.merge.length} update entries already in this book</span>
            <span className="px-2 py-1 rounded bg-warn/10 text-warn">{pv.plan.merge.filter((m) => Object.keys(m.conflicts).length).length} to review</span>
            <span className="px-2 py-1 rounded bg-inset text-muted">{pv.plan.skip} skipped</span>
          </div>
          {pv.plan.merge.length > 0 && <details open><summary className="text-sm font-medium cursor-pointer">Merged</summary>
            <ul className="text-xs mt-1 space-y-1">{pv.plan.merge.map((m) => (
              <li key={m.row_id}>{label(m.values)}{Object.keys(m.conflicts).length > 0 &&
                <span className="text-warn"> · differs from discovery: {Object.keys(m.conflicts).join(", ")} (you'll choose later in the entry)</span>}</li>))}</ul></details>}
          {pv.plan.create.length > 0 && <details><summary className="text-sm font-medium cursor-pointer">New entries</summary>
            <ul className="text-xs mt-1 grid sm:grid-cols-2 gap-x-4">{pv.plan.create.map((r, i) => <li key={i}>{label(r)} <span className="text-muted font-mono">{r.ip_mgmt || r.ip_lan || ""}</span></li>)}</ul></details>}
          <div className="flex justify-between pt-1"><button className="btn" onClick={() => setStep("map")}>Back</button>
            <button className="btn btn-primary" disabled={busy} onClick={commit}>{busy ? "Importing…" : "Import"}</button></div>
        </div>
      )}

      {step === "done" && result && (
        <div className="space-y-3">
          <p className="text-sm">Imported: {result.created} new, {result.merged} updated, {result.skipped} skipped.</p>
          <p className="text-xs text-muted">Entries whose values differ from discovery show a warning; open them to choose which to keep.</p>
          <div className="flex justify-end"><button className="btn btn-primary" onClick={onClose}>Done</button></div>
        </div>
      )}
      {error && <div className="text-crit text-xs mt-3" role="alert">{error}</div>}
    </Modal>
  );
}
