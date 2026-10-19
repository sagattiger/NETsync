import { useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api, Device, fmtAgo, fmtUptime, Group, Me } from "../api";
import { PageHeader } from "../components/Layout";
import { Card, Empty, Modal, StateBadge } from "../components/ui";

const TYPE_ICON: Record<string, string> = {
  router: "⇄", switch: "▤", firewall: "▣", server: "▥", network: "◈",
};

function Counts({ d }: { d: Device }) {
  const pill = (n: number | undefined, cls: string) =>
    n ? <span className={`px-1.5 rounded-sm text-xxs font-bold ${cls}`}>{n}</span> : null;
  return (
    <div className="flex gap-1">
      {pill(d.services_ok, "bg-ok/20 text-ok")}
      {pill(d.services_warn, "bg-warn text-black")}
      {pill(d.services_crit, "bg-crit text-white")}
      {pill(d.services_unknown, "bg-unknown text-black")}
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
        sub={`${data.length} devices`}
        actions={
          <>
            <input className="input text-xs w-56" placeholder="Filter hostname / IP…" defaultValue={q}
              onKeyDown={(e) => { if (e.key === "Enter") setParams({ q: (e.target as HTMLInputElement).value }); }} />
            {me?.role !== "viewer" && <button className="btn btn-primary" onClick={() => setAdding(true)}>+ Add device</button>}
          </>
        }
      />
      <div className="p-5">
        <Card>
          {isLoading ? <Empty>Loading…</Empty> : !data.length ? <Empty>No devices yet. Add your first device.</Empty> : (
            <table className="tbl">
              <thead>
                <tr>
                  <th className="w-16">State</th><th>Device</th><th>Platform</th><th>Location</th>
                  <th>Services</th><th className="text-right">Ports</th><th>Uptime</th><th>Last polled</th>
                </tr>
              </thead>
              <tbody>
                {data.map((d) => (
                  <tr key={d.id} className={d.disabled ? "opacity-50" : ""}>
                    <td><StateBadge state={d.status} small /></td>
                    <td>
                      <Link to={`/devices/${d.id}`} className="font-medium text-accent hover:underline">
                        <span className="text-muted mr-1.5">{TYPE_ICON[d.device_type ?? "network"] ?? "◈"}</span>{d.hostname}
                      </Link>
                      <div className="text-xxs text-muted">{d.ip} {d.sys_name && d.sys_name !== d.hostname ? `· ${d.sys_name}` : ""}</div>
                    </td>
                    <td>
                      <div>{[d.vendor, d.hardware].filter(Boolean).join(" ") || "-"}</div>
                      <div className="text-xxs text-muted">{[d.os, d.version].filter(Boolean).join(" ")}</div>
                    </td>
                    <td className="text-gray-300 text-xs">{d.sys_location ?? "-"}</td>
                    <td><Counts d={d} /></td>
                    <td className="text-right tabular-nums">{d.ports ?? 0}</td>
                    <td className="text-xs tabular-nums">{fmtUptime(d.uptime)}</td>
                    <td className="text-xs text-muted">{fmtAgo(d.last_polled)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </Card>
      </div>
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
      <div className="grid grid-cols-2 gap-3">
        <div className="col-span-2"><label className="label">Hostname</label>
          <input className="input w-full" value={f.hostname} onChange={(e) => set("hostname", e.target.value)} placeholder="core-sw1.example.net" /></div>
        <div><label className="label">IP (optional)</label>
          <input className="input w-full" value={f.ip} onChange={(e) => set("ip", e.target.value)} /></div>
        <div className="grid grid-cols-2 gap-2">
          <div><label className="label">SNMP</label>
            <select className="input w-full" value={f.snmp_version} onChange={(e) => set("snmp_version", e.target.value)}>
              <option value="1">v1</option><option value="2c">v2c</option><option value="3">v3</option>
            </select></div>
          <div><label className="label">Port</label>
            <input className="input w-full" value={f.snmp_port} onChange={(e) => set("snmp_port", e.target.value)} /></div>
        </div>
        {f.snmp_version !== "3" ? (
          <div className="col-span-2"><label className="label">Community</label>
            <input className="input w-full" value={f.snmp_community} onChange={(e) => set("snmp_community", e.target.value)} /></div>
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
              {groups.map((g) => (
                <label key={g.id} className="btn cursor-pointer">
                  <input type="checkbox" checked={f.group_ids.includes(g.id)}
                    onChange={(e) => set("group_ids", e.target.checked ? [...f.group_ids, g.id] : f.group_ids.filter((x) => x !== g.id))} />
                  {g.name}
                </label>
              ))}
            </div></div>
        )}
      </div>
      {error && <div className="text-crit text-xs mt-3">{error}</div>}
      <div className="mt-4 flex justify-end gap-2">
        <button className="btn" onClick={onClose}>Cancel</button>
        <button className="btn btn-primary" onClick={save} disabled={!f.hostname}>Add & discover</button>
      </div>
    </Modal>
  );
}
