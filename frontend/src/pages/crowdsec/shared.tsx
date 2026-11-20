/** CrowdSec plugin: the widget data shape (same as the public API) and the widget body used on dashboards and the
 * CrowdSec page. Totals, scenarios and days only: never addresses. */
import { useQuery } from "@tanstack/react-query";
import { api, prefs } from "../../api";
import { HBars, Kpi, Spark } from "../../components/Charts";
import { Empty, StateBadge } from "../../components/ui";

export interface CrowdSecWidgetData {
  id: string; type: "crowdsec"; title: string; state: "OK" | "WARN" | "CRIT" | "UNKNOWN";
  status: "ok" | "stale" | "none"; updated_at: string | null; since: string | null;
  active: number; community: number; total: number; new_24h: number | null; new_7d: number | null;
  days: [string, number | null][]; scenarios: { key: string; value: number }[];
}

const STATE_NUM = { OK: 0, WARN: 1, CRIT: 2, UNKNOWN: 3 } as const;
export const fmtInt = (n: number | null | undefined) => (n == null ? "–" : Math.round(n).toLocaleString());

/** crowdsecurity/ssh-bf -> ssh-bf (the full key in the tooltip). */
export const scenarioLabel = (key: string) => (key.includes("/") ? key.slice(key.lastIndexOf("/") + 1) : key);

export function useCrowdSecWidget(ids: number[] | null | undefined, limit = 5) {
  return useQuery({
    queryKey: ["crowdsec", "widget", (ids ?? []).join(","), limit],
    queryFn: () => api<CrowdSecWidgetData>(`/plugins/crowdsec/widget?ids=${(ids ?? []).join(",")}&limit=${limit}`),
    refetchInterval: prefs.refreshMs(60_000),
  });
}

export function DayBars({ days }: { days: [string, number | null][] }) {
  const max = Math.max(1, ...days.map(([, n]) => n ?? 0));
  return (
    <div className="flex items-end gap-1.5 h-20" role="img"
      aria-label={days.map(([d, n]) => `${d}: ${n ?? "no data"}`).join(", ")}>
      {days.map(([d, n]) => (
        <div key={d} className="flex-1 flex flex-col items-center gap-1 min-w-0" title={`${d}: ${n ?? "no data"}`}>
          <div className="w-full flex-1 flex items-end">
            <div className={`w-full rounded-t-[4px] ${n == null ? "bg-ns-track" : "bg-gradient-to-t from-ns-orange to-ns-amber"}`}
              style={{ height: `${n == null ? 6 : Math.max(4, (n / max) * 100)}%` }} />
          </div>
          <span className="text-[10px] text-faint tabular-nums">{d.slice(8)}</span>
        </div>
      ))}
    </div>
  );
}

export function CrowdSecBody({ data, compact }: { data: CrowdSecWidgetData; compact?: boolean }) {
  if (data.status === "none") return <Empty>No CrowdSec data yet. Add a source on the CrowdSec page.</Empty>;
  const spark = data.days.map(([, n]) => n);
  return (
    <div>
      <div className="flex items-center gap-2 px-5 pt-1 text-xs text-muted">
        <StateBadge state={STATE_NUM[data.state]} small />
        {data.status === "stale"
          ? <span className="text-warn">Data unavailable · last update {data.updated_at ? new Date(data.updated_at).toLocaleString() : "–"}</span>
          : <span>Updated {data.updated_at ? new Date(data.updated_at).toLocaleTimeString() : "–"}</span>}
      </div>
      <Kpi text={fmtInt(data.active)} caption="IPs blocked now by our own detection" spark={spark.some((v) => v != null) ? spark : undefined} />
      {!compact && (
        <div className="px-5 pb-5 space-y-4">
          <div className="grid grid-cols-3 gap-3 text-xs">
            {([["New · 24 h", data.new_24h], ["New · 7 days", data.new_7d], ["Community list", data.community]] as [string, number | null][])
              .map(([label, n]) => (
                <div key={label} className="rounded-lg bg-inset px-3 py-2">
                  <div className="text-muted truncate">{label}</div>
                  <div className="text-base font-semibold text-strong tabular-nums">{fmtInt(n)}</div>
                </div>
              ))}
          </div>
          {data.scenarios.length > 0 && (
            <div>
              <div className="text-xs font-semibold text-muted mb-2">Top reasons</div>
              <HBars items={data.scenarios.map((s) => ({ label: scenarioLabel(s.key), value: s.value, text: fmtInt(s.value) }))} />
            </div>
          )}
        </div>
      )}
    </div>
  );
}

export function CrowdSecWidget({ ids, limit, compact }: { ids?: number[] | null; limit?: number | null; compact?: boolean }) {
  const { data, isLoading, error } = useCrowdSecWidget(ids, limit ?? 5);
  if (error) return <Empty>CrowdSec plugin not available</Empty>;
  if (isLoading || !data) return <Empty>Loading…</Empty>;
  return <CrowdSecBody data={data} compact={compact} />;
}

export { Spark };
