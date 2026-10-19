import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import ReactECharts from "echarts-for-react";
import { api, Series } from "../api";
import { token, useTheme } from "../theme";

export interface MetricDef { name: string; label?: string; scale?: number }

export function MetricChart({
  deviceId, componentId = 0, metrics, range, unit = "", height = 200, format, area = true,
}: {
  deviceId: number; componentId?: number; metrics: MetricDef[]; range: string;
  unit?: string; height?: number; format?: (v: number) => string; area?: boolean;
}) {
  const { theme } = useTheme();
  const names = metrics.map((m) => m.name);
  const { data, isLoading } = useQuery({
    queryKey: ["metrics", deviceId, componentId, names, range],
    queryFn: () =>
      api<Series>(`/devices/${deviceId}/metrics?${names.map((n) => `name=${n}`).join("&")}&component_id=${componentId}&range=${range}`),
    refetchInterval: 60_000,
  });
  const fmt = format ?? ((v: number) => `${Number.isInteger(v) ? v : v.toFixed(1)}${unit}`);
  const empty = !isLoading && metrics.every((m) => !(data?.[m.name]?.length));

  const option = useMemo(() => {
    // accent first, then neutral and two supporting hues
    const palette = [token("accent"), token("fg2"), "#5b8def", "#f5a524", "#3dd68c", "#a78bfa"];
    return {
      backgroundColor: "transparent",
      color: palette,
      animationDuration: 300,
      grid: { left: 8, right: 12, top: 30, bottom: 4, containLabel: true },
      legend: { top: 0, right: 0, icon: "roundRect", itemWidth: 10, itemHeight: 3, textStyle: { color: token("muted"), fontSize: 11 } },
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
        axisLine: { lineStyle: { color: token("line") } },
        axisTick: { show: false },
        axisLabel: { color: token("muted"), fontSize: 10, hideOverlap: true },
        splitLine: { show: false },
      },
      yAxis: {
        type: "value",
        splitLine: { lineStyle: { color: token("line", 0.6) } },
        axisLabel: { color: token("muted"), fontSize: 10, formatter: (v: number) => fmt(v) },
      },
      series: metrics.map((m, i) => ({
        name: m.label ?? m.name,
        type: "line",
        showSymbol: false,
        symbolSize: 4,
        connectNulls: false,
        lineStyle: { width: 1.75 },
        areaStyle: area && i === 0 ? { opacity: theme === "dark" ? 0.14 : 0.1 } : undefined,
        data: (data?.[m.name] ?? []).map(([t, avg]) => [t, avg * (m.scale ?? 1)]),
      })),
    };
    // theme is a dependency so token() is re-read after switching
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [data, theme, area, unit]);

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
