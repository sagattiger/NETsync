import { BackLink } from "../components/Tabs";
import { Fragment, ReactNode, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api, Component, Device, fmtAgo, fmtUptime, Me, PluginInfo, prefs, Service, SyslogMsg } from "../api";
import { Icon } from "../components/Icon";
import { MetricChart } from "../components/MetricChart";
import ServiceTable from "../components/ServiceTable";
import { osLabel, VendorLogo, VirtBadge } from "../components/VendorLogo";
import { Bar, Card, Empty, Segmented, StateBadge, StateDot, stateText } from "../components/ui";
import { SyslogTable } from "./Syslog";
import EventsTab from "./device/EventsTab";
import NotesTab from "./device/NotesTab";
import NetstatTab from "./device/NetstatTab";
import HealthTab, { cpuLine, HealthSub } from "./device/HealthTab";
import GraphsTab from "./device/GraphsTab";
import PortsTab from "./device/PortsTab";
import { TerminalView } from "../components/TerminalView";
import { MEMORY_COLORS } from "./device/charts";
import { FORMATS } from "../presets";

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
  const [tab, subPath] = (params["*"] || "overview").split("/");
  const healthSub = (subPath || "overview") as HealthSub;
  const nav = useNavigate();
  const qc = useQueryClient();
  const [range, setRange] = useState(() => prefs.get().default_range ?? "24h");
  const [busy, setBusy] = useState<null | "discover" | "poll">(null);
  const [actionMsg, setActionMsg] = useState<{ ok: boolean; text: string } | null>(null);

  const { data: me } = useQuery({ queryKey: ["me"], queryFn: () => api<Me>("/auth/me") });
  const { data: device } = useQuery({ queryKey: ["device", id], queryFn: () => api<Device>(`/devices/${id}`), refetchInterval: 30_000 });
  const { data: components = [] } = useQuery({ queryKey: ["components", id], queryFn: () => api<Component[]>(`/devices/${id}/components`), refetchInterval: 60_000 });
  const { data: services = [] } = useQuery({ queryKey: ["services", id], queryFn: () => api<Service[]>(`/devices/${id}/services`), refetchInterval: 30_000 });
  const { data: plugins = [] } = useQuery({ queryKey: ["plugins"], queryFn: () => api<PluginInfo[]>("/plugins") });
  const { data: termAccess } = useQuery({ queryKey: ["terminal-access", id], queryFn: () => api<{ level: string; available: boolean }>(`/terminal/access/${id}`), staleTime: 60_000, retry: false });
  const canTerminal = !!termAccess?.available && termAccess.level !== "none";

  if (!device) return <Empty>Loading…</Empty>;

  const ports = components.filter((c) => c.kind === "port");
  const health = components.filter((c) => ["processor", "mempool", "storage", "sensor", "disk"].includes(c.kind));
  const netstat = components.find((c) => c.kind === "netstat");
  const pluginTabs = plugins.flatMap((p) => p.ui_tabs);
  const canEdit = me?.role !== "viewer";
  const tabs: [string, string, number?][] = [
    ["overview", "Overview"],
    ["ports", "Ports", ports.length],
    ["health", "Health", health.length],
    ["graphs", "Graphs"],
    ["services", "Services", services.length],
    ...(netstat ? [["netstat", "Network stack"] as [string, string]] : []),
    ...pluginTabs.map((t) => [t.id, t.label] as [string, string]),
    ...(canTerminal ? [["terminal", "Terminal"] as [string, string]] : []),
    ["events", "Events"],
    ["notes", "Notes"],
    ["syslog", "Syslog"],
    ...(canEdit ? [["settings", "Settings"] as [string, string]] : []),
  ];
  const worst = services.reduce((w, s) => Math.max(w, s.state), 0);
  const showRange = ["overview", "ports", "health", "graphs", "netstat", ...pluginTabs.map((t) => t.id)].includes(tab);

  /** Ask the worker to rediscover / poll, then wait until it has finished before refreshing the page. */
  async function action(kind: "discover" | "poll") {
    const field = kind === "discover" ? "last_discovered" : "last_polled";
    const before = device?.[field] ?? null;
    setBusy(kind);
    setActionMsg(null);
    try {
      await api(`/devices/${id}/${kind}`, { method: "POST" });
      const deadline = Date.now() + 120_000;
      let done = false;
      while (Date.now() < deadline) {
        await new Promise((r) => setTimeout(r, 2000));
        const d = await api<Device>(`/devices/${id}`);
        if (d[field] && d[field] !== before) { done = true; break; }
      }
      await qc.invalidateQueries();
      setActionMsg(done
        ? { ok: true, text: kind === "discover" ? "Rediscovery finished" : "Poll finished" }
        : { ok: false, text: kind === "discover"
          ? "Rediscovery didn't finish within 2 minutes: the device may be unreachable (see its status)"
          : "The poll didn't finish within 2 minutes" });
    } catch (e) {
      setActionMsg({ ok: false, text: (e as Error).message });
    } finally {
      setBusy(null);
    }
  }

  return (
    <>
      {/* device header */}
      <div className="px-4 sm:px-6 pt-5 pb-4 border-b border-line">
        <div className="flex flex-col md:flex-row md:items-start gap-4">
          <div className="flex items-start gap-4 flex-1 min-w-0">
            <VendorLogo device={device} size={56} />
            <div className="min-w-0 flex-1">
              <BackLink to="/devices" label="Devices" />
              <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
                <h1 className="text-xl font-semibold text-strong tracking-tight truncate">{device.hostname}</h1>
                <StateBadge state={device.status} />
                <VirtBadge virtualization={device.virtualization} />
                {device.disabled && <span className="text-xxs px-2 py-0.5 rounded-pill bg-chip text-fg2">Disabled</span>}
              </div>
              <div className="text-xs text-muted mt-1 line-clamp-2 md:line-clamp-1">{device.sys_descr}</div>
            </div>
          </div>
          {canEdit && (
            <div className="flex gap-2 shrink-0">
              {actionMsg && (
                <span role="status" className={`self-center text-xs ${actionMsg.ok ? "text-ok" : "text-warn"} max-w-[16rem]`}>{actionMsg.text}</span>
              )}
              <button className="btn" disabled={!!busy} onClick={() => action("poll")}>
                <Icon name="play" className="w-3.5 h-3.5" /> {busy === "poll" ? "Polling…" : "Poll now"}
              </button>
              <button className="btn" disabled={!!busy} onClick={() => action("discover")}>
                <Icon name="refresh" className={`w-3.5 h-3.5 ${busy === "discover" ? "animate-spin" : ""}`} /> {busy === "discover" ? "Rediscovering…" : "Rediscover"}
              </button>
            </div>
          )}
        </div>
        <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-x-6 gap-y-3 mt-5">
          <Meta label="IP address">{device.ip}</Meta>
          <Meta label="Platform">{[device.vendor, device.hardware].filter(Boolean).join(" ")}</Meta>
          <Meta label="Operating system">{osLabel(device.os, device.version)}</Meta>
          <Meta label="Uptime">{fmtUptime(device.uptime)}</Meta>
          <Meta label="Location">{device.sys_location}</Meta>
          <Meta label="Last polled">{fmtAgo(device.last_polled)}<span className="text-muted text-xs"> · discovered {fmtAgo(device.last_discovered)}</span></Meta>
        </div>
      </div>

      {/* tabs */}
      <div className="sticky top-14 z-20 bg-gap/95 backdrop-blur border-b border-line px-4 sm:px-6 flex items-center gap-4">
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
        {tab === "health" && (
          <HealthTab deviceId={id} components={components} services={services} range={range} sub={healthSub}
            onSub={(sub) => nav(`/devices/${id}/health${sub === "overview" ? "" : `/${sub}`}`)} />
        )}
        {tab === "graphs" && <GraphsTab deviceId={id} range={range} />}
        {tab === "services" && <Card><ServiceTable services={services} canAck={canEdit} /></Card>}
        {tab === "syslog" && <DeviceSyslog deviceId={id} />}
        {tab === "terminal" && canTerminal && <TerminalView deviceId={id} className="h-[70vh] min-h-[22rem]" />}
        {tab === "events" && <EventsTab deviceId={id} />}
        {tab === "notes" && <NotesTab deviceId={id} canEdit={canEdit} />}
        {tab === "netstat" && <NetstatTab deviceId={id} component={netstat} range={range} />}
        {tab === "settings" && <SettingsTab device={device} isAdmin={me?.role === "admin"} />}
        {pluginTabs.filter((t) => t.id === tab).map((t) =>
          t.view === "iframe" && t.url ? (
            <iframe key={t.id} src={t.url.replace("{device_id}", String(id))} className="w-full h-[70vh] card" />
          ) : t.id === "latency" ? (
            <Fragment key={t.id}>
              <Card title="Average" flush={false}>
                <MetricChart deviceId={id} range={range} format={FORMATS.ms} height={200} area={false}
                  metrics={[{ name: "ping_avg", label: "avg" }]} />
              </Card>
              <Card title="Aggregate · min / avg / max" flush={false}>
                <MetricChart deviceId={id} range={range} format={FORMATS.ms} height={260} style="range"
                  metrics={[{ name: "ping_avg", label: "avg" }]} band={{ min: "ping_min", max: "ping_max" }} />
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
  const { data: problems = [] } = useQuery({
    queryKey: ["problems", "device", device.id],
    queryFn: () => api<Service[]>(`/problems?device_id=${device.id}`),
    refetchInterval: prefs.refreshMs(30_000),
  });
  const hasCpu = components.some((c) => c.kind === "processor");
  const stats = components.find((c) => c.kind === "system_stats");
  const memTotal = stats?.values.mem_total as number | undefined;
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
              ["System name", device.sys_name], ["Hardware", device.hardware], ["Processor", cpuLine(components)],
              ["Kernel", device.kernel], ["Serial", device.serial],
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
        <Card title={`Problems · ${problems.filter((p) => !p.resolved).length}`}>
          {problems.length ? <ServiceTable services={problems} problems /> : <Empty>No problems on this device</Empty>}
        </Card>
        {hasCpu && (
          <Card title={<>Processor <span className="font-normal text-muted ml-1">{cpuLine(components)}</span></>} flush={false}>
            <MetricChart deviceId={device.id} range={range} unit="%" metrics={[{ name: "cpu_util", label: "CPU" }]} />
          </Card>
        )}
        {memTotal ? (
          <Card title="Memory" flush={false}>
            <MetricChart deviceId={device.id} range={range} format={FORMATS.bytes} stack rulerMetric="mem_total" colors={MEMORY_COLORS()}
              metrics={[{ name: "mem_used", label: "used" }, { name: "mem_buffers", label: "buffers" },
                { name: "mem_cached", label: "cached" }, { name: "mem_free", label: "free" }]} />
          </Card>
        ) : mem && (
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
