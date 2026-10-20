import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { api, Component, Device, fmtUptime, prefs, Service, Widget } from "../../api";
import { MetricChart } from "../../components/MetricChart";
import ServiceTable from "../../components/ServiceTable";
import { VendorLogo } from "../../components/VendorLogo";
import { Empty, StateBadge, stateText } from "../../components/ui";
import { presetById } from "../../presets";

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

/** Title shown when the widget has no custom title. */
export function autoTitle(w: Widget, devices: Device[], components: Component[]): string {
  const host = devices.find((d) => d.id === w.device_id)?.hostname;
  if (w.type === "graph") {
    const preset = presetById(w.preset);
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

export function WidgetBody({ w, range }: { w: Widget; range: string }) {
  const devices = useDevices();
  const device = devices.find((d) => d.id === w.device_id);

  if (w.type === "graph") {
    const preset = presetById(w.preset);
    if (!preset || !w.device_id) return <Empty>Widget is not configured</Empty>;
    return (
      <div className="p-3">
        <MetricChart deviceId={w.device_id} componentId={preset.kind ? w.component_id ?? 0 : 0} range={range}
          metrics={preset.metrics} format={preset.format} area={preset.area ?? true} height={w.size === "l" ? 260 : 200} />
      </div>
    );
  }
  if (w.type === "device") return device ? <DeviceWidget device={device} /> : <Empty>Device not found</Empty>;
  if (w.type === "services") return w.device_id ? <ServicesWidget deviceId={w.device_id} /> : <Empty>Pick a device</Empty>;
  return <ServicesWidget deviceId={w.device_id} problemsOnly />;
}
