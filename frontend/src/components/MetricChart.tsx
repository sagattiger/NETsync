import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import ReactECharts from "echarts-for-react";
import { api, Series } from "../api";
import { useTheme } from "../theme";
import { chartThemeName, ChartStyle, lineSeries, ns, rangeSeries, seriesPalette, timeBase, withAlpha, withGaps } from "../lib/chartTheme";

export interface MetricDef { name: string; label?: string; scale?: number }

/** Hex (#RGB/#RRGGBB) to the comma rgb() form ECharts needs; other colour strings pass through. */
function hexColor(hex: string): string {
  if (!hex.startsWith("#")) return hex;
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

type ChartProps = {
  metrics: MetricDef[]; unit?: string; height?: number; format?: (v: number) => string; area?: boolean;
  /** one hex colour per series, in order (missing ones use the theme palette) */
  colors?: string[] | null;
  /** no legend, no axis labels: for small/minimalist widgets */
  compact?: boolean;
  /** draw a shaded band between two extra series (e.g. ping_min..ping_max) */
  band?: { min: string; max: string; label?: string };
  /** area (glow fill) | line | spike (sharp, no fill) | range (min–max bars + average); default from `area` */
  style?: ChartStyle | null;
  /** stack the series (parts of one whole: used + buffers + cached + free) */
  stack?: boolean;
  /** real capacity (RAM size, disk size, thread count): top of the scale, drawn as a dashed "total" line */
  ruler?: number | null;
  rulerLabel?: string;
  /** range name (1h…1y): the time axis spans all of it */
  range?: string;
};

export function MetricChart({ deviceId, probeId, componentId = 0, range, rulerMetric, ...rest }: ChartProps & {
  deviceId?: number; probeId?: number; componentId?: number; range: string;
  /** device-level series whose newest value is the capacity (e.g. mem_total, cpu_count) */
  rulerMetric?: string | null;
}) {
  const names = [...new Set([...rest.metrics.map((m) => m.name), ...(rest.band ? [rest.band.min, rest.band.max] : []),
    ...(rulerMetric && !componentId ? [rulerMetric] : [])])];
  const { data, isLoading } = useQuery(seriesQuery({ deviceId, probeId, componentId, names, range }));
  // a ruler on a component chart (rare) would need a second request; device-level rulers come with the data
  const ruler = rest.ruler ?? (rulerMetric ? lastValue(data, rulerMetric) : null);
  return <TimeChart data={data} isLoading={isLoading} {...rest} ruler={ruler} range={range} />;
}

/** The chart itself, from already-loaded series (MetricChart fetches; the /ui-kit page passes fake data). */
export function TimeChart({
  data, isLoading = false, metrics, unit = "", height = 200, format, area = true, colors, compact = false, band, style,
  stack = false, ruler, rulerLabel = "total", range,
}: ChartProps & { data: Series | undefined; isLoading?: boolean }) {
  const { theme } = useTheme();
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
        data: withGaps((data?.[m.name] ?? []).map(([t, avg]) => [t, avg == null ? null : avg * (m.scale ?? 1)] as [string, number | null])),
        style: stack ? "area" : look,
        compact,
        // stacked fills turn to mud past three series: only the first three get the gradient
        fill: stack || i < 3,
      }));
      if (stack) {
        for (const l of lines) {
          l.stack = "total";
          l.smooth = false;
          const color = (l.lineStyle as { color: string }).color;
          l.lineStyle = { ...(l.lineStyle as object), width: 1 };
          l.areaStyle = { color: withAlpha(color, 0.55) };
        }
      }
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
    const base = timeBase({ compact, fmt, legend, range }) as Record<string, any>;
    if (ruler != null && ruler > 0 && series.length) {
      // the real capacity is the top of the scale; the data can still go above it (e.g. load > threads)
      base.yAxis = { ...base.yAxis, min: 0, max: (v: { max: number }) => Math.max(ruler, v.max) };
      const last = series[series.length - 1];
      last.markLine = {
        silent: true, symbol: "none", animation: false,
        lineStyle: { type: [4, 4], width: 1, color: ns("muted") },
        label: { position: "insideEndTop", color: "inherit", fontSize: 10, formatter: `${rulerLabel} ${fmt(ruler)}` },
        data: [{ yAxis: ruler }],
      };
    }
    return { ...base, color: palette, series };
    // theme is a dependency so the tokens are re-read after switching
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [data, theme, look, unit, colorKey, compact, stack, ruler, range, metrics.map((m) => m.label).join("|")]);

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
