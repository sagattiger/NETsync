/** Problems over time (1h-1y) and the counters: active, unhandled, critical, new and resolved in the range. */
import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import ReactECharts from "echarts-for-react";
import { api, prefs } from "../api";
import { useTheme } from "../theme";
import { chartThemeName, ns, timeBase, withAlpha } from "../lib/chartTheme";
import { useChartPrefs } from "../lib/useChartPrefs";
import { Segmented } from "./ui";

export interface ProblemHistoryData {
  range: string; step: number; active: number; unhandled: number; critical: number; new: number; resolved: number;
  series: { t: string; open: number; peak: number; new: number; resolved: number }[];
}
const RANGES: [string, string][] = [["1h", "1h"], ["6h", "6h"], ["24h", "24h"], ["7d", "7d"], ["30d", "30d"], ["1y", "1y"]];
const LABEL: Record<string, string> = { "1h": "last hour", "6h": "last 6 hours", "24h": "last 24 hours", "7d": "last 7 days", "30d": "last 30 days", "1y": "last year" };

export function useProblemHistory(range: string) {
  return useQuery({
    queryKey: ["problem-history", range],
    queryFn: () => api<ProblemHistoryData>(`/problems/history?range=${range}`),
    refetchInterval: 60_000,
  });
}

/** The numbers only (Home widget, and above the chart). */
export function ProblemCounters({ data, range, compact = false }: { data?: ProblemHistoryData; range: string; compact?: boolean }) {
  const tiles: [string, number | undefined, string, string?][] = [
    ["Active", data?.active, data?.active ? "text-crit" : "text-ok", "/problems"],
    ["Unhandled", data?.unhandled, data?.unhandled ? "text-warn" : "text-ok", "/problems"],
    ["Critical", data?.critical, data?.critical ? "text-crit" : "text-strong"],
    [`New · ${range}`, data?.new, "text-strong"],
    [`Resolved · ${range}`, data?.resolved, "text-ok"],
  ];
  return (
    <div className={`grid grid-cols-2 sm:grid-cols-5 gap-3 ${compact ? "p-4" : ""}`}>
      {tiles.map(([label, value, tone, to]) => {
        const body = (
          <>
            <div className="text-xs text-muted">{label}</div>
            <div className={`text-2xl font-semibold tabular-nums mt-0.5 ${tone}`}>{value ?? "–"}</div>
          </>
        );
        return to ? <Link key={label} to={to} className="rounded-xl bg-inset/60 border border-line px-4 py-3 hover:border-edge">{body}</Link>
          : <div key={label} className="rounded-xl bg-inset/60 border border-line px-4 py-3">{body}</div>;
      })}
    </div>
  );
}

/** Home widget: counters for the last 24 hours. */
export function ProblemCountersWidget() {
  const { data } = useProblemHistory("24h");
  return <ProblemCounters data={data} range="24h" compact />;
}

/** Problems page: counters plus the chart, with its own range. */
export default function ProblemHistory() {
  const [range, setRange] = useState(() => prefs.get().default_range ?? "24h");
  const { data } = useProblemHistory(range);
  const { theme } = useTheme();
  const look = useChartPrefs();
  const option = useMemo(() => {
    const crit = ns("red"), ok = ns("green"), warn = ns("amber");
    const base = timeBase({ fmt: (v: number) => String(Math.round(v)), legend: ["open", "new", "resolved"], range, yMin: 0 }) as any;
    const rows = data?.series ?? [];
    return {
      ...base,
      yAxis: { ...base.yAxis, minInterval: 1 },
      series: [
        { name: "open", type: "line", step: "end", showSymbol: false, data: rows.map((b) => [b.t, b.open]),
          lineStyle: { width: 2, color: warn }, itemStyle: { color: warn }, areaStyle: { color: withAlpha(warn, 0.15) } },
        { name: "new", type: "bar", barMaxWidth: 6, data: rows.map((b) => [b.t, b.new]), itemStyle: { color: withAlpha(crit, 0.8) } },
        { name: "resolved", type: "bar", barMaxWidth: 6, data: rows.map((b) => [b.t, b.resolved]), itemStyle: { color: withAlpha(ok, 0.8) } },
      ],
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [data, theme, look, range]);
  return (
    <section className="card p-4 space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="text-sm font-medium text-strong">Problems over the {LABEL[range]}</div>
        <Segmented value={range} onChange={setRange} options={RANGES} />
      </div>
      <ProblemCounters data={data} range={range} />
      <ReactECharts key={`${theme}${look}`} option={option} theme={chartThemeName(theme)} style={{ height: 180 }} notMerge opts={{ renderer: "svg" }} />
    </section>
  );
}
