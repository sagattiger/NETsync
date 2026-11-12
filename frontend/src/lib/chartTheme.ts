/** ECharts look for NETsync ("Glow" UI kit, docs/design/netsync-ui-kit.svg).
 *
 * Every colour is read from the --ns-* CSS tokens in index.css, so dark/light switch at runtime and
 * widgets never hard-code colours. The glow is deliberately faint and only on in dark mode
 * (--ns-glow: 1); light mode draws the same palette flat. */
import * as echarts from "echarts";

export type ChartStyle = "area" | "line" | "spike" | "range";
export const CHART_STYLES: [ChartStyle, string][] = [["area", "Area"], ["line", "Line"], ["spike", "Spike"], ["range", "Min–max"]];

/** Default series order; per-widget colours still win. */
export const SERIES_ORDER = ["orange", "pink", "purple", "teal", "amber", "red"] as const;
/** OK, WARN, CRIT, UNKNOWN */
export const STATE_TOKENS = ["green", "amber", "red", "grey"] as const;

function cssVar(name: string): string {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
}

/** A --ns-* token as an ECharts-safe colour (legacy comma syntax: ECharts can't parse "rgb(r g b / a)"). */
export function ns(name: string, alpha = 1): string {
  const [r, g, b] = cssVar(`--ns-${name}`).split(/\s+/);
  if (!b) return alpha === 1 ? "#888" : `rgba(136, 136, 136, ${alpha})`;
  return alpha === 1 ? `rgb(${r}, ${g}, ${b})` : `rgba(${r}, ${g}, ${b}, ${alpha})`;
}

/** Same colour with another alpha; accepts #hex, rgb() and rgba(). */
export function withAlpha(color: string, alpha: number): string {
  if (color.startsWith("#")) {
    let h = color.slice(1);
    if (h.length === 3) h = h.split("").map((c) => c + c).join("");
    const n = parseInt(h, 16);
    return `rgba(${(n >> 16) & 255}, ${(n >> 8) & 255}, ${n & 255}, ${alpha})`;
  }
  const m = color.match(/\d+(\.\d+)?/g);
  return m && m.length >= 3 ? `rgba(${m[0]}, ${m[1]}, ${m[2]}, ${alpha})` : color;
}

/** Range name -> milliseconds (the x-axis always spans the whole range, even when data starts later). */
export const RANGE_MS: Record<string, number> = {
  "1h": 3_600_000, "6h": 21_600_000, "24h": 86_400_000, "7d": 604_800_000, "30d": 2_592_000_000, "1y": 31_536_000_000,
};

/** Insert a null where samples are missing (gap > 3x the usual step), so a line breaks instead of
 *  drawing a straight or curved bridge across an outage. */
export function withGaps<T extends [string | number, ...unknown[]]>(points: T[]): (T | [string | number, null])[] {
  if (points.length < 3) return points;
  const ts = points.map((p) => new Date(p[0]).getTime());
  const steps = ts.slice(1).map((t, i) => t - ts[i]).filter((d) => d > 0).sort((a, b) => a - b);
  const step = steps[Math.floor(steps.length / 2)] ?? 0;
  if (!step) return points;
  const out: (T | [string | number, null])[] = [points[0]];
  for (let i = 1; i < points.length; i++) {
    if (ts[i] - ts[i - 1] > step * 3) out.push([new Date(ts[i - 1] + step).toISOString(), null]);
    out.push(points[i]);
  }
  return out;
}

export const glowOn = () => cssVar("--ns-glow") === "1";
export const reducedMotion = () => typeof matchMedia !== "undefined" && matchMedia("(prefers-reduced-motion: reduce)").matches;

/** Faint halo under a stroke (dark mode only). */
export function glow(color: string, blur = 6): Record<string, unknown> {
  return glowOn() ? { shadowBlur: blur, shadowColor: withAlpha(color, 0.45) } : {};
}

/** Series colours in order, with the widget's own hex colours first where set. */
export function seriesPalette(colors?: (string | null | undefined)[] | null): string[] {
  return SERIES_ORDER.map((n, i) => colors?.[i] || ns(n));
}

export const stateColor = (state: number | null | undefined) => ns(STATE_TOKENS[state ?? 3] ?? "grey");

/** Register (or refresh) the two ECharts themes from the current CSS tokens; returns the active name. */
export function chartThemeName(theme: "light" | "dark"): string {
  const name = `netsync-${theme}`;
  echarts.registerTheme(name, {
    color: seriesPalette(),
    backgroundColor: "transparent",
    textStyle: { fontFamily: "Inter, Segoe UI, Roboto, system-ui, sans-serif", color: ns("muted") },
  });
  return name;
}

export interface TimeAxisOpts { compact?: boolean; fmt: (v: number) => string; legend?: string[]; yMin?: number; range?: string }

/** Grid, axes, tooltip and legend shared by every time-series chart. */
export function timeBase({ compact, fmt, legend, yMin, range }: TimeAxisOpts): Record<string, unknown> {
  const span = range ? RANGE_MS[range] : undefined;
  const now = Date.now();
  const motion = !reducedMotion();
  return {
    backgroundColor: "transparent",
    animation: motion,
    animationDuration: motion ? 300 : 0,
    grid: compact ? { left: 0, right: 0, top: 4, bottom: 0, containLabel: false } : { left: 8, right: 12, top: 30, bottom: 4, containLabel: true },
    legend: compact || !legend ? { show: false } : {
      top: 0, right: 0, icon: "circle", itemWidth: 8, itemHeight: 8, itemGap: 14,
      textStyle: { color: ns("muted"), fontSize: 11 }, data: legend,
    },
    tooltip: {
      trigger: "axis",
      backgroundColor: ns("card"),
      borderColor: ns("line"),
      borderWidth: 1,
      padding: [8, 12],
      extraCssText: "border-radius:10px;box-shadow:0 8px 24px rgba(0,0,0,.25);",
      textStyle: { color: ns("text"), fontSize: 12 },
      axisPointer: { type: "line", lineStyle: { color: ns("muted", 0.6), type: [3, 3] } },
      valueFormatter: (v: number) => (v == null ? "-" : fmt(v)),
    },
    xAxis: {
      type: "time",
      show: !compact,
      ...(span ? { min: now - span, max: now } : {}),
      axisLine: { show: false },
      axisTick: { show: false },
      axisLabel: { color: ns("muted"), fontSize: 11, hideOverlap: true },
      splitLine: { show: false },
    },
    yAxis: {
      type: "value",
      show: !compact,
      scale: compact,
      min: yMin,
      splitNumber: 4,
      axisLine: { show: false },
      splitLine: { lineStyle: { color: ns("line"), type: [2, 4] } },
      axisLabel: { color: ns("muted"), fontSize: 11, formatter: (v: number) => fmt(v) },
    },
  };
}

type Point = [string | number, number | null, ...unknown[]];

/** Glow area (default), plain line, or spike (sharp joins, no fill). Gaps (null) stay gaps. */
export function lineSeries({ name, color, data, style = "area", compact, fill = true, z = 3 }: {
  name: string; color: string; data: Point[]; style?: ChartStyle; compact?: boolean; fill?: boolean; z?: number;
}): Record<string, unknown> {
  const area = style === "area" && fill;
  return {
    name,
    type: "line",
    smooth: style === "spike" ? false : 0.35,
    showSymbol: false,
    symbol: "circle",
    symbolSize: 9,
    connectNulls: false,
    lineStyle: { width: compact ? 2 : 2.5, color, join: style === "spike" ? "miter" : "round", ...glow(color) },
    itemStyle: { color: "#fff", borderColor: color, borderWidth: 3 },
    emphasis: { focus: "none", scale: false, lineStyle: { width: compact ? 2 : 2.5 } },
    areaStyle: area ? {
      color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
        { offset: 0, color: withAlpha(color, glowOn() ? 0.3 : 0.22) },
        { offset: 1, color: withAlpha(color, 0) },
      ]),
    } : undefined,
    data,
    z,
  };
}

/** Thin rounded min→max bars per bucket plus a teal average line ("candles": jitter, RTT min/avg/max).
 *  ``data`` rows are [t, avg, min, max]. */
export function rangeSeries({ name, data, colors }: { name: string; data: [string, number | null, number | null, number | null][]; colors?: string[] }): Record<string, unknown>[] {
  const pal = colors?.length ? colors : [ns("orange"), ns("pink"), ns("purple")];
  const spreads = data.map((p) => (p[2] != null && p[3] != null ? p[3] - p[2] : 0)).sort((a, b) => a - b);
  const q = (f: number) => spreads[Math.floor((spreads.length - 1) * f)] ?? 0;
  const [lo, hi] = [q(0.6), q(0.9)];
  const ts = data.map((p) => new Date(p[0]).getTime());
  const step = ts.length > 1 ? Math.max(1, (ts[ts.length - 1] - ts[0]) / (ts.length - 1)) : 60_000;
  const candles = {
    name: `${name} min–max`,
    type: "custom",
    renderItem: (_: unknown, api: any) => {
      const mn = api.value(2), mx = api.value(3);
      if (mn == null || mx == null || Number.isNaN(mn) || Number.isNaN(mx)) return null;
      const top = api.coord([api.value(0), mx]);
      const bottom = api.coord([api.value(0), mn]);
      const w = Math.max(2, Math.min(7, api.size([step, 0])[0] * 0.55));
      const spread = mx - mn;
      const fill = spread > hi ? pal[2 % pal.length] : spread > lo ? pal[1 % pal.length] : pal[0];
      return {
        type: "rect",
        shape: { x: top[0] - w / 2, y: top[1], width: w, height: Math.max(2, bottom[1] - top[1]), r: w / 2 },
        style: { fill, ...glow(fill, 4) },
      };
    },
    encode: { x: 0, y: [2, 3] },
    data,
    tooltip: { show: false },
    z: 2,
  };
  const teal = ns("teal");
  const avg = {
    name,
    type: "line",
    smooth: 0.4,
    showSymbol: false,
    connectNulls: false,
    lineStyle: { width: 1.8, color: teal, ...glow(teal, 4) },
    itemStyle: { color: "#fff", borderColor: teal, borderWidth: 3 },
    data: data.map((p) => [p[0], p[1]]),
    z: 3,
  };
  return [candles, avg];
}
