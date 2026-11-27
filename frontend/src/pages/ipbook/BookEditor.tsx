import { useState } from "react";
import { api } from "../../api";
import { Icon, ICON_NAMES } from "../../components/Icon";
import { Modal } from "../../components/ui";
import { Book, IPB } from "./types";

/** Create a book (IP book for a network, or a service book) or edit one. A book's network can't change later. */
export function BookEditor({ book, onClose, onSaved }: { book: Book | null; onClose: () => void; onSaved: (id?: number) => void }) {
  const [kind, setKind] = useState<"ip" | "service">(book?.kind ?? "ip");
  const [f, setF] = useState({
    title: book?.title ?? "", heading: book?.heading ?? "", description: book?.description ?? "", icon: book?.icon ?? "",
    cidr: book?.cidr ?? "", vlan: book?.vlan ?? "", gateway: book?.gateway ?? "", dns: book?.dns ?? "", alert_when_down: book?.alert_when_down ?? false,
    scan: book?.scan ?? true,
  });
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const set = (k: string, v: any) => setF((x) => ({ ...x, [k]: v }));

  async function save() {
    setBusy(true); setError("");
    try {
      const out = await api<Book>(book ? `${IPB}/books/${book.id}` : `${IPB}/books`, { method: book ? "PUT" : "POST", body: { ...f, kind } });
      onSaved(out.id);
    } catch (e: any) { setError(e.message); } finally { setBusy(false); }
  }
  async function remove() {
    if (!book) return;
    const what = book.kind === "ip" ? "everything written on its addresses" : "all its entries and their passwords";
    if (!confirm(`Delete the book "${book.title}" and ${what}? This can't be undone.`)) return;
    try { await api(`${IPB}/books/${book.id}`, { method: "DELETE" }); onSaved(); } catch (e: any) { setError(e.message); }
  }
  const field = (k: keyof typeof f, label: string, props: Record<string, any> = {}) => (
    <div><label className="label" htmlFor={`bk-${k}`}>{label}</label>
      <input id={`bk-${k}`} className="input w-full" value={String(f[k] ?? "")} onChange={(e) => set(k, e.target.value)} {...props} /></div>
  );

  return (
    <Modal title={book ? `Edit ${book.title}` : "New book"} onClose={onClose}>
      <div className="grid gap-3">
        {!book && (
          <div className="grid grid-cols-2 gap-2" role="radiogroup" aria-label="Kind of book">
            {([["ip", "IP book", "One network, a row per address"], ["service", "Service book", "A list of services, logins and URLs"]] as const).map(([k, l, d]) => (
              <button key={k} type="button" role="radio" aria-checked={kind === k} onClick={() => setKind(k)}
                className={`text-left rounded-lg border p-3 ${kind === k ? "border-accent bg-accent/10" : "border-line hover:bg-inset"}`}>
                <div className="text-sm font-medium text-strong">{l}</div><div className="text-xs text-muted">{d}</div>
              </button>))}
          </div>
        )}
        {kind === "ip" ? (
          <>
            <div className="grid sm:grid-cols-2 gap-3">
              {field("cidr", "Network", { placeholder: "10.0.0.0/24", disabled: !!book, className: "input w-full font-mono" })}
              {field("title", "Title", { placeholder: "Servers" })}
            </div>
            {field("heading", "Heading (banner over the list)", { placeholder: "RANGE IP Example Networks" })}
            <div className="grid sm:grid-cols-3 gap-3">
              {field("vlan", "VLAN")}
              {field("gateway", "Gateway", { className: "input w-full font-mono" })}
              {field("dns", "DNS", { className: "input w-full font-mono" })}
            </div>
            <p className="text-xs text-muted">Up to /20 (4094 addresses). Discovery fills in the addresses it finds on your devices.</p>
            <label className="flex items-start gap-2 text-sm"><input type="checkbox" className="mt-1" checked={f.scan} onChange={(e) => set("scan", e.target.checked)} />
              <span>Scan the network: ping every address each round, so addresses in use that no monitored device has show up as live, with their DNS name</span></label>
          </>
        ) : field("title", "Name", { placeholder: "Production stack" })}
        <div><label className="label" htmlFor="bk-desc">Description</label>
          <textarea id="bk-desc" className="input w-full" rows={2} value={f.description} onChange={(e) => set("description", e.target.value)} /></div>
        <div><span className="label">Icon</span>
          <div className="flex flex-wrap gap-1">{ICON_NAMES.map((n) => (
            <button key={n} type="button" title={n} aria-label={`Icon ${n}`} aria-pressed={f.icon === n} onClick={() => set("icon", n)}
              className={`w-8 h-8 rounded-lg flex items-center justify-center ${f.icon === n ? "bg-accent/20 text-accent ring-1 ring-accent" : "hover:bg-inset text-fg2"}`}>
              <Icon name={n} className="w-4 h-4" /></button>))}</div></div>
        <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={f.alert_when_down} onChange={(e) => set("alert_when_down", e.target.checked)} />
          Alert when down: an address in this book that stops answering becomes a problem (each row can override)</label>
      </div>
      {error && <div className="text-crit text-xs mt-3" role="alert">{error}</div>}
      <div className="mt-4 flex items-center justify-between gap-2">
        {book ? <button className="btn text-crit" onClick={remove}>Delete book</button> : <span />}
        <span className="flex gap-2"><button className="btn" onClick={onClose}>Cancel</button>
          <button className="btn btn-primary" onClick={save} disabled={busy || (kind === "ip" ? !f.cidr.trim() : !f.title.trim())}>{busy ? "Saving…" : book ? "Save" : "Create"}</button></span>
      </div>
    </Modal>
  );
}
