import { useQuery } from "@tanstack/react-query";
import ReactECharts from "echarts-for-react";
import { api, Series } from "../api";

const PALETTE = ["#15d1a0", "#4aa3ff", "#ffb547", "#e36bff", "#ff5d5d", "#9be15d"];

export interface MetricDef { name: string; label?: string; scale?: number }

export function MetricChart({
  deviceId, componentId = 0, metrics, range, unit = "", height = 200, format, area = true,
}: {
  deviceId: number; componentId?: number; metrics: MetricDef[]; range: string;
  unit?: string; height?: number; format?: (v: number) => string; area?: boolean;
}) {
  const names = metrics.map((m) => m.name);
  const { data, isLoading } = useQuery({
    queryKey: ["metrics", deviceId, componentId, names, range],
    queryFn: () =>
      api<Series>(`/devices/${deviceId}/metrics?${names.map((n) => `name=${n}`).join("&")}&component_id=${componentId}&range=${range}`),
    refetchInterval: 60_000,
  });
  const fmt = format ?? ((v: number) => `${v.toFixed(1)}${unit}`);

  const option = {
    backgroundColor: "transparent",
    color: PALETTE,
    grid: { left: 64, right: 16, top: 28, bottom: 28 },
    legend: { top: 0, right: 0, textStyle: { color: "#8b98a5", fontSize: 11 }, itemHeight: 8 },
    tooltip: {
      trigger: "axis",
      backgroundColor: "#232930",
      borderColor: "#38414b",
      textStyle: { color: "#e5e7eb", fontSize: 12 },
      valueFormatter: (v: number) => (v == null ? "-" : fmt(v)),
    },
    xAxis: { type: "time", axisLine: { lineStyle: { color: "#38414b" } }, axisLabel: { color: "#8b98a5", fontSize: 10 } },
    yAxis: {
      type: "value",
      splitLine: { lineStyle: { color: "#2b323a" } },
      axisLabel: { color: "#8b98a5", fontSize: 10, formatter: (v: number) => fmt(v) },
    },
    series: metrics.map((m) => ({
      name: m.label ?? m.name,
      type: "line",
      showSymbol: false,
      smooth: false,
      lineStyle: { width: 1.5 },
      areaStyle: area ? { opacity: 0.12 } : undefined,
      data: (data?.[m.name] ?? []).map(([t, avg]) => [t, avg * (m.scale ?? 1)]),
    })),
  };

  return (
    <div style={{ height }} className="relative">
      {isLoading && <div className="absolute inset-0 flex items-center justify-center text-muted text-xs">loading…</div>}
      <ReactECharts option={option} style={{ height }} notMerge />
    </div>
  );
}
