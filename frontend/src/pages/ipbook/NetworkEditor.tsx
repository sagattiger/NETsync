import { useState } from "react";
import { api } from "../../api";
import { Icon, ICON_NAMES } from "../../components/Icon";
import { Modal } from "../../components/ui";
import { IPB, Network } from "./types";

/** Add or edit a network (admins). A learned network keeps its address and can only be hidden. */
export function NetworkEditor({ network, onClose, onSaved }: { network: Network | null; onClose: () => void; onSaved: (id?: number) => void }) {
  const [f, setF] = useState({
    cidr: network?.cidr ?? "", title: network?.title ?? "", description: network?.description ?? "", icon: network?.icon ?? "network",
    vlan: network?.vlan ?? "", gateway: network?.gateway ?? "", dns: network?.dns ?? "", alert_when_down: network?.alert_when_down ?? false,
    hidden: network?.hidden ?? false,
  });
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const set = (k: string, v: any) => setF((x) => ({ ...x, [k]: v }));
  const learned = network?.source === "learned";

  async function save() {
    setBusy(true); setError("");
    try {
      const body = { ...f, description: f.description || null, vlan: f.vlan || null, gateway: f.gateway || null, dns: f.dns || null };
      const out = await api<Network>(network ? `${IPB}/networks/${network.id}` : `${IPB}/networks`, { method: network ? "PUT" : "POST", body });
      onSaved(out.id);
    } catch (e: any) { setError(e.message); } finally { setBusy(false); }
  }
  async function remove() {
    if (!network) return;
    if (!confirm(learned ? `Hide ${network.cidr}? Discovery won't bring it back; entries stay.` : `Delete ${network.cidr}? Its entries stay in IP Book.`)) return;
    try { await api(`${IPB}/networks/${network.id}`, { method: "DELETE" }); onSaved(); } catch (e: any) { setError(e.message); }
  }
  const field = (k: keyof typeof f, label: string, props: Record<string, any> = {}) => (
    <div><label className="label" htmlFor={`nw-${k}`}>{label}</label>
      <input id={`nw-${k}`} className="input w-full" value={String(f[k] ?? "")} onChange={(e) => set(k, e.target.value)} {...props} /></div>
  );

  return (
    <Modal title={network ? `Edit ${network.cidr}` : "Add network"} onClose={onClose}>
      <div className="grid gap-3">
        <div className="grid sm:grid-cols-2 gap-3">
          {field("cidr", "Network (CIDR)", { placeholder: "10.0.0.0/24", disabled: learned, className: "input w-full font-mono" })}
          {field("title", "Title", { placeholder: "Servers" })}
        </div>
        <div><label className="label" htmlFor="nw-desc">Description</label>
          <textarea id="nw-desc" className="input w-full" rows={2} value={f.description} onChange={(e) => set("description", e.target.value)} /></div>
        <div className="grid sm:grid-cols-3 gap-3">
          {field("vlan", "VLAN")}
          {field("gateway", "Gateway", { className: "input w-full font-mono" })}
          {field("dns", "DNS", { className: "input w-full font-mono" })}
        </div>
        <div><span className="label">Icon</span>
          <div className="flex flex-wrap gap-1">{ICON_NAMES.map((n) => (
            <button key={n} type="button" title={n} aria-label={`Icon ${n}`} aria-pressed={f.icon === n} onClick={() => set("icon", n)}
              className={`w-8 h-8 rounded-lg flex items-center justify-center ${f.icon === n ? "bg-accent/20 text-accent ring-1 ring-accent" : "hover:bg-inset text-fg2"}`}>
              <Icon name={n} className="w-4 h-4" /></button>))}</div></div>
        <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={f.alert_when_down} onChange={(e) => set("alert_when_down", e.target.checked)} />
          Alert when down: an IP in this network that stops answering becomes a problem (entries can override)</label>
        {learned && network?.hidden && <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={f.hidden} onChange={(e) => set("hidden", e.target.checked)} /> Hidden</label>}
      </div>
      {error && <div className="text-crit text-xs mt-3" role="alert">{error}</div>}
      <div className="mt-4 flex items-center justify-between gap-2">
        {network ? <button className="btn text-crit" onClick={remove}>{learned ? "Hide network" : "Delete network"}</button> : <span />}
        <span className="flex gap-2"><button className="btn" onClick={onClose}>Cancel</button>
          <button className="btn btn-primary" onClick={save} disabled={busy || !f.cidr.trim()}>{busy ? "Saving…" : "Save"}</button></span>
      </div>
    </Modal>
  );
}
