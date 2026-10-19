import { Fragment, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api, Component, Device, fmtAgo, fmtBps, fmtBytes, fmtUptime, Me, PluginInfo, Service, SyslogMsg } from "../api";
import { MetricChart } from "../components/MetricChart";
import ServiceTable from "../components/ServiceTable";
import { Bar, Card, Empty, StateBadge, stateText } from "../components/ui";
import { SyslogTable } from "./Syslog";

const RANGES = ["1h", "6h", "24h", "7d", "30d", "1y"];

function RangePicker({ value, onChange }: { value: string; onChange: (v: string) => void }) {
  return (
    <div className="flex rounded border border-line overflow-hidden">
      {RANGES.map((r) => (
        <button key={r} onClick={() => onChange(r)}
          className={`px-2 py-1 text-xxs ${value === r ? "bg-accent text-black font-semibold" : "bg-panel2 text-muted hover:text-white"}`}>
          {r}
        </button>
      ))}
    </div>
  );
}

export default function DevicePage() {
  const params = useParams();
  const id = Number(params.id);
  const tab = params["*"] || "overview";
  const nav = useNavigate();
  const qc = useQueryClient();
  const [range, setRange] = useState("24h");

  const { data: me } = useQuery({ queryKey: ["me"], queryFn: () => api<Me>("/auth/me") });
  const { data: device } = useQuery({ queryKey: ["device", id], queryFn: () => api<Device>(`/devices/${id}`), refetchInterval: 30_000 });
  const { data: components = [] } = useQuery({ queryKey: ["components", id], queryFn: () => api<Component[]>(`/devices/${id}/components`), refetchInterval: 60_000 });
  const { data: services = [] } = useQuery({ queryKey: ["services", id], queryFn: () => api<Service[]>(`/devices/${id}/services`), refetchInterval: 30_000 });
  const { data: plugins = [] } = useQuery({ queryKey: ["plugins"], queryFn: () => api<PluginInfo[]>("/plugins") });

  if (!device) return <Empty>Loading…</Empty>;

  const ports = components.filter((c) => c.kind === "port");
  const health = components.filter((c) => ["processor", "mempool", "storage", "sensor"].includes(c.kind));
  const pluginTabs = plugins.flatMap((p) => p.ui_tabs);
  const tabs: [string, string, number?][] = [
    ["overview", "Overview"],
    ["ports", "Ports", ports.length],
    ["health", "Health", health.length],
    ["services", "Services", services.length],
    ...pluginTabs.map((t) => [t.id, t.label] as [string, string]),
    ["syslog", "Syslog"],
    ["events", "Events"],
    ...(me?.role !== "viewer" ? [["settings", "Settings"] as [string, string]] : []),
  ];
  const worst = services.reduce((w, s) => Math.max(w, s.state), 0);

  async function action(kind: "discover" | "poll") {
    await api(`/devices/${id}/${kind}`, { method: "POST" });
    setTimeout(() => qc.invalidateQueries(), 3000);
  }

  return (
    <>
      {/* Observium style device header */}
      <div className="border-b border-line bg-panel/60 px-5 py-4 flex gap-5 items-start">
        <div className={`w-1.5 self-stretch rounded ${["bg-ok", "bg-warn", "bg-crit", "bg-unknown"][device.status]}`} />
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-3">
            <h1 className="text-xl font-semibold truncate">{device.hostname}</h1>
            <StateBadge state={device.status} />
            {device.disabled && <span className="text-xxs px-1.5 rounded bg-line">DISABLED</span>}
          </div>
          <div className="text-xs text-muted mt-1 truncate">{device.sys_descr}</div>
          <div className="flex flex-wrap gap-x-6 gap-y-1 mt-2 text-xs">
            <span><span className="text-muted">IP </span>{device.ip ?? "-"}</span>
            <span><span className="text-muted">Platform </span>{[device.vendor, device.hardware].filter(Boolean).join(" ") || "-"}</span>
            <span><span className="text-muted">OS </span>{[device.os, device.version].filter(Boolean).join(" ") || "-"}</span>
            <span><span className="text-muted">Uptime </span>{fmtUptime(device.uptime)}</span>
            <span><span className="text-muted">Location </span>{device.sys_location ?? "-"}</span>
          </div>
        </div>
        <div className="flex flex-col items-end gap-2">
          {me?.role !== "viewer" && (
            <div className="flex gap-2">
              <button className="btn" onClick={() => action("poll")}>Poll now</button>
              <button className="btn" onClick={() => action("discover")}>Rediscover</button>
            </div>
          )}
          <div className="text-xxs text-muted">polled {fmtAgo(device.last_polled)} · discovered {fmtAgo(device.last_discovered)}</div>
        </div>
      </div>

      <div className="px-5 border-b border-line flex gap-1 bg-panel/30 overflow-x-auto">
        {tabs.map(([key, label, count]) => (
          <button key={key} onClick={() => nav(`/devices/${id}/${key === "overview" ? "" : key}`)}
            className={`px-3 py-2 text-sm border-b-2 whitespace-nowrap ${tab === key ? "border-accent text-white" : "border-transparent text-muted hover:text-white"}`}>
            {label}
            {key === "services" && worst > 0 && <span className={`ml-1 ${stateText(worst)}`}>●</span>}
            {count !== undefined && <span className="ml-1 text-xxs text-muted">{count}</span>}
          </button>
        ))}
        <div className="ml-auto py-1.5"><RangePicker value={range} onChange={setRange} /></div>
      </div>

      <div className="p-5 space-y-4">
        {tab === "overview" && <OverviewTab device={device} components={components} services={services} range={range} />}
        {tab === "ports" && <PortsTab deviceId={id} ports={ports} range={range} />}
        {tab === "health" && <HealthTab deviceId={id} components={health} range={range} />}
        {tab === "services" && <Card><ServiceTable services={services} canAck={me?.role !== "viewer"} /></Card>}
        {tab === "syslog" && <DeviceSyslog deviceId={id} />}
        {tab === "events" && <EventsTab deviceId={id} />}
        {tab === "settings" && <SettingsTab device={device} isAdmin={me?.role === "admin"} />}
        {pluginTabs.filter((t) => t.id === tab).map((t) =>
          t.view === "iframe" && t.url ? (
            <iframe key={t.id} src={t.url.replace("{device_id}", String(id))} className="w-full h-[70vh] card" />
          ) : (
            <Card key={t.id} title={t.label}>
              <div className="p-3">
                {t.id === "latency" ? (
                  <>
                    <MetricChart deviceId={id} range={range} unit=" ms" height={260} area={false}
                      metrics={[{ name: "ping_min", label: "min" }, { name: "ping_avg", label: "avg" }, { name: "ping_max", label: "max" }]} />
                    <MetricChart deviceId={id} range={range} unit="%" height={140} metrics={[{ name: "ping_loss", label: "loss" }]} />
                  </>
                ) : (
                  <MetricChart deviceId={id} range={range} height={260} metrics={t.metrics.map((m) => ({ name: m }))} />
                )}
              </div>
            </Card>
          ),
        )}
      </div>
    </>
  );
}

function OverviewTab({ device, components, services, range }: { device: Device; components: Component[]; services: Service[]; range: string }) {
  const ports = components.filter((c) => c.kind === "port");
  const up = ports.filter((p) => p.values.oper === 1).length;
  const mem = components.find((c) => c.kind === "mempool");
  const storage = components.filter((c) => c.kind === "storage");
  const problems = services.filter((s) => s.state > 0);
  const hasCpu = components.some((c) => c.kind === "processor");

  return (
    <div className="grid grid-cols-1 xl:grid-cols-3 gap-4">
      <div className="space-y-4">
        <Card title="Device">
          <table className="tbl"><tbody>
            {([
              ["System name", device.sys_name], ["Hardware", device.hardware], ["Serial", device.serial],
              ["Operating system", [device.os, device.version].filter(Boolean).join(" ")],
              ["Object ID", device.sys_object_id], ["Contact", device.sys_contact], ["Location", device.sys_location],
              ["SNMP", `v${device.snmp_version} :${device.snmp_port}`],
              ["Poll time", device.poll_duration != null ? `${device.poll_duration.toFixed(2)} s` : null],
            ] as [string, string | null][]).map(([k, v]) => (
              <tr key={k}><td className="text-muted w-36">{k}</td><td className="break-all">{v || "-"}</td></tr>
            ))}
          </tbody></table>
        </Card>
        <Card title="Ports">
          <div className="p-3 flex gap-6 text-sm">
            <div><span className="text-2xl font-semibold">{ports.length}</span> <span className="text-muted">total</span></div>
            <div><span className="text-2xl font-semibold text-ok">{up}</span> <span className="text-muted">up</span></div>
            <div><span className="text-2xl font-semibold text-muted">{ports.length - up}</span> <span className="text-muted">down</span></div>
          </div>
        </Card>
        {(mem || storage.length > 0) && (
          <Card title="Memory & storage">
            <table className="tbl"><tbody>
              {[mem, ...storage].filter(Boolean).map((c) => (
                <tr key={c!.id}><td className="truncate max-w-[10rem]">{c!.name}</td><td><Bar pct={c!.values.pct} /></td>
                  <td className="text-xs text-muted whitespace-nowrap">{fmtBytes(c!.values.used)} / {fmtBytes(c!.values.size)}</td></tr>
              ))}
            </tbody></table>
          </Card>
        )}
      </div>
      <div className="xl:col-span-2 space-y-4">
        <Card title={`Problems (${problems.length})`}>
          {problems.length ? <ServiceTable services={problems} /> : <Empty>No problems on this device</Empty>}
        </Card>
        {hasCpu && (
          <Card title="Processor"><div className="p-3">
            <MetricChart deviceId={device.id} range={range} unit="%" metrics={[{ name: "cpu_util", label: "CPU" }]} />
          </div></Card>
        )}
        {mem && (
          <Card title="Memory"><div className="p-3">
            <MetricChart deviceId={device.id} componentId={mem.id} range={range} unit="%" metrics={[{ name: "used_pct", label: "used" }]} />
          </div></Card>
        )}
        <Card title="Latency"><div className="p-3">
          <MetricChart deviceId={device.id} range={range} unit=" ms" height={160} area={false}
            metrics={[{ name: "ping_avg", label: "avg" }, { name: "ping_max", label: "max" }]} />
        </div></Card>
      </div>
    </div>
  );
}

function PortsTab({ deviceId, ports, range }: { deviceId: number; ports: Component[]; range: string }) {
  const [open, setOpen] = useState<number | null>(null);
  const [filter, setFilter] = useState("");
  const rows = ports.filter((p) => !filter || `${p.name} ${p.descr ?? ""}`.toLowerCase().includes(filter.toLowerCase()));
  if (!ports.length) return <Card><Empty>No ports discovered</Empty></Card>;
  return (
    <Card title={`Ports (${ports.length})`} actions={
      <input className="input text-xs normal-case tracking-normal" placeholder="filter…" value={filter} onChange={(e) => setFilter(e.target.value)} />
    }>
      <table className="tbl">
        <thead><tr><th className="w-6"></th><th>Port</th><th>Description</th><th>Speed</th><th className="text-right">In</th><th className="text-right">Out</th><th>Utilization</th><th>MAC</th></tr></thead>
        <tbody>
          {rows.map((p) => {
            const v = p.values;
            const color = v.admin === 2 ? "bg-gray-500" : v.oper === 1 ? "bg-ok" : "bg-crit";
            return (
              <Fragment key={p.id}>
                <tr className="cursor-pointer" onClick={() => setOpen(open === p.id ? null : p.id)}>
                  <td><span className={`inline-block w-2.5 h-2.5 rounded-full ${color}`} title={v.admin === 2 ? "admin down" : v.oper === 1 ? "up" : "down"} /></td>
                  <td className="font-medium whitespace-nowrap">{p.name}</td>
                  <td className="text-gray-300">{p.descr ?? ""}</td>
                  <td className="text-xs whitespace-nowrap">{p.attrs.speed ? fmtBps(p.attrs.speed) : "-"}</td>
                  <td className="text-right tabular-nums text-xs">{fmtBps(v.in_bps)}</td>
                  <td className="text-right tabular-nums text-xs">{fmtBps(v.out_bps)}</td>
                  <td>{v.util != null ? <Bar pct={v.util} /> : <span className="text-muted">-</span>}</td>
                  <td className="text-xs text-muted font-mono">{p.attrs.mac ?? ""}</td>
                </tr>
                {open === p.id && (
                  <tr><td colSpan={8} className="bg-bg">
                    <div className="grid md:grid-cols-2 gap-4 p-2">
                      <div>
                        <div className="text-xxs uppercase text-muted mb-1">Traffic</div>
                        <MetricChart deviceId={deviceId} componentId={p.id} range={range} format={fmtBps}
                          metrics={[{ name: "in_bps", label: "in" }, { name: "out_bps", label: "out" }]} />
                      </div>
                      <div>
                        <div className="text-xxs uppercase text-muted mb-1">Errors / discards (per second)</div>
                        <MetricChart deviceId={deviceId} componentId={p.id} range={range} area={false} format={(x) => x.toFixed(2)}
                          metrics={[{ name: "in_errors" }, { name: "out_errors" }, { name: "in_discards" }, { name: "out_discards" }]} />
                      </div>
                    </div>
                  </td></tr>
                )}
              </Fragment>
            );
          })}
        </tbody>
      </table>
    </Card>
  );
}

function HealthTab({ deviceId, components, range }: { deviceId: number; components: Component[]; range: string }) {
  const [open, setOpen] = useState<number | null>(null);
  if (!components.length) return <Card><Empty>No health components discovered</Empty></Card>;
  const groups: [string, string][] = [["processor", "Processors"], ["mempool", "Memory"], ["storage", "Storage"], ["sensor", "Sensors"]];
  return (
    <>
      {groups.map(([kind, title]) => {
        const items = components.filter((c) => c.kind === kind);
        if (!items.length) return null;
        return (
          <Card key={kind} title={title}>
            <table className="tbl"><tbody>
              {items.map((c) => (
                <Fragment key={c.id}>
                  <tr className="cursor-pointer" onClick={() => setOpen(open === c.id ? null : c.id)}>
                    <td className="w-64">{c.name}</td>
                    <td><Bar pct={kind === "processor" ? c.values.load : c.values.pct} /></td>
                    <td className="text-xs text-muted">{kind !== "processor" && `${fmtBytes(c.values.used)} / ${fmtBytes(c.values.size)}`}</td>
                  </tr>
                  {open === c.id && (
                    <tr><td colSpan={3} className="bg-bg p-2">
                      <MetricChart deviceId={deviceId} componentId={c.id} range={range} unit="%"
                        metrics={[{ name: kind === "processor" ? "load" : "used_pct", label: kind === "processor" ? "load" : "used" }]} />
                    </td></tr>
                  )}
                </Fragment>
              ))}
            </tbody></table>
          </Card>
        );
      })}
    </>
  );
}

function DeviceSyslog({ deviceId }: { deviceId: number }) {
  const { data = [] } = useQuery({
    queryKey: ["syslog", deviceId],
    queryFn: () => api<SyslogMsg[]>(`/syslog?device_id=${deviceId}&limit=300`),
    refetchInterval: 15_000,
  });
  return <Card title="Syslog">{data.length ? <SyslogTable rows={data} /> : <Empty>No syslog messages from this device</Empty>}</Card>;
}

function EventsTab({ deviceId }: { deviceId: number }) {
  const { data = [] } = useQuery({
    queryKey: ["history", deviceId],
    queryFn: () => api<{ time: string; service: string; old_state: number; new_state: number; output: string }[]>(`/devices/${deviceId}/history`),
  });
  return (
    <Card title="State changes">
      {!data.length ? <Empty>No events yet</Empty> : (
        <table className="tbl">
          <thead><tr><th>Time</th><th>Service</th><th>From</th><th>To</th><th>Output</th></tr></thead>
          <tbody>
            {data.map((e, i) => (
              <tr key={i}>
                <td className="text-xs whitespace-nowrap">{new Date(e.time).toLocaleString()}</td>
                <td>{e.service}</td>
                <td><StateBadge state={e.old_state} small /></td>
                <td><StateBadge state={e.new_state} small /></td>
                <td className="text-gray-300">{e.output}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </Card>
  );
}

function SettingsTab({ device, isAdmin }: { device: Device; isAdmin: boolean }) {
  const qc = useQueryClient();
  const nav = useNavigate();
  const [community, setCommunity] = useState("");
  const [ip, setIp] = useState(device.ip ?? "");
  const [msg, setMsg] = useState("");

  async function save() {
    const body: any = { ip: ip || null };
    if (community) body.snmp_community = community;
    await api(`/devices/${device.id}`, { method: "PATCH", body });
    setMsg("Saved");
    qc.invalidateQueries({ queryKey: ["device", device.id] });
  }
  async function toggle() {
    await api(`/devices/${device.id}`, { method: "PATCH", body: { disabled: !device.disabled } });
    qc.invalidateQueries({ queryKey: ["device", device.id] });
  }
  async function remove() {
    if (!confirm(`Delete ${device.hostname} and all its data?`)) return;
    await api(`/devices/${device.id}`, { method: "DELETE" });
    nav("/devices");
  }

  return (
    <Card title="Device settings">
      <div className="p-4 grid gap-3 max-w-md">
        <div><label className="label">IP address</label><input className="input w-full" value={ip} onChange={(e) => setIp(e.target.value)} /></div>
        <div><label className="label">New SNMP community (leave empty to keep)</label>
          <input className="input w-full" type="password" value={community} onChange={(e) => setCommunity(e.target.value)} /></div>
        <div className="flex gap-2 items-center">
          <button className="btn btn-primary" onClick={save}>Save</button>
          <button className="btn" onClick={toggle}>{device.disabled ? "Enable polling" : "Disable polling"}</button>
          {isAdmin && <button className="btn hover:border-crit text-crit" onClick={remove}>Delete device</button>}
          {msg && <span className="text-ok text-xs">{msg}</span>}
        </div>
        <div className="text-xs text-muted">Thresholds are managed centrally in <Link className="text-accent" to="/setup/rules">Threshold rules</Link>.</div>
      </div>
    </Card>
  );
}
