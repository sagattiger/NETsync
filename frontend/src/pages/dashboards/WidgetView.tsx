import { createContext, useContext } from "react";
import { Link } from "react-router-dom";
import { useQueries, useQuery } from "@tanstack/react-query";
import { api, Component, Device, fmtUptime, Heartbeat, logoSrc, prefs, Probe, RingItem, Series, Service, Widget } from "../../api";
import { daysTone, fmtMs, fmtPct, HeartbeatBar, StatusPill } from "../probes/shared";
import { lastValue, MetricChart, MetricDef, seriesQuery } from "../../components/MetricChart";
import { Donut, Gauge, HBars, Kpi, nsVar, Ring, SERIES_VARS, STATE_VARS, STATE_WORDS } from "../../components/Charts";
import ServiceTable from "../../components/ServiceTable";
import { VendorLogo } from "../../components/VendorLogo";
import { Empty, StateBadge, stateText } from "../../components/ui";
import { Preset, usePresets } from "../../presets";

export function useDevices() {
  return useQuery({ queryKey: ["devices"], queryFn: () => api<Device[]>("/devices"), refetchInterval: prefs.refreshMs(30_000) }).data ?? [];
}

export function useComponents(deviceId: number | null, kind?: string | null) {
  return useQuery({
    queryKey: ["components", deviceId],
    queryFn: () => api<Component[]>(`/devices/${deviceId}/components`),
    enabled: !!deviceId,
  }).data?.filter((c) => !kind || c.kind === kind) ?? [];
}

export function useProbes() {
  return useQuery({ queryKey: ["probes"], queryFn: () => api<Probe[]>("/probes"), refetchInterval: prefs.refreshMs(30_000) }).data ?? [];
}

/** Devices and probes of the dashboard being shown (donut "all" counts only these). Unset = everything visible. */
export const DashboardScope = createContext<{ deviceIds: number[]; probeIds: number[] } | null>(null);

/** Devices and probes a list of widgets reads. */
export function widgetScope(widgets: Widget[]): { deviceIds: number[]; probeIds: number[] } {
  const d = new Set<number>(), p = new Set<number>();
  for (const w of widgets) {
    if (w.probe_id) p.add(w.probe_id); else if (w.device_id) d.add(w.device_id);
    for (const it of w.items ?? []) { if (it.probe_id) p.add(it.probe_id); else if (it.device_id) d.add(it.device_id); }
    for (const id of w.probe_ids ?? []) p.add(id);
  }
  return { deviceIds: [...d], probeIds: [...p] };
}

/** Worst state of a device from its service counts (CRIT > WARN > UNKNOWN > OK). */
export function deviceWorst(d: Device | undefined): number | null {
  if (!d) return null;
  return d.services_crit ? 2 : d.services_warn ? 1 : d.services_unknown ? 3 : d.status ?? 0;
}

/** The series a kpi/gauge/ring/bars widget reads: by key (label or name), else the first of the preset. */
export function pickMetric(preset: Preset | undefined, key?: string | null): MetricDef | undefined {
  return preset?.metrics.find((m) => m.label === key || m.name === key) ?? preset?.metrics[0];
}

/** Title shown when the widget has no custom title. */
export function autoTitle(w: Widget, devices: Device[], components: Component[],
  presetById: (id: string | null | undefined) => Preset | undefined, probes: Probe[] = []): string {
  const host = devices.find((d) => d.id === w.device_id)?.hostname;
  const probe = probes.find((p) => p.id === w.probe_id);
  if (w.type === "uptime") return probe?.name ?? "Uptime";
  if (w.type === "kpi" || w.type === "gauge") {
    if (w.stat === "uptime") return probe ? `Uptime · ${probe.name}` : "Uptime";
    const preset = presetById(w.preset);
    const comp = components.find((c) => c.id === w.component_id);
    const metric = preset && preset.metrics.length > 1 ? pickMetric(preset, w.metric)?.label : null;
    return [probe?.name ?? host, preset?.label, comp?.name, metric].filter(Boolean).join(" · ") || "Value";
  }
  if (w.type === "rings") return "Health";
  if (w.type === "donut") return `${w.device_id ? `${host} · ` : ""}${w.count === "problems" ? "Problems" : "Services"}`;
  if (w.type === "bars") return [host, presetById(w.preset)?.label].filter(Boolean).join(" · ") || "Top";
  if (w.type === "graph") {
    const preset = presetById(w.preset);
    if (preset?.source === "probe") {
      const probe = probes.find((p) => p.id === w.probe_id);
      return [probe?.name, preset.label].filter(Boolean).join(" · ");
    }
    const comp = components.find((c) => c.id === w.component_id);
    return [host, preset?.label, comp?.name].filter(Boolean).join(" · ") || "Graph";
  }
  if (w.type === "device") return host ?? "Device";
  if (w.type === "services") return `${host ?? "Device"} · Services`;
  return w.device_id ? `${host} · Problems` : "All problems";
}

function DeviceWidget({ device }: { device: Device }) {
  const counts = [device.services_ok, device.services_warn, device.services_crit, device.services_unknown];
  return (
    <Link to={`/devices/${device.id}`} className="flex items-center gap-4 p-4 group">
      <VendorLogo device={device} size={48} />
      <div className="flex-1 min-w-0">
        <div className="font-medium text-strong truncate group-hover:text-accent transition-colors">{device.hostname}</div>
        <div className="text-xs text-muted truncate">{[device.vendor, device.hardware, device.version].filter(Boolean).join(" · ")}</div>
        <div className="flex items-center gap-3 mt-2 text-xs">
          <StateBadge state={device.status} small />
          <span className="text-muted">up {fmtUptime(device.uptime)}</span>
        </div>
      </div>
      <div className="flex gap-3 text-lg font-semibold tabular-nums">
        {counts.map((n, st) => (n ? <span key={st} className={stateText(st)}>{n}</span> : null))}
      </div>
    </Link>
  );
}

function ServicesWidget({ deviceId, problemsOnly }: { deviceId: number | null; problemsOnly?: boolean }) {
  const { data = [] } = useQuery({
    queryKey: deviceId ? ["services", deviceId] : ["problems", "unhandled"],
    queryFn: () => api<Service[]>(deviceId ? `/devices/${deviceId}/services` : "/problems?include_acked=false"),
    refetchInterval: prefs.refreshMs(30_000),
  });
  const devices = useDevices();
  const rows = (problemsOnly ? data.filter((s) => s.state > 0) : data).map((s) => ({
    ...s, hostname: s.hostname ?? devices.find((d) => d.id === s.device_id)?.hostname,
  }));
  if (!rows.length) return <Empty>{problemsOnly ? "No problems" : "No services"}</Empty>;
  return <div className="max-h-80 overflow-y-auto"><ServiceTable services={rows} showHost={!deviceId} canAck={false} problems={problemsOnly} /></div>;
}

const HEIGHTS = { compact: 140, normal: 0, tall: 380 };

/** Chart height for a widget: "normal" keeps today's look (taller for full-width widgets). */
export function chartHeight(w: Widget): number {
  if (w.height === "compact") return w.compact ? 64 : HEIGHTS.compact;
  if (w.height === "tall") return w.compact ? 160 : HEIGHTS.tall;
  if (w.compact) return 90;
  return (w.cols ?? 0) >= 12 || (!w.cols && w.size === "l") ? 260 : 200;
}

export function WidgetLogo({ logo, className = "w-5 h-5" }: { logo?: string | null; className?: string }) {
  const src = logoSrc(logo);
  if (!src) return null;
  return <img src={src} alt="" className={`${className} object-contain shrink-0`} loading="lazy" referrerPolicy="no-referrer" />;
}

/** Series of a graph widget with its custom labels applied (probe graphs default to the probe name). */
export function widgetMetrics(w: Widget, preset: Preset, probe?: Probe): MetricDef[] {
  return preset.metrics.map((m) => {
    const key = m.label ?? m.name;
    const fallback = preset.source === "probe" && preset.metrics.length === 1 && probe ? probe.name : key;
    return { ...m, label: w.labels?.[key] || fallback };
  });
}

function CompactValues({ w, preset, metrics, range }: { w: Widget; preset: Preset; metrics: MetricDef[]; range: string }) {
  const isProbe = preset.source === "probe";
  const { data } = useQuery(seriesQuery({
    deviceId: w.device_id, probeId: isProbe ? w.probe_id : null, componentId: preset.kind ? w.component_id ?? 0 : 0,
    names: metrics.map((m) => m.name).concat(isProbe && preset.id === "probe_latency" ? ["ping_min", "ping_max"] : []), range,
  }));
  return (
    <div className="flex flex-wrap items-baseline gap-x-4 gap-y-1 px-4 pt-1">
      {metrics.map((m, i) => {
        const v = lastValue(data, m.name);
        return (
          <div key={m.name} className="flex items-baseline gap-1.5 min-w-0">
            <span className="text-xl font-semibold tabular-nums text-strong" style={{ color: w.colors?.[i] ?? (metrics.length > 1 ? SERIES_VARS[i % SERIES_VARS.length] : undefined) }}>
              {v == null ? "–" : preset.format(v)}
            </span>
            {metrics.length > 1 && <span className="text-xs text-muted truncate">{m.label}</span>}
          </div>
        );
      })}
    </div>
  );
}

/** One preset metric of a device/component or a probe: last value over the range plus the points (sparkline). */
function useMetric(src: { device_id?: number | null; component_id?: number | null; probe_id?: number | null; preset?: string | null; metric?: string | null }, range: string) {
  const { byId } = usePresets();
  const preset = byId(src.preset);
  const m = pickMetric(preset, src.metric);
  const isProbe = preset?.source === "probe";
  const { data, isLoading } = useQuery({
    ...seriesQuery({
      deviceId: isProbe ? null : src.device_id, probeId: isProbe ? src.probe_id : null,
      componentId: preset?.kind ? src.component_id ?? 0 : 0, names: m ? [m.name] : [], range,
    }),
    enabled: !!m && !!(isProbe ? src.probe_id : src.device_id) && (!preset?.kind || !!src.component_id),
  });
  const points = m ? data?.[m.name] ?? [] : [];
  return { preset, m, value: m ? lastValue(data, m.name) : null, points, isLoading };
}

const fmtFor = (preset: Preset | undefined, v: number | null) => (v == null ? "–" : preset ? preset.format(v) : String(v));

function KpiWidget({ w, range, probe }: { w: Widget; range: string; probe?: Probe }) {
  const uptime = w.stat === "uptime";
  const metric = useMetric(uptime ? { probe_id: w.probe_id, preset: "probe_uptime" } : w, range);
  if (uptime && !probe) return <Empty>Pick a probe</Empty>;
  const win = w.window ?? "30d";
  const value = uptime ? probe!.uptime[win] ?? null : metric.value;
  const text = uptime ? fmtPct(value) : fmtFor(metric.preset, value);
  const caption = w.caption || (uptime ? `last ${win === "24h" ? "24 hours" : win === "7d" ? "7 days" : "30 days"}` : metric.preset?.label);
  const tone = uptime && value != null ? (value >= 99.9 ? undefined : value >= 98 ? "text-warn" : "text-crit") : undefined;
  return <Kpi text={text} caption={caption ?? undefined} spark={metric.points.map((p) => p[1])} color={w.colors?.[0] ?? (uptime ? nsVar("green") : undefined)} tone={tone} />;
}

function GaugeWidget({ w, range }: { w: Widget; range: string }) {
  const { preset, value, isLoading } = useMetric(w, range);
  if (!preset) return <Empty>Widget is not configured</Empty>;
  return (
    <div className="px-4 pb-4 pt-1">
      <Gauge value={isLoading ? null : value} min={w.min ?? 0} max={w.max ?? 100} warn={w.warn} crit={w.crit}
        text={fmtFor(preset, value)} label={preset.label} />
    </div>
  );
}

function RingsWidget({ w, range }: { w: Widget; range: string }) {
  const { byId } = usePresets();
  const devices = useDevices();
  const probes = useProbes();
  const items = (w.items ?? []).slice(0, 4);
  const results = useQueries({
    queries: items.map((it) => {
      const preset = byId(it.preset);
      const m = pickMetric(preset, it.metric);
      const isProbe = preset?.source === "probe";
      return {
        ...seriesQuery({ deviceId: isProbe ? null : it.device_id, probeId: isProbe ? it.probe_id : null,
          componentId: preset?.kind ? it.component_id ?? 0 : 0, names: m ? [m.name] : [], range }),
        enabled: !!m && !!(isProbe ? it.probe_id : it.device_id),
      };
    }),
  });
  if (!items.length) return <Empty>Add 1–4 rings</Empty>;
  const label = (it: RingItem) => it.label || (it.probe_id ? probes.find((p) => p.id === it.probe_id)?.name
    : devices.find((d) => d.id === it.device_id)?.hostname) || byId(it.preset)?.label || "–";
  return (
    <div className="flex flex-wrap justify-around gap-4 px-4 pb-5 pt-2">
      {items.map((it, i) => {
        const m = pickMetric(byId(it.preset), it.metric);
        const v = m ? lastValue(results[i].data as Series | undefined, m.name) : null;
        return <Ring key={i} value={v} label={label(it)} color={it.color ?? [nsVar("teal"), nsVar("orange"), nsVar("purple"), nsVar("pink")][i]} size={112} />;
      })}
    </div>
  );
}

function DonutWidget({ w }: { w: Widget }) {
  const scope = useContext(DashboardScope);
  const devices = useDevices();
  const probes = useProbes();
  const problemsOnly = w.count === "problems";
  const pickedDevices = w.device_id ? devices.filter((d) => d.id === w.device_id)
    : scope ? devices.filter((d) => scope.deviceIds.includes(d.id)) : devices;
  const pickedProbes = w.device_id ? [] : scope ? probes.filter((p) => scope.probeIds.includes(p.id)) : probes;
  const counts = [0, 0, 0, 0];
  for (const d of pickedDevices) {
    counts[0] += d.services_ok ?? 0; counts[1] += d.services_warn ?? 0; counts[2] += d.services_crit ?? 0; counts[3] += d.services_unknown ?? 0;
  }
  for (const p of pickedProbes) for (const s of p.services) counts[s.state] = (counts[s.state] ?? 0) + 1;
  const items = counts.map((n, st) => ({ label: STATE_WORDS[st], value: n, color: STATE_VARS[st] }))
    .filter((it, st) => (!problemsOnly || st > 0) && it.value > 0);
  const total = items.reduce((a, i) => a + i.value, 0);
  return (
    <div className="px-4 pb-4 pt-1">
      <Donut items={items} center={total} caption={problemsOnly ? "open" : "services"} />
    </div>
  );
}

function BarsWidget({ w, range }: { w: Widget; range: string }) {
  const { byId } = usePresets();
  const preset = byId(w.preset);
  const m = pickMetric(preset, w.metric);
  const isProbe = preset?.source === "probe";
  const probes = useProbes();
  const limit = w.limit ?? 5;
  const { data: latest = [] } = useQuery({
    queryKey: ["latest", w.device_id, preset?.kind, m?.name],
    queryFn: () => api<{ component_id: number; name: string; values: Record<string, number> }[]>(
      `/devices/${w.device_id}/latest?name=${m!.name}${preset?.kind ? `&kind=${preset.kind}` : ""}`),
    enabled: !isProbe && !!w.device_id && !!m && !!preset?.kind,
    refetchInterval: prefs.refreshMs(60_000),
  });
  const ids = isProbe ? (w.probe_ids ?? []).slice(0, 10) : [];
  const probeSeries = useQueries({
    queries: ids.map((id) => seriesQuery({ probeId: id, names: m ? [m.name] : [], range })),
  });
  if (!preset || !m) return <Empty>Widget is not configured</Empty>;
  const rows = isProbe
    ? ids.map((id, i) => ({ label: probes.find((p) => p.id === id)?.name ?? `Probe ${id}`, value: lastValue(probeSeries[i].data as Series | undefined, m.name) }))
    : latest.map((c) => ({ label: c.name, value: c.values[m.name] ?? null }));
  const top = rows.sort((a, b) => (b.value ?? -1) - (a.value ?? -1)).slice(0, limit);
  if (!top.length) return <Empty>No data yet</Empty>;
  return <div className="px-4 pb-4 pt-1"><HBars items={top.map((r) => ({ ...r, text: fmtFor(preset, r.value) }))} /></div>;
}

function UptimeWidget({ w, probe }: { w: Widget; probe?: Probe }) {
  const { data: beats = [] } = useQuery({
    queryKey: ["probe-beats", w.probe_id],
    queryFn: () => api<Heartbeat[]>(`/probes/${w.probe_id}/heartbeats?limit=100`),
    refetchInterval: prefs.refreshMs(30_000),
    enabled: !!w.probe_id,
  });
  if (!probe) return <Empty>Probe not found</Empty>;
  const tall = w.height === "tall" ? "h-14" : w.height === "compact" || w.compact ? "h-5" : "h-[38px]";
  const windows: ["24h" | "7d" | "30d", string][] = [["24h", "24 h"], ["7d", "7 d"], ["30d", "30 d"]];
  const days = probe.cert_days_left;
  const http = probe.last_message?.match(/^HTTP \d{3}/)?.[0];
  const sep = <span className="text-faint">·</span>;
  return (
    <div className={w.compact ? "px-4 pb-3 pt-1 space-y-2" : "px-4 pb-4 pt-1 space-y-3"}>
      {!w.compact && (
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
          <StatusPill enabled={probe.enabled} maintenance={probe.maintenance} state={probe.state} />
          <span className="text-xs text-muted truncate max-w-[20rem]">{probe.last_message}</span>
        </div>
      )}
      <HeartbeatBar beats={beats} max={w.compact ? 60 : 100} height={tall} />
      <div className="flex flex-wrap items-baseline gap-x-2.5 gap-y-1 text-xs text-muted">
        {(w.compact ? windows.slice(0, 1) : windows).map(([k, label], i) => (
          <span key={k} className="inline-flex items-baseline gap-2.5">
            {i > 0 && sep}<span>{label} <span className="font-semibold tabular-nums text-strong">{fmtPct(probe.uptime[k])}</span></span>
          </span>
        ))}
        {!w.compact && days != null && <>{sep}<span>cert <span className={`font-semibold tabular-nums ${daysTone(days)}`}>{Math.floor(days)} days</span></span></>}
        {!w.compact && http && <>{sep}<span>{http}</span></>}
        {!w.compact && <>{sep}<span className="tabular-nums">{fmtMs(probe.rtt_ms ?? probe.last_response_ms)}</span></>}
      </div>
    </div>
  );
}

export function WidgetBody({ w, range }: { w: Widget; range: string }) {
  const { byId: presetById } = usePresets();
  const devices = useDevices();
  const probes = useProbes();
  const device = devices.find((d) => d.id === w.device_id);

  if (w.type === "uptime") return w.probe_id ? <UptimeWidget w={w} probe={probes.find((p) => p.id === w.probe_id)} /> : <Empty>Pick a probe</Empty>;
  if (w.type === "kpi") return <KpiWidget w={w} range={range} probe={probes.find((p) => p.id === w.probe_id)} />;
  if (w.type === "gauge") return <GaugeWidget w={w} range={range} />;
  if (w.type === "rings") return <RingsWidget w={w} range={range} />;
  if (w.type === "donut") return <DonutWidget w={w} />;
  if (w.type === "bars") return <BarsWidget w={w} range={range} />;
  if (w.type === "graph") {
    const preset = presetById(w.preset);
    const isProbe = preset?.source === "probe";
    if (!preset || (isProbe ? !w.probe_id : !w.device_id)) return <Empty>Widget is not configured</Empty>;
    const probe = isProbe ? probes.find((p) => p.id === w.probe_id) : undefined;
    const metrics = widgetMetrics(w, preset, probe);
    const band = isProbe && preset.id === "probe_latency" ? { min: "ping_min", max: "ping_max" } : undefined;
    const chart = (
      <MetricChart deviceId={isProbe ? undefined : w.device_id!} probeId={isProbe ? w.probe_id! : undefined}
        componentId={preset.kind ? w.component_id ?? 0 : 0} range={range} metrics={metrics} format={preset.format}
        area={preset.area ?? true} height={chartHeight(w)} colors={w.colors} compact={!!w.compact} band={band} style={w.style} />
    );
    if (w.compact) {
      return (
        <div>
          <CompactValues w={w} preset={preset} metrics={metrics} range={range} />
          <div className="px-2 pb-2 pt-1">{chart}</div>
        </div>
      );
    }
    return <div className="px-3 pb-3">{chart}</div>;
  }
  if (w.type === "device") return device ? <DeviceWidget device={device} /> : <Empty>Device not found</Empty>;
  if (w.type === "services") return w.device_id ? <ServicesWidget deviceId={w.device_id} /> : <Empty>Pick a device</Empty>;
  return <ServicesWidget deviceId={w.device_id} problemsOnly />;
}
