import { Fragment, ReactNode, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api, Component, Device, fmtAgo, fmtBps, fmtBytes, fmtUptime, Me, PluginInfo, prefs, Service, SyslogMsg } from "../api";
import { Icon } from "../components/Icon";
import { MetricChart } from "../components/MetricChart";
import ServiceTable from "../components/ServiceTable";
import { osLabel, VendorLogo, VirtBadge } from "../components/VendorLogo";
import { Bar, Card, Empty, hideLg, hideMd, hideSm, Segmented, StateBadge, StateDot, stateText } from "../components/ui";
import { SyslogTable } from "./Syslog";
import EventsTab from "./device/EventsTab";
import NotesTab from "./device/NotesTab";
import NetstatTab from "./device/NetstatTab";
import { AddToDashboard } from "../components/AddToDashboard";

const RANGES: [string, string][] = [["1h", "1h"], ["6h", "6h"], ["24h", "24h"], ["7d", "7d"], ["30d", "30d"], ["1y", "1y"]];

function Meta({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="min-w-0">
      <div className="text-xxs text-muted">{label}</div>
      <div className="text-sm text-fg truncate">{children || "-"}</div>
    </div>
  );
}

export default function DevicePage() {
  const params = useParams();
  const id = Number(params.id);
  const tab = params["*"] || "overview";
  const nav = useNavigate();
  const qc = useQueryClient();
  const [range, setRange] = useState(() => prefs.get().default_range ?? "24h");

  const { data: me } = useQuery({ queryKey: ["me"], queryFn: () => api<Me>("/auth/me") });
  const { data: device } = useQuery({ queryKey: ["device", id], queryFn: () => api<Device>(`/devices/${id}`), refetchInterval: 30_000 });
  const { data: components = [] } = useQuery({ queryKey: ["components", id], queryFn: () => api<Component[]>(`/devices/${id}/components`), refetchInterval: 60_000 });
  const { data: services = [] } = useQuery({ queryKey: ["services", id], queryFn: () => api<Service[]>(`/devices/${id}/services`), refetchInterval: 30_000 });
  const { data: plugins = [] } = useQuery({ queryKey: ["plugins"], queryFn: () => api<PluginInfo[]>("/plugins") });

  if (!device) return <Empty>Loading…</Empty>;

  const ports = components.filter((c) => c.kind === "port");
  const health = components.filter((c) => ["processor", "mempool", "storage", "sensor"].includes(c.kind));
  const netstat = components.find((c) => c.kind === "netstat");
  const pluginTabs = plugins.flatMap((p) => p.ui_tabs);
  const canEdit = me?.role !== "viewer";
  const tabs: [string, string, number?][] = [
    ["overview", "Overview"],
    ["ports", "Ports", ports.length],
    ["health", "Health", health.length],
    ["services", "Services", services.length],
    ...(netstat ? [["netstat", "Network stack"] as [string, string]] : []),
    ...pluginTabs.map((t) => [t.id, t.label] as [string, string]),
    ["events", "Events"],
    ["notes", "Notes"],
    ["syslog", "Syslog"],
    ...(canEdit ? [["settings", "Settings"] as [string, string]] : []),
  ];
  const worst = services.reduce((w, s) => Math.max(w, s.state), 0);
  const showRange = ["overview", "ports", "health", "netstat", ...pluginTabs.map((t) => t.id)].includes(tab);

  async function action(kind: "discover" | "poll") {
    await api(`/devices/${id}/${kind}`, { method: "POST" });
    setTimeout(() => qc.invalidateQueries(), 3000);
  }

  return (
    <>
      {/* device header */}
      <div className="px-4 sm:px-6 pt-5 pb-4 border-b border-line">
        <div className="flex flex-col md:flex-row md:items-start gap-4">
          <div className="flex items-start gap-4 flex-1 min-w-0">
            <VendorLogo device={device} size={56} />
            <div className="min-w-0 flex-1">
              <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
                <h1 className="text-xl font-semibold text-strong tracking-tight truncate">{device.hostname}</h1>
                <StateBadge state={device.status} />
                <VirtBadge virtualization={device.virtualization} />
                {device.disabled && <span className="text-xxs px-2 py-0.5 rounded-full bg-chip text-fg2">Disabled</span>}
              </div>
              <div className="text-xs text-muted mt-1 line-clamp-2 md:line-clamp-1">{device.sys_descr}</div>
            </div>
          </div>
          {canEdit && (
            <div className="flex gap-2 shrink-0">
              <button className="btn" onClick={() => action("poll")}><Icon name="play" className="w-3.5 h-3.5" /> Poll now</button>
              <button className="btn" onClick={() => action("discover")}><Icon name="refresh" className="w-3.5 h-3.5" /> Rediscover</button>
            </div>
          )}
        </div>
        <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-x-6 gap-y-3 mt-5">
          <Meta label="IP address">{device.ip}</Meta>
          <Meta label="Platform">{[device.vendor, device.hardware].filter(Boolean).join(" ")}</Meta>
          <Meta label="Operating system">{osLabel(device.os, device.version)}</Meta>
          <Meta label="Uptime">{fmtUptime(device.uptime)}</Meta>
          <Meta label="Location">{device.sys_location}</Meta>
          <Meta label="Last polled">{fmtAgo(device.last_polled)}</Meta>
        </div>
      </div>

      {/* tabs */}
      <div className="sticky top-14 z-20 bg-bg/95 backdrop-blur border-b border-line px-4 sm:px-6 flex items-center gap-4">
        <div className="flex gap-1 overflow-x-auto -mb-px flex-1 min-w-0">
          {tabs.map(([key, label, count]) => (
            <button key={key} onClick={() => nav(`/devices/${id}/${key === "overview" ? "" : key}`)}
              className={`px-3 py-3 text-sm border-b-2 whitespace-nowrap transition-colors ${tab === key ? "border-accent text-strong font-medium" : "border-transparent text-muted hover:text-fg"}`}>
              {label}
              {key === "services" && worst > 0 && <StateDot state={worst} className="ml-1.5 align-middle" />}
              {count !== undefined && <span className="ml-1.5 text-xxs text-muted">{count}</span>}
            </button>
          ))}
        </div>
        {showRange && <div className="hidden sm:block py-2"><Segmented value={range} onChange={setRange} options={RANGES} /></div>}
      </div>
      {showRange && <div className="sm:hidden px-4 pt-3"><Segmented value={range} onChange={setRange} options={RANGES} /></div>}

      <div className="px-4 sm:px-6 py-5 space-y-4">
        {tab === "overview" && <OverviewTab device={device} components={components} services={services} range={range} />}
        {tab === "ports" && <PortsTab deviceId={id} ports={ports} range={range} />}
        {tab === "health" && <HealthTab deviceId={id} components={health} range={range} />}
        {tab === "services" && <Card><ServiceTable services={services} canAck={canEdit} /></Card>}
        {tab === "syslog" && <DeviceSyslog deviceId={id} />}
        {tab === "events" && <EventsTab deviceId={id} />}
        {tab === "notes" && <NotesTab deviceId={id} canEdit={canEdit} />}
        {tab === "netstat" && <NetstatTab deviceId={id} component={netstat} range={range} />}
        {tab === "settings" && <SettingsTab device={device} isAdmin={me?.role === "admin"} />}
        {pluginTabs.filter((t) => t.id === tab).map((t) =>
          t.view === "iframe" && t.url ? (
            <iframe key={t.id} src={t.url.replace("{device_id}", String(id))} className="w-full h-[70vh] card" />
          ) : t.id === "latency" ? (
            <Fragment key={t.id}>
              <Card title="Round-trip time" flush={false}>
                <MetricChart deviceId={id} range={range} unit=" ms" height={260} area={false}
                  metrics={[{ name: "ping_avg", label: "avg" }, { name: "ping_min", label: "min" }, { name: "ping_max", label: "max" }]} />
              </Card>
              <Card title="Packet loss" flush={false}>
                <MetricChart deviceId={id} range={range} unit="%" height={150} metrics={[{ name: "ping_loss", label: "loss" }]} />
              </Card>
            </Fragment>
          ) : (
            <Card key={t.id} title={t.label} flush={false}>
              <MetricChart deviceId={id} range={range} height={260} metrics={t.metrics.map((m) => ({ name: m }))} />
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
  const counts = [0, 1, 2, 3].map((st) => services.filter((s) => s.state === st).length);

  return (
    <div className="grid grid-cols-1 xl:grid-cols-3 gap-4">
      <div className="space-y-4">
        <Card title="Summary" flush={false}>
          <div className="grid grid-cols-2 gap-4">
            <div>
              <div className="text-xxs text-muted">Services</div>
              <div className="flex items-baseline gap-3 mt-1">
                {counts.map((n, st) => n > 0 && (
                  <span key={st} className={`text-lg font-semibold tabular-nums ${stateText(st)}`}>{n}</span>
                ))}
              </div>
            </div>
            <div>
              <div className="text-xxs text-muted">Ports up</div>
              <div className="text-lg font-semibold text-strong tabular-nums mt-1">{up}<span className="text-muted font-normal text-sm"> / {ports.length}</span></div>
            </div>
          </div>
        </Card>
        <Card title="Device">
          <table className="tbl"><tbody>
            {([
              ["System name", device.sys_name], ["Hardware", device.hardware], ["Kernel", device.kernel], ["Serial", device.serial],
              ["Contact", device.sys_contact], ["Object ID", device.sys_object_id],
              ["SNMP", `v${device.snmp_version} · port ${device.snmp_port}`],
              ["Poll time", device.poll_duration != null ? `${device.poll_duration.toFixed(2)} s` : null],
            ] as [string, string | null][]).map(([k, v]) => (
              <tr key={k}><td className="text-muted w-32 whitespace-nowrap">{k}</td><td className="break-all text-fg">{v || "-"}</td></tr>
            ))}
          </tbody></table>
        </Card>
        {(mem || storage.length > 0) && (
          <Card title="Memory & storage">
            <table className="tbl"><tbody>
              {[mem, ...storage].filter(Boolean).map((c) => (
                <tr key={c!.id}>
                  <td className="max-w-[9rem] truncate text-fg" title={c!.name}>{c!.name}</td>
                  <td><Bar pct={c!.values.pct} /></td>
                </tr>
              ))}
            </tbody></table>
          </Card>
        )}
      </div>
      <div className="xl:col-span-2 space-y-4">
        <Card title={`Problems · ${problems.length}`}>
          {problems.length ? <ServiceTable services={problems} /> : <Empty>No problems on this device</Empty>}
        </Card>
        {hasCpu && (
          <Card title="Processor" flush={false}>
            <MetricChart deviceId={device.id} range={range} unit="%" metrics={[{ name: "cpu_util", label: "CPU" }]} />
          </Card>
        )}
        {mem && (
          <Card title="Memory" flush={false}>
            <MetricChart deviceId={device.id} componentId={mem.id} range={range} unit="%" metrics={[{ name: "used_pct", label: "used" }]} />
          </Card>
        )}
        <Card title="Latency" flush={false}>
          <MetricChart deviceId={device.id} range={range} unit=" ms" height={170} area={false}
            metrics={[{ name: "ping_avg", label: "avg" }, { name: "ping_max", label: "max" }]} />
        </Card>
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
    <Card title={`Ports · ${ports.length}`} actions={
      <input className="input py-1 text-xs w-36 sm:w-48" placeholder="Filter…" value={filter} onChange={(e) => setFilter(e.target.value)} />
    }>
      <table className="tbl">
        <thead><tr>
          <th>Port</th><th className={hideMd}>Description</th><th className={hideLg}>Speed</th>
          <th className="text-right">In</th><th className="text-right">Out</th><th className={hideSm}>Utilization</th><th className={hideLg}>MAC</th>
        </tr></thead>
        <tbody>
          {rows.map((p) => {
            const v = p.values;
            const status = v.admin === 2 ? 3 : v.oper === 1 ? 0 : 2;
            return (
              <Fragment key={p.id}>
                <tr className="cursor-pointer" onClick={() => setOpen(open === p.id ? null : p.id)}>
                  <td className="whitespace-nowrap">
                    <div className="flex items-center gap-2.5">
                      <span className={`w-2 h-2 rounded-full ${v.admin === 2 ? "bg-faint" : status === 0 ? "bg-ok" : "bg-crit"}`}
                        title={v.admin === 2 ? "admin down" : status === 0 ? "up" : "down"} />
                      <span className="font-medium text-strong">{p.name}</span>
                      <Icon name="chevron" className={`w-3.5 h-3.5 text-muted transition-transform ${open === p.id ? "rotate-90" : ""}`} />
                    </div>
                    {p.descr && <div className="md:hidden text-xs text-muted mt-0.5 pl-[18px]">{p.descr}</div>}
                  </td>
                  <td className={`text-fg2 ${hideMd}`}>{p.descr ?? ""}</td>
                  <td className={`text-xs whitespace-nowrap text-fg2 ${hideLg}`}>{p.attrs.speed ? fmtBps(p.attrs.speed) : "-"}</td>
                  <td className="text-right tabular-nums text-xs whitespace-nowrap">{fmtBps(v.in_bps)}</td>
                  <td className="text-right tabular-nums text-xs whitespace-nowrap">{fmtBps(v.out_bps)}</td>
                  <td className={hideSm}>{v.util != null ? <Bar pct={v.util} /> : <span className="text-muted">-</span>}</td>
                  <td className={`text-xs text-muted font-mono ${hideLg}`}>{p.attrs.mac ?? ""}</td>
                </tr>
                {open === p.id && (
                  <tr><td colSpan={7} className="bg-inset/40">
                    <div className="flex justify-end -mb-2">
                      <AddToDashboard deviceId={deviceId} preset="port_traffic" componentId={p.id} />
                    </div>
                    <div className="grid lg:grid-cols-2 gap-6 py-2">
                      <div>
                        <div className="text-xs text-muted mb-1">Traffic</div>
                        <MetricChart deviceId={deviceId} componentId={p.id} range={range} format={fmtBps}
                          metrics={[{ name: "in_bps", label: "in" }, { name: "out_bps", label: "out" }]} />
                      </div>
                      <div>
                        <div className="text-xs text-muted mb-1">Errors & discards per second</div>
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
                    <td className="text-strong font-medium">
                      <div className="flex items-center gap-2">
                        <Icon name="chevron" className={`w-3.5 h-3.5 text-muted transition-transform ${open === c.id ? "rotate-90" : ""}`} />
                        <span className="truncate max-w-[14rem]" title={c.name}>{c.name}</span>
                      </div>
                    </td>
                    <td><Bar pct={kind === "processor" ? c.values.load : c.values.pct} /></td>
                    <td className={`text-xs text-muted text-right whitespace-nowrap ${hideSm}`}>
                      {kind !== "processor" && `${fmtBytes(c.values.used)} of ${fmtBytes(c.values.size)}`}
                    </td>
                  </tr>
                  {open === c.id && (
                    <tr><td colSpan={3} className="bg-inset/40">
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
  return <Card title="Syslog">{data.length ? <SyslogTable rows={data} /> : <Empty>No syslog messages from this device yet</Empty>}</Card>;
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
    <Card title="Device settings" flush={false}>
      <div className="grid gap-4 max-w-md">
        <div><label className="label">IP address</label><input className="input w-full" value={ip} onChange={(e) => setIp(e.target.value)} /></div>
        <div><label className="label">New SNMP community (leave empty to keep the current one)</label>
          <input className="input w-full" type="password" value={community} onChange={(e) => setCommunity(e.target.value)} /></div>
        <div className="flex flex-wrap gap-2 items-center">
          <button className="btn btn-primary" onClick={save}>Save</button>
          <button className="btn" onClick={toggle}>{device.disabled ? "Enable polling" : "Disable polling"}</button>
          {isAdmin && <button className="btn text-crit hover:bg-crit/10 border-crit/40" onClick={remove}>Delete device</button>}
          {msg && <span className="text-ok text-xs">{msg}</span>}
        </div>
        <div className="text-xs text-muted">Thresholds are managed centrally in <Link className="link" to="/setup/rules">Threshold rules</Link>.</div>
      </div>
    </Card>
  );
}
