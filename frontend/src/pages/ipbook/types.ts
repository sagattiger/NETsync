/** IP Book data as the API (/api/plugins/ipbook) returns it. Secrets never come back: only whether one is set. */
export interface Warning { kind: string; text: string; rows: number[]; networks: number[] }
export interface Column {
  id: number; key: string; label: string; type: string; icon: string | null; options: string[] | null;
  position: number; hidden: boolean; builtin: boolean; kind: "service" | "ip";
}
export interface Book {
  id: number; kind: "ip" | "service"; title: string; heading: string | null; description: string | null; icon: string | null;
  cidr: string | null; vlan: string | null; gateway: string | null; dns: string | null; alert_when_down: boolean; position: number;
}
export interface Counts { size: number; used: number; available: number; reserved: number }
export interface BookSummary extends Book { counts?: Counts; entries?: number }
export interface Health { state: "up" | "down" | "unknown"; rtt: number | null; at: string; misses?: number }
export interface Row {
  id: number; values: Record<string, any>; secrets: Record<string, { set: boolean }>; sensitive: boolean;
  source: "learned" | "manual" | "imported"; alert_when_down: boolean | null; runs_on_id: number | null;
  device_id: number | null; conflicts: Record<string, { manual: any; discovered: any }>; manual_keys: string[];
  missing_since: string | null; match_keys?: string[]; health?: Record<string, Health>; warnings?: Warning[]; book_id?: number;
}
export type AddressStatus = "subnet" | "broadcast" | "gateway" | "available" | "used" | "reserved" | "down";
export interface Address {
  ip: string; status: AddressStatus; values: Record<string, any>; reserved: boolean; learned: boolean;
  alert_when_down: boolean | null; updated_at: string | null; updated_by: string | null; health: Health | null;
}
export interface Overview { books: BookSummary[]; columns: { service: Column[]; ip: Column[] }; is_admin: boolean }
export interface IpBookView { book: Book; addresses: Address[]; counts: Counts }
export interface ServiceBookView { book: Book; rows: Row[] }
export interface SearchResult { rows: Row[]; addresses: { book_id: number; book: string; ip: string; values: Record<string, any> }[] }

export const IPB = "/plugins/ipbook";
/** Worst health of a row's IPs: down beats unknown beats up. */
export function rowHealth(r: Row): Health | null {
  const all = Object.values(r.health ?? {});
  if (!all.length) return null;
  return all.find((h) => h.state === "down") ?? all.find((h) => h.state === "unknown") ?? all[0];
}
