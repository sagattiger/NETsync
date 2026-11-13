import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api, fmtAgo, fmtDateTime } from "../api";
import { Icon } from "../components/Icon";
import { Page, PageHeader } from "../components/Layout";
import { Card, Empty, hideMd, hideSm, Modal } from "../components/ui";

interface ApiToken {
  id: number; name: string; prefix: string; created_by: string | null; created_at: string;
  last_used_at: string | null; expires_at: string | null; revoked: boolean; status: "active" | "expired" | "revoked";
}

const STATUS = {
  active: "bg-ok/10 text-ok", expired: "bg-warn/15 text-warn", revoked: "bg-chip text-muted",
};

function CreateToken({ onClose }: { onClose: () => void }) {
  const qc = useQueryClient();
  const [name, setName] = useState("");
  const [expires, setExpires] = useState("");
  const [created, setCreated] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);
  const [error, setError] = useState("");

  async function create() {
    setError("");
    try {
      const r = await api<ApiToken & { token: string }>("/tokens", {
        body: { name, expires_at: expires ? new Date(`${expires}T23:59:59`).toISOString() : null },
      });
      setCreated(r.token);
      qc.invalidateQueries({ queryKey: ["tokens"] });
    } catch (e: any) { setError(e.message); }
  }

  async function copy() {
    if (!created) return;
    try { await navigator.clipboard.writeText(created); setCopied(true); } catch { setCopied(false); }
  }

  if (created) {
    return (
      <Modal title="Token created" onClose={onClose}>
        <div className="space-y-4">
          <div className="rounded-lg border border-warn/40 bg-warn/10 text-warn text-sm p-3">
            Copy it now: this is the only time the full token is shown. Only a hash is stored.
          </div>
          <div className="flex gap-2">
            <code className="flex-1 min-w-0 break-all font-mono text-sm px-3 py-2.5 rounded-lg bg-inset border border-line text-strong select-all">{created}</code>
            <button className="btn btn-primary shrink-0" onClick={copy}><Icon name={copied ? "check" : "note"} className="w-3.5 h-3.5" /> {copied ? "Copied" : "Copy"}</button>
          </div>
          <div className="text-xs text-muted">
            Use it as <code className="font-mono">Authorization: Bearer nst_…</code> on <code className="font-mono">/api/public/…</code>.
            It is read-only and is not accepted by any other NETsync endpoint.
          </div>
          <div className="flex justify-end"><button className="btn" onClick={onClose}>Done</button></div>
        </div>
      </Modal>
    );
  }

  return (
    <Modal title="New API token" onClose={onClose}>
      <div className="space-y-4">
        <div><label className="label">Name</label>
          <input className="input w-full" autoFocus maxLength={128} value={name} onChange={(e) => setName(e.target.value)}
            placeholder="Paymenter status page" /></div>
        <div><label className="label">Expires (optional)</label>
          <input className="input w-full" type="date" value={expires} min={new Date().toISOString().slice(0, 10)}
            onChange={(e) => setExpires(e.target.value)} />
          <div className="text-xs text-muted mt-1">Leave empty for a token that never expires. You can revoke it at any time.</div>
        </div>
        {error && <div className="text-xs text-crit">{error}</div>}
        <div className="flex justify-end gap-2">
          <button className="btn" onClick={onClose}>Cancel</button>
          <button className="btn btn-primary" onClick={create} disabled={!name.trim()}>Create token</button>
        </div>
      </div>
    </Modal>
  );
}

export default function Tokens() {
  const qc = useQueryClient();
  const [creating, setCreating] = useState(false);
  const { data = [], isLoading } = useQuery({ queryKey: ["tokens"], queryFn: () => api<ApiToken[]>("/tokens") });

  async function revoke(t: ApiToken) {
    if (!confirm(`Revoke "${t.name}"? Anything using it stops working immediately.`)) return;
    await api(`/tokens/${t.id}`, { method: "DELETE" });
    qc.invalidateQueries({ queryKey: ["tokens"] });
  }

  return (
    <>
      <PageHeader title="API tokens" sub="Read-only tokens for the public dashboards API (e.g. a status page on your website)"
        actions={<button className="btn btn-primary" onClick={() => setCreating(true)}><Icon name="plus" className="w-3.5 h-3.5" /> New token</button>} />
      <Page>
        <Card>
          {isLoading ? <Empty>Loading…</Empty> : !data.length ? <Empty>No API tokens yet.</Empty> : (
            <table className="tbl">
              <thead><tr>
                <th>Name</th><th>Token</th><th className={hideMd}>Created</th><th className={hideSm}>Last used</th>
                <th className={hideMd}>Expires</th><th>Status</th><th></th>
              </tr></thead>
              <tbody>
                {data.map((t) => (
                  <tr key={t.id} className={t.status === "active" ? "" : "opacity-60"}>
                    <td className="font-medium text-strong">{t.name}</td>
                    <td className="font-mono text-xs text-fg2">{t.prefix}…</td>
                    <td className={`text-xs text-fg2 ${hideMd}`}>{fmtDateTime(t.created_at)}<div className="text-muted">{t.created_by}</div></td>
                    <td className={`text-xs text-fg2 ${hideSm}`}>{t.last_used_at ? fmtAgo(t.last_used_at) : "never"}</td>
                    <td className={`text-xs text-fg2 ${hideMd}`}>{t.expires_at ? fmtDateTime(t.expires_at) : "never"}</td>
                    <td><span className={`text-xxs font-semibold uppercase px-2 py-0.5 rounded-pill ${STATUS[t.status]}`}>{t.status}</span></td>
                    <td className="text-right">
                      {!t.revoked && <button className="btn btn-ghost px-2 py-1 text-crit hover:bg-crit/10" onClick={() => revoke(t)}>Revoke</button>}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </Card>
        <p className="text-xs text-muted">
          Only dashboards marked <span className="text-strong">Public</span> are readable with a token, and responses never include hostnames,
          IP addresses, SNMP data, syslog, users, comments or check output. See docs/PUBLIC-API.md.
        </p>
      </Page>
      {creating && <CreateToken onClose={() => setCreating(false)} />}
    </>
  );
}
