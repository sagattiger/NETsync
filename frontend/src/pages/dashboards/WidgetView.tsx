import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { api, Component, Device, fmtUptime, logoSrc, prefs, Probe, Service, Widget } from "../../api";
import { lastValue, MetricChart, MetricDef, seriesQuery } from "../../components/MetricChart";
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

/** Title shown when the widget has no custom title. */
export function autoTitle(w: Widget, devices: Device[], components: Component[],
  presetById: (id: string | null | undefined) => Preset | undefined, probes: Probe[] = []): string {
  const host = devices.find((d) => d.id === w.device_id)?.hostname;
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
    <div className="flex flex-wrap items-baseline gap-x-4 gap-y-1 px-4 pt-3">
      {metrics.map((m, i) => {
        const v = lastValue(data, m.name);
        return (
          <div key={m.name} className="flex items-baseline gap-1.5 min-w-0">
            <span className="text-xl font-semibold tabular-nums text-strong" style={w.colors?.[i] ? { color: w.colors[i] } : undefined}>
              {v == null ? "–" : preset.format(v)}
            </span>
            {metrics.length > 1 && <span className="text-xs text-muted truncate">{m.label}</span>}
          </div>
        );
      })}
    </div>
  );
}

export function WidgetBody({ w, range }: { w: Widget; range: string }) {
  const { byId: presetById } = usePresets();
  const devices = useDevices();
  const probes = useProbes();
  const device = devices.find((d) => d.id === w.device_id);

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
        area={preset.area ?? true} height={chartHeight(w)} colors={w.colors} compact={!!w.compact} band={band} />
    );
    if (w.compact) {
      return (
        <div>
          <CompactValues w={w} preset={preset} metrics={metrics} range={range} />
          <div className="px-2 pb-2 pt-1">{chart}</div>
        </div>
      );
    }
    return <div className="p-3">{chart}</div>;
  }
  if (w.type === "device") return device ? <DeviceWidget device={device} /> : <Empty>Device not found</Empty>;
  if (w.type === "services") return w.device_id ? <ServicesWidget deviceId={w.device_id} /> : <Empty>Pick a device</Empty>;
  return <ServicesWidget deviceId={w.device_id} problemsOnly />;
}
