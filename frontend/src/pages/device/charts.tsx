/** Chart helpers for the device page: a preset chart in a card, several components on one chart, and the
 *  list of series a device actually has (so empty graphs stay hidden). */
import { ReactNode } from "react";
import { useQueries, useQuery } from "@tanstack/react-query";
import { api, Component, prefs, Series } from "../../api";
import { AddToDashboard } from "../../components/AddToDashboard";
import { MetricChart, seriesQuery, TimeChart } from "../../components/MetricChart";
import { Card } from "../../components/ui";
import { FORMATS, Preset, usePresets } from "../../presets";
import { ns } from "../../lib/chartTheme";

/** Same colours as the RAM bar: used orange, buffers red, cached amber, free grey. */
export const MEMORY_COLORS = () => [ns("orange"), ns("red"), ns("amber"), ns("grey", 0.35)];
const PRESET_COLORS: Record<string, () => string[]> = { mem_detail: MEMORY_COLORS };

/** Device-level series with data in the last hours. */
export function useMetricNames(deviceId: number) {
  return useQuery({
    queryKey: ["metric-names", deviceId],
    queryFn: () => api<string[]>(`/devices/${deviceId}/metric-names`),
    refetchInterval: prefs.refreshMs(300_000),
    staleTime: 60_000,
  }).data;
}

/** A preset has data when any of its series is in `names` (undefined = still loading: show it). */
export const presetHasData = (p: Preset, names: string[] | undefined) => !names || p.metrics.some((m) => names.includes(m.name));

/** One preset as a card: title, add-to-dashboard, chart scaled to the capacity when the preset has a ruler. */
export function PresetCard({ deviceId, preset, range, componentId, height = 220, ruler, title, extra }: {
  deviceId: number; preset: Preset; range: string; componentId?: number; height?: number;
  /** fixed capacity for component charts (e.g. a filesystem's size) */
  ruler?: number | null;
  title?: ReactNode; extra?: ReactNode;
}) {
  return (
    <Card title={title ?? preset.label} actions={<>{extra}<AddToDashboard deviceId={deviceId} preset={preset.id} componentId={componentId} label="" /></>}>
      <div className="px-3 pb-3 pt-2">
        <MetricChart deviceId={deviceId} componentId={componentId} range={range} metrics={preset.metrics} format={preset.format}
          area={preset.area ?? true} stack={preset.stack} rulerMetric={componentId ? null : preset.ruler} ruler={ruler}
          colors={PRESET_COLORS[preset.id]?.()}
          rulerLabel={preset.ruler === "cpu_count" ? "threads" : "total"} height={height} />
      </div>
    </Card>
  );
}

/** Grid of preset cards for a list of preset ids, skipping the ones without data. */
export function PresetGrid({ deviceId, ids, range, names }: { deviceId: number; ids: string[]; range: string; names?: string[] }) {
  const { byId } = usePresets();
  const shown = ids.map((id) => byId(id)).filter((p): p is Preset => !!p && presetHasData(p, names));
  if (!shown.length) return null;
  return (
    <div className="grid lg:grid-cols-2 gap-4">
      {shown.map((p) => <PresetCard key={p.id} deviceId={deviceId} preset={p} range={range} />)}
    </div>
  );
}

/** The same metric of several components on one chart (all core temperatures, every filesystem…). */
export function MultiChart({ deviceId, components, metric, range, format, height = 240, area = false, label }: {
  deviceId: number; components: Component[]; metric: string; range: string; format: (v: number) => string;
  height?: number; area?: boolean; label?: (c: Component) => string;
}) {
  const results = useQueries({
    queries: components.map((c) => seriesQuery({ deviceId, componentId: c.id, names: [metric], range })),
  });
  const data: Series = {};
  components.forEach((c, i) => { data[`c${c.id}`] = (results[i].data as Series | undefined)?.[metric] ?? []; });
  return (
    <TimeChart data={data} isLoading={results.some((r) => r.isLoading)} format={format} area={area} height={height} range={range}
      metrics={components.map((c) => ({ name: `c${c.id}`, label: label ? label(c) : c.name }))} />
  );
}

export const fmtUnit = (unit: keyof typeof FORMATS) => FORMATS[unit];
