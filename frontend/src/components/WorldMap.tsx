/** World map of devices and sites (offline: country shapes come from the world-atlas package, no tile server).
 *
 *  Devices: green = up without problems, yellow = open problems (count shown), red = down.
 *  Devices at the same place (same site, or same coordinates) are one marker; clicking it lists them in a grid.
 *  Sites and data centers are blue buildings; hovering shows only the site name. */
import { useEffect, useMemo, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import ReactECharts from "echarts-for-react";
import * as echarts from "echarts";
import { api } from "../api";
import { useTheme } from "../theme";
import { Icon } from "./Icon";

export interface MapDevice {
  id: number; hostname: string; status: number; disabled: boolean; os: string | null; device_type: string | null;
  site_id: number | null; lat: number; lon: number; warn: number; crit: number; unknown: number; location: string | null;
}
export interface MapSite { id: number; name: string; kind: "site" | "datacenter"; lat: number; lon: number; address: string | null }
interface MapData { devices: MapDevice[]; sites: MapSite[]; unplaced: number }

export const REGIONS: Record<string, { label: string; center: [number, number]; zoom: number }> = {
  world: { label: "World", center: [10, 20], zoom: 1.15 },
  americas: { label: "Americas", center: [-75, 10], zoom: 2.2 },
  south_america: { label: "South America", center: [-58, -20], zoom: 3.2 },
  brazil: { label: "Brazil", center: [-50, -14], zoom: 4.2 },
  sao_paulo: { label: "São Paulo", center: [-46.8, -23.5], zoom: 30 },
  north_america: { label: "North America", center: [-98, 42], zoom: 3 },
  europe: { label: "Europe", center: [12, 50], zoom: 4.5 },
  asia: { label: "Asia", center: [100, 30], zoom: 2.6 },
};

// a small building (data center / site)
const BUILDING = "path://M3 22V3a1 1 0 0 1 1-1h10a1 1 0 0 1 1 1v5h5a1 1 0 0 1 1 1v13h1v2H2v-2h1Zm2 0h3v-4h4v4h1V4H5v18Zm10 0h4V10h-4v12ZM7 6h2v2H7V6Zm4 0h2v2h-2V6ZM7 10h2v2H7v-2Zm4 0h2v2h-2v-2Zm-4 4h2v2H7v-2Zm4 0h2v2h-2v-2Zm6-2h2v2h-2v-2Zm0 4h2v2h-2v-2Z";
const GREEN = "#22c55e", YELLOW = "#f5b83d", RED = "#ef4444", BLUE = "#3b82f6";

let loading: Promise<void> | null = null;

/** Rings that cross the 180° meridian draw a line across the whole map: drop those pieces (eastern Chukotka, Fiji). */
function dropWrapped(f: any): any {
  const wraps = (ring: number[][]) => ring.some((p, i) => i > 0 && Math.abs(p[0] - ring[i - 1][0]) > 180);
  const g = f.geometry;
  if (!g) return f;
  if (g.type === "Polygon" && wraps(g.coordinates[0])) return { ...f, geometry: { type: "MultiPolygon", coordinates: [] } };
  if (g.type === "MultiPolygon") return { ...f, geometry: { ...g, coordinates: g.coordinates.filter((poly: number[][][]) => !wraps(poly[0])) } };
  return f;
}
/** Register the "world" map once (50m country shapes, ~0.7 MB, loaded on first use). */
export function loadWorld(): Promise<void> {
  loading ??= Promise.all([import("world-atlas/countries-50m.json"), import("topojson-client")]).then(([topo, tc]) => {
    const t = (topo as any).default ?? topo;
    const geo = tc.feature(t, t.objects.countries) as any;
    geo.features = geo.features.filter((f: any) => f.properties?.name !== "Antarctica").map(dropWrapped);
    echarts.registerMap("world", geo);
  });
  return loading;
}

export interface Group {
  key: string; lon: number; lat: number; site: MapSite | null; devices: MapDevice[];
  down: number; problems: number; level: 0 | 1 | 2;
}

export function devLevel(d: MapDevice): 0 | 1 | 2 {
  if (d.status === 2) return 2;
  return d.crit + d.warn > 0 ? 1 : 0;
}

/** One marker per site, or per exact position for devices without a site. */
export function groupDevices(devices: MapDevice[], sites: MapSite[]): Group[] {
  const bySite = new Map(sites.map((s) => [s.id, s]));
  const groups = new Map<string, Group>();
  for (const d of devices) {
    const site = d.site_id ? bySite.get(d.site_id) ?? null : null;
    const key = site ? `s${site.id}` : `${d.lat.toFixed(4)},${d.lon.toFixed(4)}`;
    const g = groups.get(key) ?? { key, lon: d.lon, lat: d.lat, site, devices: [], down: 0, problems: 0, level: 0 as 0 | 1 | 2 };
    g.devices.push(d);
    g.down += d.status === 2 ? 1 : 0;
    g.problems += d.crit + d.warn;
    g.level = Math.max(g.level, devLevel(d)) as 0 | 1 | 2;
    groups.set(key, g);
  }
  return [...groups.values()];
}

export function WorldMap({ height = 420, center, zoom, style = "auto", hideSites = false }: {
  height?: number; center?: [number, number] | null; zoom?: number | null; style?: "night" | "light" | "auto" | null; hideSites?: boolean | null;
}) {
  const { theme } = useTheme();
  const [ready, setReady] = useState(false);
  const [open, setOpen] = useState<{ g: Group; x: number; y: number } | null>(null);
  const box = useRef<HTMLDivElement>(null);
  const { data } = useQuery({ queryKey: ["map"], queryFn: () => api<MapData>("/map"), refetchInterval: 30_000 });
  useEffect(() => { loadWorld().then(() => setReady(true)); }, []);
  const night = style === "night" || (style !== "light" && theme === "dark");

  const groups = useMemo(() => groupDevices(data?.devices ?? [], data?.sites ?? []), [data]);
  const totals = useMemo(() => {
    const all = data?.devices ?? [];
    return { ok: all.filter((d) => devLevel(d) === 0).length, warn: all.filter((d) => devLevel(d) === 1).length,
      down: all.filter((d) => devLevel(d) === 2).length, problems: all.reduce((n, d) => n + d.warn + d.crit, 0) };
  }, [data]);

  const option = useMemo(() => {
    if (!ready) return null;
    const color = (lv: number) => [GREEN, YELLOW, RED][lv];
    const statusData = groups.map((g) => ({
      name: g.site?.name ?? g.devices[0].location ?? g.devices[0].hostname,
      value: [g.lon, g.lat, g.devices.length], group: g,
      symbolSize: Math.min(26, 10 + Math.min(g.devices.length, 8) * 1.6),
      symbolOffset: g.site && !hideSites ? [13, -12] : [0, 0],
      itemStyle: { color: color(g.level), borderColor: night ? "rgba(255,255,255,.85)" : "#fff", borderWidth: 1.5,
        shadowBlur: night ? 12 : 0, shadowColor: color(g.level) },
      label: {
        show: g.problems > 0 || g.down > 0 || g.devices.length > 1,
        formatter: g.down ? `${g.down} down` : g.problems ? `${g.problems}` : `${g.devices.length}`,
        position: g.devices.length > 1 && !g.problems && !g.down ? "inside" : "right",
        color: g.down ? RED : g.problems ? YELLOW : "#fff", fontWeight: 700, fontSize: 11,
        textBorderColor: night ? "#020617" : "#fff", textBorderWidth: 3,
      },
    }));
    const sites = hideSites ? [] : (data?.sites ?? []);
    // decorative links: every site to the nearest data center (like the backbone in a NOC map)
    const dcs = sites.filter((s) => s.kind === "datacenter");
    const links = dcs.length ? sites.filter((s) => s.kind !== "datacenter" || dcs.length > 1).map((s) => {
      const dc = dcs.filter((d) => d.id !== s.id).sort((a, b) => Math.hypot(a.lon - s.lon, a.lat - s.lat) - Math.hypot(b.lon - s.lon, b.lat - s.lat))[0];
      return dc ? { coords: [[s.lon, s.lat], [dc.lon, dc.lat]] } : null;
    }).filter(Boolean) : [];
    return {
      backgroundColor: night
        ? new echarts.graphic.RadialGradient(0.5, 0.35, 0.9, [{ offset: 0, color: "#0b1d3a" }, { offset: 1, color: "#020617" }])
        : "#eef4fb",
      tooltip: {
        trigger: "item", confine: true,
        formatter: (p: any) => {
          if (p.seriesName === "sites") return `<b>${p.name}</b>`;
          const g: Group | undefined = p.data?.group;
          if (!g) return "";
          const head = g.site ? `<b>${g.site.name}</b>` : `<b>${g.devices.length === 1 ? g.devices[0].hostname : `${g.devices.length} devices`}</b>`;
          const parts = [g.down && `${g.down} down`, g.problems && `${g.problems} problems`].filter(Boolean).join(" · ") || "all OK";
          return `${head}<br/>${g.devices.length} device${g.devices.length === 1 ? "" : "s"} · ${parts}`;
        },
      },
      geo: {
        map: "world", roam: true, center: center ?? REGIONS.world.center, zoom: zoom ?? REGIONS.world.zoom,
        scaleLimit: { min: 0.8, max: 60 }, silent: true,
        itemStyle: night
          ? { areaColor: "#0d2747", borderColor: "rgba(56,189,248,.45)", borderWidth: 0.6, shadowColor: "rgba(56,189,248,.35)", shadowBlur: 6 }
          : { areaColor: "#d9e3ee", borderColor: "#9fb2c8", borderWidth: 0.5 },
      },
      series: [
        ...(links.length ? [{
          name: "links", type: "lines", coordinateSystem: "geo", silent: true, zlevel: 1,
          effect: { show: night, period: 5, trailLength: 0.35, symbolSize: 2.5, color: "#7dd3fc" },
          lineStyle: { color: night ? "rgba(56,189,248,.55)" : "rgba(59,130,246,.45)", width: 1.1, curveness: 0.25 },
          data: links,
        }] : []),
        ...(sites.length ? [{
          name: "sites", type: "scatter", coordinateSystem: "geo", symbol: BUILDING, symbolSize: 20, zlevel: 2,
          itemStyle: { color: BLUE, shadowBlur: night ? 14 : 0, shadowColor: "rgba(59,130,246,.9)" },
          data: sites.map((s) => ({ name: s.name, value: [s.lon, s.lat], site: s })),
        }] : []),
        { name: "devices", type: "scatter", coordinateSystem: "geo", zlevel: 3, data: statusData.filter((d) => d.group.level < 2) },
        { name: "down", type: "effectScatter", coordinateSystem: "geo", zlevel: 4, rippleEffect: { scale: 3, brushType: "stroke" },
          data: statusData.filter((d) => d.group.level === 2) },
      ],
    };
  }, [ready, groups, data, night, center, zoom, hideSites]);

  const onClick = (p: any) => {
    const rect = box.current?.getBoundingClientRect();
    const x = (p.event?.offsetX ?? 0), y = (p.event?.offsetY ?? 0);
    if (p.seriesName === "sites") {
      const g = groups.find((x) => x.site?.id === p.data.site.id) ?? { key: "s", lon: 0, lat: 0, site: p.data.site, devices: [], down: 0, problems: 0, level: 0 as const };
      setOpen({ g, x, y });
    } else if (p.data?.group) setOpen({ g: p.data.group, x, y });
    void rect;
  };

  return (
    <div ref={box} className="relative" style={{ height }}>
      {option ? (
        <ReactECharts option={option} notMerge style={{ height }} opts={{ renderer: "canvas" }} onEvents={{ click: onClick }} />
      ) : <div className="h-full flex items-center justify-center text-xs text-muted">Loading the map…</div>}

      {/* legend */}
      <div className={`absolute left-3 bottom-3 flex flex-wrap items-center gap-3 text-xs px-3 py-1.5 rounded-lg backdrop-blur ${night ? "bg-black/40 text-slate-200" : "bg-white/80 text-fg2"}`}>
        <span className="flex items-center gap-1.5"><span className="w-2.5 h-2.5 rounded-full" style={{ background: GREEN }} />OK {totals.ok}</span>
        <span className="flex items-center gap-1.5"><span className="w-2.5 h-2.5 rounded-full" style={{ background: YELLOW }} />Problems {totals.warn}{totals.problems ? ` (${totals.problems})` : ""}</span>
        <span className="flex items-center gap-1.5"><span className="w-2.5 h-2.5 rounded-full" style={{ background: RED }} />Down {totals.down}</span>
        {!hideSites && !!data?.sites.length && <span className="flex items-center gap-1.5"><span style={{ color: BLUE }}><Icon name="server" className="w-3 h-3" /></span>Sites {data.sites.length}</span>}
      </div>
      {!!data?.unplaced && (
        <Link to="/settings/sites" className={`absolute right-3 bottom-3 text-xs px-3 py-1.5 rounded-lg backdrop-blur hover:underline ${night ? "bg-black/40 text-slate-300" : "bg-white/80 text-muted"}`}>
          {data.unplaced} device{data.unplaced === 1 ? "" : "s"} without a location
        </Link>
      )}
      {data && !data.devices.length && !data.sites.length && (
        <div className="absolute inset-0 flex items-center justify-center pointer-events-none">
          <div className={`text-sm px-4 py-2 rounded-lg ${night ? "bg-black/50 text-slate-200" : "bg-white/90 text-fg2"}`}>
            Give devices a location (Settings → Sites, or a device's Settings) to see them here.
          </div>
        </div>
      )}

      {open && (
        <div className="absolute z-10 w-[min(26rem,calc(100%-1.5rem))] max-h-[80%] overflow-auto card shadow-2xl p-3"
          style={{ left: Math.min(open.x + 12, (box.current?.clientWidth ?? 400) - 420 > 0 ? open.x + 12 : 12), top: Math.max(12, Math.min(open.y - 20, height - 260)) }}>
          <div className="flex items-center gap-2 mb-2">
            {open.g.site ? <span style={{ color: BLUE }}><Icon name="server" className="w-4 h-4" /></span> : <Icon name="globe" className="w-4 h-4 text-muted" />}
            <div className="min-w-0 flex-1">
              <div className="text-sm font-semibold text-strong truncate">{open.g.site?.name ?? open.g.devices[0]?.location ?? "Devices here"}</div>
              <div className="text-xxs text-muted">{open.g.site ? (open.g.site.kind === "datacenter" ? "Data center" : "Site") : `${open.g.lat.toFixed(4)}, ${open.g.lon.toFixed(4)}`}
                {open.g.site?.address ? ` · ${open.g.site.address}` : ""} · {open.g.devices.length} device{open.g.devices.length === 1 ? "" : "s"}</div>
            </div>
            <button className="p-1 text-muted hover:text-strong" onClick={() => setOpen(null)}><Icon name="x" className="w-4 h-4" /></button>
          </div>
          <div className="grid grid-cols-2 sm:grid-cols-3 gap-1.5">
            {open.g.devices.map((d) => {
              const lv = devLevel(d);
              return (
                <Link key={d.id} to={`/devices/${d.id}`} className="rounded-md border border-line px-2 py-1.5 hover:bg-active/40 min-w-0"
                  style={{ borderLeft: `3px solid ${[GREEN, YELLOW, RED][lv]}` }}>
                  <div className="text-xs font-medium text-strong truncate" title={d.hostname}>{d.hostname.split(".")[0]}</div>
                  <div className="text-xxs text-muted truncate">
                    {d.status === 2 ? <span className="text-crit">down</span>
                      : d.crit + d.warn ? <>{d.crit ? <span className="text-crit">{d.crit} crit</span> : null}{d.crit && d.warn ? " · " : ""}{d.warn ? <span className="text-warn">{d.warn} warn</span> : null}</>
                      : "OK"}
                  </div>
                </Link>
              );
            })}
            {!open.g.devices.length && <div className="col-span-full text-xs text-muted p-2">No devices at this site yet.</div>}
          </div>
        </div>
      )}
    </div>
  );
}
