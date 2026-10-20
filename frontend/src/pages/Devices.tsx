import { useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api, Device, fmtAgo, fmtUptime, Group, Me } from "../api";
import { Icon } from "../components/Icon";
import { Page, PageHeader } from "../components/Layout";
import { osLabel, VendorLogo, VirtBadge } from "../components/VendorLogo";
import { Card, Empty, hideLg, hideMd, hideSm, Modal, Segmented, StateBadge } from "../components/ui";

function Counts({ d }: { d: Device }) {
  const pill = (n: number | undefined, cls: string) =>
    n ? <span className={`px-1.5 py-0.5 rounded-md text-xxs font-semibold tabular-nums ${cls}`}>{n}</span> : null;
  return (
    <div className="flex gap-1">
      {pill(d.services_ok, "bg-ok/10 text-ok")}
      {pill(d.services_warn, "bg-warn/15 text-warn")}
      {pill(d.services_crit, "bg-crit/10 text-crit")}
      {pill(d.services_unknown, "bg-unknown/15 text-unknown")}
    </div>
  );
}

export default function Devices() {
  const [params, setParams] = useSearchParams();
  const q = params.get("q") ?? "";
  const [adding, setAdding] = useState(false);
  const { data: me } = useQuery({ queryKey: ["me"], queryFn: () => api<Me>("/auth/me") });
  const { data = [], isLoading } = useQuery({
    queryKey: ["devices", q],
    queryFn: () => api<Device[]>(`/devices${q ? `?q=${encodeURIComponent(q)}` : ""}`),
    refetchInterval: 30_000,
  });

  return (
    <>
      <PageHeader
        title="Devices"
        sub={`${data.length} device${data.length === 1 ? "" : "s"}`}
        actions={
          <>
            <input className="input py-1.5 text-xs w-full sm:w-56" placeholder="Filter hostname / IP…" defaultValue={q}
              onKeyDown={(e) => { if (e.key === "Enter") setParams({ q: (e.target as HTMLInputElement).value }); }} />
            {me?.role !== "viewer" && (
              <button className="btn btn-primary" onClick={() => setAdding(true)}><Icon name="plus" className="w-3.5 h-3.5" /> Add device</button>
            )}
          </>
        }
      />
      <Page>
        <Card>
          {isLoading ? <Empty>Loading…</Empty> : !data.length ? <Empty>No devices yet. Add your first device.</Empty> : (
            <table className="tbl">
              <thead>
                <tr>
                  <th>Device</th><th className={hideMd}>Platform</th><th className={hideLg}>Location</th>
                  <th className={hideSm}>Services</th><th className={`text-right ${hideLg}`}>Ports</th>
                  <th className={hideLg}>Uptime</th><th className={hideMd}>Polled</th><th className="text-right">State</th>
                </tr>
              </thead>
              <tbody>
                {data.map((d) => (
                  <tr key={d.id} className={d.disabled ? "opacity-50" : ""}>
                    <td>
                      <Link to={`/devices/${d.id}`} className="flex items-center gap-3 group">
                        <VendorLogo device={d} size={34} />
                        <div className="min-w-0">
                          <div className="font-medium text-strong group-hover:text-accent transition-colors truncate">{d.hostname}</div>
                          <div className="text-xs text-muted flex items-center gap-1.5">{d.ip ?? d.ip_addresses?.[0]}<VirtBadge virtualization={d.virtualization} /></div>
                        </div>
                      </Link>
                    </td>
                    <td className={hideMd}>
                      <div className="text-fg">{[d.vendor, d.hardware].filter(Boolean).join(" ") || "-"}</div>
                      <div className="text-xs text-muted">{osLabel(d.os, d.version)}</div>
                    </td>
                    <td className={`text-fg2 text-xs ${hideLg}`}>{d.sys_location ?? "-"}</td>
                    <td className={hideSm}><Counts d={d} /></td>
                    <td className={`text-right tabular-nums ${hideLg}`}>{d.ports ?? 0}</td>
                    <td className={`text-xs tabular-nums text-fg2 ${hideLg}`}>{fmtUptime(d.uptime)}</td>
                    <td className={`text-xs text-muted ${hideMd}`}>{fmtAgo(d.last_polled)}</td>
                    <td className="text-right"><StateBadge state={d.status} small /></td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </Card>
      </Page>
      {adding && <AddDevice onClose={() => setAdding(false)} />}
    </>
  );
}

function AddDevice({ onClose }: { onClose: () => void }) {
  const qc = useQueryClient();
  const { data: groups = [] } = useQuery({ queryKey: ["groups"], queryFn: () => api<Group[]>("/groups") });
  const [f, setF] = useState({
    hostname: "", ip: "", snmp_version: "2c", snmp_port: 161, snmp_community: "public",
    v3_user: "", v3_auth_proto: "sha", v3_auth_key: "", v3_priv_proto: "aes", v3_priv_key: "",
    group_ids: [] as number[],
  });
  const [error, setError] = useState("");
  const set = (k: string, v: any) => setF((p) => ({ ...p, [k]: v }));

  async function save() {
    setError("");
    try {
      await api("/devices", {
        body: {
          hostname: f.hostname, ip: f.ip || null, snmp_version: f.snmp_version, snmp_port: +f.snmp_port,
          snmp_community: f.snmp_version === "3" ? null : f.snmp_community,
          snmp_v3: f.snmp_version === "3" ? {
            user: f.v3_user, auth_proto: f.v3_auth_key ? f.v3_auth_proto : null, auth_key: f.v3_auth_key || null,
            priv_proto: f.v3_priv_key ? f.v3_priv_proto : null, priv_key: f.v3_priv_key || null,
          } : null,
          group_ids: f.group_ids,
        },
      });
      qc.invalidateQueries({ queryKey: ["devices"] });
      onClose();
    } catch (e: any) { setError(e.message); }
  }

  return (
    <Modal title="Add device" onClose={onClose}>
      <div className="grid grid-cols-2 gap-4">
        <div className="col-span-2"><label className="label">Hostname</label>
          <input className="input w-full" value={f.hostname} onChange={(e) => set("hostname", e.target.value)} placeholder="core-sw1.example.net" /></div>
        <div className="col-span-2 sm:col-span-1"><label className="label">IP address (optional)</label>
          <input className="input w-full" value={f.ip} onChange={(e) => set("ip", e.target.value)} /></div>
        <div className="col-span-2 sm:col-span-1"><label className="label">SNMP version</label>
          <Segmented value={f.snmp_version} onChange={(v) => set("snmp_version", v)} options={[["1", "v1"], ["2c", "v2c"], ["3", "v3"]]} /></div>
        {f.snmp_version !== "3" ? (
          <>
            <div className="col-span-2 sm:col-span-1"><label className="label">Community</label>
              <input className="input w-full" value={f.snmp_community} onChange={(e) => set("snmp_community", e.target.value)} /></div>
            <div className="col-span-2 sm:col-span-1"><label className="label">Port</label>
              <input className="input w-full" value={f.snmp_port} onChange={(e) => set("snmp_port", e.target.value)} /></div>
          </>
        ) : (
          <>
            <div className="col-span-2"><label className="label">Username</label>
              <input className="input w-full" value={f.v3_user} onChange={(e) => set("v3_user", e.target.value)} /></div>
            <div><label className="label">Auth protocol</label>
              <select className="input w-full" value={f.v3_auth_proto} onChange={(e) => set("v3_auth_proto", e.target.value)}>
                {["md5", "sha", "sha256", "sha512"].map((p) => <option key={p}>{p}</option>)}
              </select></div>
            <div><label className="label">Auth key</label>
              <input className="input w-full" type="password" value={f.v3_auth_key} onChange={(e) => set("v3_auth_key", e.target.value)} /></div>
            <div><label className="label">Privacy protocol</label>
              <select className="input w-full" value={f.v3_priv_proto} onChange={(e) => set("v3_priv_proto", e.target.value)}>
                {["des", "aes", "aes256"].map((p) => <option key={p}>{p}</option>)}
              </select></div>
            <div><label className="label">Privacy key</label>
              <input className="input w-full" type="password" value={f.v3_priv_key} onChange={(e) => set("v3_priv_key", e.target.value)} /></div>
          </>
        )}
        {groups.length > 0 && (
          <div className="col-span-2"><label className="label">Groups</label>
            <div className="flex flex-wrap gap-2">
              {groups.map((g) => {
                const on = f.group_ids.includes(g.id);
                return (
                  <button key={g.id} type="button" onClick={() => set("group_ids", on ? f.group_ids.filter((x) => x !== g.id) : [...f.group_ids, g.id])}
                    className={`btn ${on ? "border-accent text-strong bg-accent/10" : ""}`}>{g.name}</button>
                );
              })}
            </div></div>
        )}
      </div>
      {error && <div className="text-crit text-xs mt-4">{error}</div>}
      <div className="mt-6 flex justify-end gap-2">
        <button className="btn" onClick={onClose}>Cancel</button>
        <button className="btn btn-primary" onClick={save} disabled={!f.hostname}>Add & discover</button>
      </div>
    </Modal>
  );
}
