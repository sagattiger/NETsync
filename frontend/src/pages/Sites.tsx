/** Settings → Sites: sites and data centers with their position, and where each device is on the world map. */
import { useEffect, useMemo, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import ReactECharts from "echarts-for-react";
import { api, Device } from "../api";
import { Icon } from "../components/Icon";
import { Page, PageHeader } from "../components/Layout";
import { loadWorld } from "../components/WorldMap";
import { Card, Empty, Modal } from "../components/ui";
import { useTheme } from "../theme";
import { useMe } from "./probes/shared";

export interface SiteRow { id: number; name: string; kind: "site" | "datacenter"; lat: number | null; lon: number | null; address: string | null; description: string | null; devices: number }

/** A map to click on: sets the position, zoom and drag to be precise. */
export function PickMap({ lat, lon, onPick, height = 260 }: { lat: number | null; lon: number | null; onPick: (lat: number, lon: number) => void; height?: number }) {
  const { theme } = useTheme();
  const [ready, setReady] = useState(false);
  useEffect(() => { loadWorld().then(() => setReady(true)); }, []);
  const night = theme === "dark";
  const option = useMemo(() => ready ? {
    backgroundColor: night ? "#071326" : "#eef4fb",
    geo: { map: "world", roam: true, center: lat != null && lon != null ? [lon, lat] : [-50, -14], zoom: lat != null ? 6 : 2.5,
      scaleLimit: { min: 0.8, max: 200 },
      itemStyle: night ? { areaColor: "#0d2747", borderColor: "rgba(56,189,248,.45)", borderWidth: 0.6 } : { areaColor: "#d9e3ee", borderColor: "#9fb2c8", borderWidth: 0.5 },
      emphasis: { disabled: true } },
    series: lat != null && lon != null ? [{ type: "effectScatter", coordinateSystem: "geo", data: [[lon, lat]], symbolSize: 10, itemStyle: { color: "#3b82f6" } }] : [],
    // eslint-disable-next-line react-hooks/exhaustive-deps
  } : null, [ready, night, lat, lon]);
  if (!option) return <div style={{ height }} className="rounded-lg bg-inset flex items-center justify-center text-xs text-muted">Loading the map…</div>;
  return (
    <div className="rounded-lg overflow-hidden border border-line">
      <ReactECharts option={option} style={{ height }} onChartReady={(chart: any) => {
        chart.getZr().on("click", (e: any) => {
          const pt = chart.convertFromPixel({ geoIndex: 0 }, [e.offsetX, e.offsetY]);
          if (pt && Number.isFinite(pt[0]) && Number.isFinite(pt[1])) onPick(Math.round(pt[1] * 1e5) / 1e5, Math.round(pt[0] * 1e5) / 1e5);
        });
      }} />
    </div>
  );
}

function SiteForm({ site, devices, onClose }: { site?: SiteRow; devices: Device[]; onClose: () => void }) {
  const qc = useQueryClient();
  const [f, setF] = useState({ name: site?.name ?? "", kind: site?.kind ?? "site", lat: site?.lat ?? null as number | null, lon: site?.lon ?? null as number | null,
    address: site?.address ?? "", description: site?.description ?? "" });
  const [members, setMembers] = useState<number[]>(() => devices.filter((d) => site && d.site_id === site.id).map((d) => d.id));
  const [q, setQ] = useState("");
  const [err, setErr] = useState("");
  const save = async () => {
    setErr("");
    try {
      await api(site ? `/sites/${site.id}` : "/sites", { method: site ? "PUT" : "POST", body: { ...f, address: f.address || null, description: f.description || null, device_ids: members } });
      qc.invalidateQueries({ queryKey: ["sites"] }); qc.invalidateQueries({ queryKey: ["map"] }); qc.invalidateQueries({ queryKey: ["devices"] });
      onClose();
    } catch (e: any) { setErr(e.message); }
  };
  const num = (v: string) => (v.trim() === "" || Number.isNaN(+v) ? null : +v);
  const shown = devices.filter((d) => d.device_type !== "probe" && (!q || d.hostname.toLowerCase().includes(q.toLowerCase())));
  return (
    <Modal title={site ? `Edit ${site.name}` : "Add a site"} onClose={onClose} wide>
      <div className="space-y-4">
        <div className="grid sm:grid-cols-[1fr_auto] gap-3">
          <label className="text-sm">Name<input className="input w-full mt-1" value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} placeholder="e.g. Osasco DC" /></label>
          <label className="text-sm">Type
            <div className="seg mt-1 flex">
              {(["site", "datacenter"] as const).map((k) => (
                <button key={k} type="button" className={f.kind === k ? "bg-seg-active text-on-seg-active" : ""} onClick={() => setF({ ...f, kind: k })}>{k === "site" ? "Site" : "Data center"}</button>
              ))}
            </div>
          </label>
        </div>
        <label className="text-sm block">Address (optional)<input className="input w-full mt-1" value={f.address} onChange={(e) => setF({ ...f, address: e.target.value })} /></label>
        <div className="grid grid-cols-2 gap-3">
          <label className="text-sm">Latitude<input className="input w-full mt-1 font-mono" value={f.lat ?? ""} onChange={(e) => setF({ ...f, lat: num(e.target.value) })} placeholder="-23.5329" /></label>
          <label className="text-sm">Longitude<input className="input w-full mt-1 font-mono" value={f.lon ?? ""} onChange={(e) => setF({ ...f, lon: num(e.target.value) })} placeholder="-46.7920" /></label>
        </div>
        <div>
          <div className="text-xs text-muted mb-1">Click the map to set the position (zoom with the wheel), or paste coordinates from a map service.</div>
          <PickMap lat={f.lat} lon={f.lon} onPick={(lat, lon) => setF((x) => ({ ...x, lat, lon }))} />
        </div>
        <div>
          <div className="flex items-center justify-between mb-1">
            <span className="text-sm text-strong">Devices at this site <span className="text-muted">({members.length})</span></span>
            <input className="input h-7 text-xs w-44" placeholder="Filter…" value={q} onChange={(e) => setQ(e.target.value)} />
          </div>
          <div className="max-h-48 overflow-y-auto border border-line rounded-lg p-2 grid sm:grid-cols-2 gap-1">
            {shown.map((d) => (
              <label key={d.id} className="flex items-center gap-2 text-xs cursor-pointer">
                <input type="checkbox" className="accent-accent" checked={members.includes(d.id)}
                  onChange={(e) => setMembers((m) => (e.target.checked ? [...m, d.id] : m.filter((x) => x !== d.id)))} />
                <span className="truncate">{d.hostname}</span>
                {d.site_id && d.site_id !== site?.id && <span className="text-muted">(moves here)</span>}
              </label>
            ))}
          </div>
        </div>
        {err && <div className="text-sm text-crit">{err}</div>}
        <div className="flex justify-end gap-2"><button className="btn" onClick={onClose}>Cancel</button>
          <button className="btn btn-primary" onClick={save} disabled={!f.name.trim()}>Save</button></div>
      </div>
    </Modal>
  );
}

function DeviceLocation({ d, onClose }: { d: Device; onClose: () => void }) {
  const qc = useQueryClient();
  const [lat, setLat] = useState<number | null>(d.lat ?? null);
  const [lon, setLon] = useState<number | null>(d.lon ?? null);
  const save = async (clear = false) => {
    await api(`/devices/${d.id}`, { method: "PATCH", body: clear ? { lat: null, lon: null } : { lat, lon } });
    qc.invalidateQueries({ queryKey: ["devices"] }); qc.invalidateQueries({ queryKey: ["map"] }); qc.invalidateQueries({ queryKey: ["device", d.id] });
    onClose();
  };
  return (
    <Modal title={`Location of ${d.hostname}`} onClose={onClose} wide>
      <div className="space-y-3">
        <div className="grid grid-cols-2 gap-3">
          <label className="text-sm">Latitude<input className="input w-full mt-1 font-mono" value={lat ?? ""} onChange={(e) => setLat(e.target.value === "" ? null : +e.target.value)} /></label>
          <label className="text-sm">Longitude<input className="input w-full mt-1 font-mono" value={lon ?? ""} onChange={(e) => setLon(e.target.value === "" ? null : +e.target.value)} /></label>
        </div>
        {d.sys_location && <div className="text-xs text-muted">SNMP location: {d.sys_location}</div>}
        <PickMap lat={lat} lon={lon} onPick={(a, b) => { setLat(a); setLon(b); }} />
        <div className="flex justify-end gap-2">
          {(d.lat != null || d.lon != null) && <button className="btn mr-auto" onClick={() => save(true)}>Remove location</button>}
          <button className="btn" onClick={onClose}>Cancel</button>
          <button className="btn btn-primary" onClick={() => save()} disabled={lat == null || lon == null}>Save</button>
        </div>
      </div>
    </Modal>
  );
}

export default function Sites() {
  const me = useMe();
  const qc = useQueryClient();
  const canEdit = me?.role !== "viewer";
  const { data: sites = [] } = useQuery({ queryKey: ["sites"], queryFn: () => api<SiteRow[]>("/sites") });
  const { data: devices = [] } = useQuery({ queryKey: ["devices"], queryFn: () => api<Device[]>("/devices") });
  const [editing, setEditing] = useState<SiteRow | "new" | null>(null);
  const [locating, setLocating] = useState<Device | null>(null);
  const [q, setQ] = useState("");
  const byId = new Map(sites.map((s) => [s.id, s]));
  const remove = async (s: SiteRow) => {
    if (!confirm(`Delete ${s.name}? Its devices keep their own location, if any.`)) return;
    await api(`/sites/${s.id}`, { method: "DELETE" });
    qc.invalidateQueries({ queryKey: ["sites"] }); qc.invalidateQueries({ queryKey: ["map"] }); qc.invalidateQueries({ queryKey: ["devices"] });
  };
  const setSite = async (d: Device, siteId: number | null) => {
    await api(`/devices/${d.id}`, { method: "PATCH", body: { site_id: siteId } });
    qc.invalidateQueries({ queryKey: ["devices"] }); qc.invalidateQueries({ queryKey: ["sites"] }); qc.invalidateQueries({ queryKey: ["map"] });
  };
  const list = devices.filter((d) => d.device_type !== "probe" && (!q || `${d.hostname} ${d.sys_location ?? ""}`.toLowerCase().includes(q.toLowerCase())))
    .sort((a, b) => a.hostname.localeCompare(b.hostname));

  return (
    <Page>
      <PageHeader title="Sites" sub="Sites and data centers show as blue buildings on the world map; their devices take their position."
        actions={canEdit && <button className="btn btn-primary" onClick={() => setEditing("new")}><Icon name="plus" className="w-3.5 h-3.5" /> Add site</button>} />
      <Card title={`Sites and data centers · ${sites.length}`}>
        {!sites.length ? <Empty>No sites yet. Add one, then pick its devices.</Empty> : (
          <table className="tbl">
            <thead><tr><th>Name</th><th>Type</th><th>Position</th><th className="hidden md:table-cell">Address</th><th>Devices</th><th /></tr></thead>
            <tbody>
              {sites.map((s) => (
                <tr key={s.id}>
                  <td className="text-strong font-medium">{s.name}</td>
                  <td className="text-xs">{s.kind === "datacenter" ? "Data center" : "Site"}</td>
                  <td className="font-mono text-xs">{s.lat != null && s.lon != null ? `${s.lat.toFixed(4)}, ${s.lon.toFixed(4)}` : <span className="text-warn">not set</span>}</td>
                  <td className="hidden md:table-cell text-xs text-muted">{s.address ?? ""}</td>
                  <td className="tabular-nums">{s.devices}</td>
                  <td className="text-right whitespace-nowrap">{canEdit && <>
                    <button className="btn h-7" onClick={() => setEditing(s)}>Edit</button>{" "}
                    <button className="btn h-7 text-crit" onClick={() => remove(s)}>Delete</button></>}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Card>

      <Card title="Devices" actions={<input className="input py-1 text-xs w-44" placeholder="Filter…" value={q} onChange={(e) => setQ(e.target.value)} />}>
        <table className="tbl">
          <thead><tr><th>Device</th><th className="hidden md:table-cell">SNMP location</th><th>Site</th><th>Position on the map</th><th /></tr></thead>
          <tbody>
            {list.map((d) => {
              const site = d.site_id ? byId.get(d.site_id) : undefined;
              const pos = site?.lat != null ? `${site.lat!.toFixed(4)}, ${site.lon!.toFixed(4)} (site)` : d.lat != null && d.lon != null ? `${d.lat.toFixed(4)}, ${d.lon.toFixed(4)}` : null;
              return (
                <tr key={d.id}>
                  <td className="text-strong">{d.hostname}</td>
                  <td className="hidden md:table-cell text-xs text-muted">{d.sys_location ?? ""}</td>
                  <td>
                    <select className="input h-7 py-0 text-xs" value={d.site_id ?? ""} disabled={!canEdit} onChange={(e) => setSite(d, e.target.value ? +e.target.value : null)}>
                      <option value="">No site</option>
                      {sites.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
                    </select>
                  </td>
                  <td className="font-mono text-xs">{pos ?? <span className="text-muted">none</span>}</td>
                  <td className="text-right">{canEdit && !site && <button className="btn h-7" onClick={() => setLocating(d)}><Icon name="globe" className="w-3.5 h-3.5" /> Set position</button>}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </Card>
      {editing && <SiteForm site={editing === "new" ? undefined : editing} devices={devices} onClose={() => setEditing(null)} />}
      {locating && <DeviceLocation d={locating} onClose={() => setLocating(null)} />}
    </Page>
  );
}
