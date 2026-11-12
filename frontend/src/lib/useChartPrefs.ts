import { useQuery } from "@tanstack/react-query";
import { api, Me } from "../api";
import { setChartPrefs } from "./chartTheme";

/** Applies the user's chart look and returns a key that changes when it does (charts re-render). */
export function useChartPrefs(): string {
  const me = useQuery({ queryKey: ["me"], queryFn: () => api<Me>("/auth/me"), staleTime: 60_000 }).data;
  const p = me?.preferences.chart;
  setChartPrefs(p);
  return JSON.stringify(p ?? {});
}
