import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import ReactECharts from "echarts-for-react";
import { api, Series } from "../api";
import { token, useTheme } from "../theme";

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
  colors, compact = false, band,
}: {
  deviceId?: number; probeId?: number; componentId?: number; metrics: MetricDef[]; range: string;
  unit?: string; height?: number; format?: (v: number) => string; area?: boolean;
  /** one hex colour per series, in order (missing ones use the theme palette) */
  colors?: string[] | null;
  /** no legend, no axis labels: for small/minimalist widgets */
  compact?: boolean;
  /** draw a shaded band between two extra series (e.g. ping_min..ping_max) */
  band?: { min: string; max: string; label?: string };
}) {
  const { theme } = useTheme();
  const names = [...metrics.map((m) => m.name), ...(band ? [band.min, band.max] : [])];
  const { data, isLoading } = useQuery(seriesQuery({ deviceId, probeId, componentId, names, range }));
  const fmt = format ?? ((v: number) => `${Number.isInteger(v) ? v : v.toFixed(1)}${unit}`);
  const empty = !isLoading && metrics.every((m) => !(data?.[m.name]?.length));
  const colorKey = (colors ?? []).join(",");

  const option = useMemo(() => {
    // accent first, then neutral and two supporting hues; per-widget colours override in order
    const palette = [token("accent"), token("fg2"), "#5b8def", "#f5a524", "#3dd68c", "#a78bfa"]
      .map((c, i) => (colors?.[i] ? hexColor(colors[i]) : c));
    const lines = metrics.map((m, i) => ({
      name: m.label ?? m.name,
      type: "line",
      showSymbol: false,
      symbolSize: 4,
      connectNulls: false,
      lineStyle: { width: compact ? 1.5 : 1.75, color: palette[i % palette.length] },
      itemStyle: { color: palette[i % palette.length] },
      areaStyle: area && i === 0 ? { opacity: theme === "dark" ? 0.14 : 0.1 } : undefined,
      data: (data?.[m.name] ?? []).map(([t, avg]) => [t, avg * (m.scale ?? 1)]),
      z: 3,
    }));
    const bandSeries = band && data ? (() => {
      const mins = data[band.min] ?? [];
      const maxByT = new Map((data[band.max] ?? []).map(([t, , , mx]) => [t, mx]));
      const lower = mins.map(([t, , mn]) => [t, mn]);
      const width = mins.map(([t, , mn]) => [t, maxByT.has(t) ? Math.max(0, (maxByT.get(t) as number) - mn) : null]);
      const tint = palette[0];
      return [
        { name: "_bandlow", type: "line", stack: "band", data: lower, showSymbol: false, lineStyle: { opacity: 0 },
          tooltip: { show: false }, silent: true, z: 1 },
        { name: band.label ?? "min–max", type: "line", stack: "band", data: width, showSymbol: false, lineStyle: { opacity: 0 },
          areaStyle: { color: tint, opacity: theme === "dark" ? 0.18 : 0.14 }, itemStyle: { color: tint }, silent: true, z: 1,
          tooltip: { show: false } },
      ];
    })() : [];
    return {
      backgroundColor: "transparent",
      color: palette,
      animationDuration: 300,
      grid: compact ? { left: 0, right: 0, top: 4, bottom: 0, containLabel: false } : { left: 8, right: 12, top: 30, bottom: 4, containLabel: true },
      legend: compact ? { show: false } : {
        top: 0, right: 0, icon: "roundRect", itemWidth: 10, itemHeight: 3, textStyle: { color: token("muted"), fontSize: 11 },
        data: [...lines.map((l) => l.name), ...(band ? [band.label ?? "min–max"] : [])],
      },
      tooltip: {
        trigger: "axis",
        backgroundColor: token("surface"),
        borderColor: token("edge"),
        textStyle: { color: token("fg"), fontSize: 12 },
        axisPointer: { lineStyle: { color: token("edge") } },
        valueFormatter: (v: number) => (v == null ? "-" : fmt(v)),
      },
      xAxis: {
        type: "time",
        show: !compact,
        axisLine: { lineStyle: { color: token("line") } },
        axisTick: { show: false },
        axisLabel: { color: token("muted"), fontSize: 10, hideOverlap: true },
        splitLine: { show: false },
      },
      yAxis: {
        type: "value",
        show: !compact,
        scale: compact,
        splitLine: { lineStyle: { color: token("line", 0.6) } },
        axisLabel: { color: token("muted"), fontSize: 10, formatter: (v: number) => fmt(v) },
      },
      series: [...bandSeries, ...lines],
    };
    // theme is a dependency so token() is re-read after switching
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [data, theme, area, unit, colorKey, compact, metrics.map((m) => m.label).join("|")]);

  return (
    <div style={{ height }} className="relative">
      {(isLoading || empty) && (
        <div className="absolute inset-0 flex items-center justify-center text-muted text-xs pointer-events-none">
          {isLoading ? "Loading…" : "No data for this range yet"}
        </div>
      )}
      <ReactECharts key={theme} option={option} style={{ height }} notMerge opts={{ renderer: "svg" }} />
    </div>
  );
}

/** Latest average of a series (for compact widgets and lists). */
export function lastValue(series: Series | undefined, name: string): number | null {
  const s = series?.[name];
  return s && s.length ? s[s.length - 1][1] : null;
}
