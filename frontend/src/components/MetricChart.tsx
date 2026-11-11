import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import ReactECharts from "echarts-for-react";
import { api, Series } from "../api";
import { useTheme } from "../theme";
import { chartThemeName, ChartStyle, lineSeries, rangeSeries, seriesPalette, timeBase, withAlpha } from "../lib/chartTheme";

export interface MetricDef { name: string; label?: string; scale?: number }

/** Hex (#RGB/#RRGGBB) to the comma rgb() form ECharts needs. */
function hexColor(hex: string): string {
  let h = hex.replace("#", "");
  if (h.length === 3) h = h.split("").map((c) => c + c).join("");
  const n = parseInt(h, 16);
  return `rgb(${(n >> 16) & 255}, ${(n >> 8) & 255}, ${n & 255})`;
}

/** Shared by MetricChart and compact widgets so both read one cached request. */
export function seriesQuery({ deviceId, probeId, componentId = 0, names, range }: {
  deviceId?: number | null; probeId?: number | null; componentId?: number; names: string[]; range: string;
}) {
  const base = probeId ? `/probes/${probeId}/metrics` : `/devices/${deviceId}/metrics`;
  return {
    queryKey: ["metrics", probeId ? `probe:${probeId}` : deviceId, componentId, names, range],
    queryFn: () => api<Series>(`${base}?${names.map((n) => `name=${n}`).join("&")}&component_id=${componentId}&range=${range}`),
    refetchInterval: 60_000,
    enabled: !!(probeId || deviceId),
  };
}

export function MetricChart({
  deviceId, probeId, componentId = 0, metrics, range, unit = "", height = 200, format, area = true,
  colors, compact = false, band, style,
}: {
  deviceId?: number; probeId?: number; componentId?: number; metrics: MetricDef[]; range: string;
  unit?: string; height?: number; format?: (v: number) => string; area?: boolean;
  /** one hex colour per series, in order (missing ones use the theme palette) */
  colors?: string[] | null;
  /** no legend, no axis labels: for small/minimalist widgets */
  compact?: boolean;
  /** draw a shaded band between two extra series (e.g. ping_min..ping_max) */
  band?: { min: string; max: string; label?: string };
  /** area (glow fill) | line | spike (sharp, no fill) | range (min–max bars + average); default from `area` */
  style?: ChartStyle | null;
}) {
  const { theme } = useTheme();
  const names = [...new Set([...metrics.map((m) => m.name), ...(band ? [band.min, band.max] : [])])];
  const { data, isLoading } = useQuery(seriesQuery({ deviceId, probeId, componentId, names, range }));
  const fmt = format ?? ((v: number) => `${Number.isInteger(v) ? v : v.toFixed(1)}${unit}`);
  const empty = !isLoading && metrics.every((m) => !(data?.[m.name]?.length));
  const colorKey = (colors ?? []).join(",");
  const look: ChartStyle = style ?? (area ? "area" : "line");

  const option = useMemo(() => {
    const palette = seriesPalette(colors?.map((c) => (c ? hexColor(c) : c)));
    const legend: string[] = [];
    let series: Record<string, unknown>[];
    if (look === "range") {
      // one metric as min–max bars (from its own bucket min/max, or the band series) plus the average line
      const m = metrics[0];
      const scale = m.scale ?? 1;
      const pts = data?.[m.name] ?? [];
      const mins = band ? new Map((data?.[band.min] ?? []).map(([t, , mn]) => [t, mn])) : null;
      const maxs = band ? new Map((data?.[band.max] ?? []).map(([t, , , mx]) => [t, mx])) : null;
      const rows = pts.map(([t, avg, mn, mx]) => {
        const lo = mins?.get(t) ?? mn, hi = maxs?.get(t) ?? mx;
        return [t, avg == null ? null : avg * scale, lo == null ? null : lo * scale, hi == null ? null : hi * scale] as [string, number | null, number | null, number | null];
      });
      const name = m.label ?? m.name;
      legend.push(name);
      series = rangeSeries({ name, data: rows, colors: colors?.length ? palette.slice(0, 3) : undefined });
    } else {
      const lines = metrics.map((m, i) => lineSeries({
        name: m.label ?? m.name,
        color: palette[i % palette.length],
        data: (data?.[m.name] ?? []).map(([t, avg]) => [t, avg == null ? null : avg * (m.scale ?? 1)]),
        style: look,
        compact,
        // stacked fills turn to mud past three series: only the first three get the gradient
        fill: i < 3,
      }));
      legend.push(...lines.map((l) => l.name as string));
      const bandSeries = band && data && look !== "spike" ? (() => {
        const mins = data[band.min] ?? [];
        const maxByT = new Map((data[band.max] ?? []).map(([t, , , mx]) => [t, mx]));
        const lower = mins.map(([t, , mn]) => [t, mn]);
        const width = mins.map(([t, , mn]) => [t, maxByT.has(t) ? Math.max(0, (maxByT.get(t) as number) - mn) : null]);
        const tint = palette[0];
        const label = band.label ?? "min–max";
        legend.push(label);
        return [
          { name: "_bandlow", type: "line", stack: "band", data: lower, showSymbol: false, lineStyle: { opacity: 0 },
            tooltip: { show: false }, silent: true, z: 1 },
          { name: label, type: "line", stack: "band", data: width, showSymbol: false, lineStyle: { opacity: 0 },
            areaStyle: { color: withAlpha(tint, 0.14) }, itemStyle: { color: tint }, silent: true, z: 1,
            tooltip: { show: false } },
        ];
      })() : [];
      series = [...bandSeries, ...lines];
    }
    return { ...timeBase({ compact, fmt, legend }), color: palette, series };
    // theme is a dependency so the tokens are re-read after switching
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [data, theme, look, unit, colorKey, compact, metrics.map((m) => m.label).join("|")]);

  return (
    <div style={{ height }} className="relative">
      {(isLoading || empty) && (
        <div className="absolute inset-0 flex items-center justify-center text-muted text-xs pointer-events-none">
          {isLoading ? "Loading…" : "No data for this range yet"}
        </div>
      )}
      <ReactECharts key={theme} option={option} theme={chartThemeName(theme)} style={{ height }} notMerge opts={{ renderer: "svg" }} />
    </div>
  );
}

/** Latest average of a series (for compact widgets and lists). */
export function lastValue(series: Series | undefined, name: string): number | null {
  const s = series?.[name];
  return s && s.length ? s[s.length - 1][1] : null;
}
