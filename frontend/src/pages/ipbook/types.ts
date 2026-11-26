/** IP Book data as the API (/api/plugins/ipbook) returns it. Secrets never come back: only whether one is set. */
export interface Usage { size: number; used: number; free: number; pct: number }
export interface Warning { kind: string; text: string; rows: number[]; networks: number[] }
export interface Network {
  id: number; cidr: string; title: string; description: string | null; icon: string | null; vlan: string | null;
  gateway: string | null; dns: string | null; alert_when_down: boolean; source: "learned" | "manual"; hidden: boolean;
}
export interface NetworkSummary extends Network { usage: Usage; warning_count: number }
export interface Column {
  id: number; key: string; label: string; type: string; icon: string | null; options: string[] | null;
  position: number; hidden: boolean; builtin: boolean;
}
export interface Health { state: "up" | "down" | "unknown"; rtt: number | null; at: string; misses?: number }
export interface Row {
  id: number; values: Record<string, any>; secrets: Record<string, { set: boolean }>; sensitive: boolean;
  source: "learned" | "manual" | "imported"; alert_when_down: boolean | null; runs_on_id: number | null;
  device_id: number | null; conflicts: Record<string, { manual: any; discovered: any }>; manual_keys: string[];
  missing_since: string | null; match_keys?: string[]; health?: Record<string, Health>; warnings?: Warning[];
}
export interface Overview { networks: NetworkSummary[]; columns: Column[]; is_admin: boolean; counts: { all: number; no_network: number } }
export interface NetworkView { network: Network | null; rows: Row[]; usage?: Usage; grid?: string[] | null; warnings?: Warning[] }

export const IPB = "/plugins/ipbook";
/** Worst health of a row's IPs: down beats unknown beats up. */
export function rowHealth(r: Row): Health | null {
  const all = Object.values(r.health ?? {});
  if (!all.length) return null;
  return all.find((h) => h.state === "down") ?? all.find((h) => h.state === "unknown") ?? all[0];
}
