import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { api, fmtBps, fmtBytes, fmtUptime } from "./api";
import type { MetricDef } from "./components/MetricChart";

/** Graph presets come from the backend (GET /api/presets, netsync/presets.py) so they never drift. */
export type Unit = "bps" | "pct" | "ms" | "s" | "rate" | "count" | "bytes" | "Bps" | "celsius" | "rpm" | "load" | "duration";

export interface Preset {
  id: string;
  label: string;
  group: string;
  kind: string | null; // component kind the preset needs (null = device-level series)
  unit: Unit;
  metrics: MetricDef[];
  area: boolean;
  source: "device" | "probe"; // probe presets point at widget.probe_id
  stack?: boolean; // stacked series (parts of one whole)
  ruler?: string | null; // metric with the real capacity (mem_total, cpu_count): top of the scale
  format: (v: number) => string;
}

type ApiPreset = Omit<Preset, "format" | "metrics"> & { metrics: { name: string; label: string }[] };

export const FORMATS: Record<Unit, (v: number) => string> = {
  bps: fmtBps,
  pct: (v) => `${v.toFixed(v < 10 ? 1 : 0)}%`,
  ms: (v) => `${v.toFixed(1)} ms`,
  s: (v) => `${v.toFixed(2)} s`,
  rate: (v) => (v >= 100 ? `${v.toFixed(0)}/s` : `${v.toFixed(v < 1 ? 2 : 1)}/s`),
  count: (v) => `${Math.round(v)}`,
  bytes: (v) => fmtBytes(v),
  Bps: (v) => `${fmtBytes(v)}/s`,
  celsius: (v) => `${v.toFixed(1)} °C`,
  rpm: (v) => `${Math.round(v)} RPM`,
  load: (v) => v.toFixed(2),
  duration: (v) => fmtUptime(v),
};

export function usePresets() {
  const { data } = useQuery({
    queryKey: ["presets"],
    queryFn: () => api<ApiPreset[]>("/presets"),
    staleTime: Infinity,
  });
  return useMemo(() => {
    const presets: Preset[] = (data ?? []).map((p) => ({ ...p, format: FORMATS[p.unit] ?? FORMATS.count }));
    const byId = (id: string | null | undefined) => presets.find((p) => p.id === id);
    const groups = [...new Set(presets.map((p) => p.group))];
    return { presets, byId, groups, loaded: !!data };
  }, [data]);
}
