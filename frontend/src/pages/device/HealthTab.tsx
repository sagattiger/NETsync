/** Device Health: overview plus processor, memory, storage, disk I/O, temperature and fan pages. */
import { Fragment, ReactNode, useState } from "react";
import { Component, fmtBytes, Service } from "../../api";
import { Icon } from "../../components/Icon";
import { MetricChart } from "../../components/MetricChart";
import { Bar, Card, Empty, hideSm, LevelBar } from "../../components/ui";
import { FORMATS, usePresets } from "../../presets";
import { MultiChart, PresetCard, PresetGrid, useMetricNames } from "./charts";

export type HealthSub = "overview" | "processor" | "memory" | "storage" | "diskio" | "temperature" | "fanspeed";

const sensorsOf = (cs: Component[], cls: string) => cs.filter((c) => c.kind === "sensor" && c.attrs.class === cls)
  .sort((a, b) => a.name.localeCompare(b.name, undefined, { numeric: true }));

/** Physical cores = CPU core temperature sensors ("Core 0", "Core 1"…); hyper-threads share a core. */
export function cpuInfo(components: Component[]) {
  const cpus = components.filter((c) => c.kind === "processor");
  const model = cpus.find((c) => c.attrs.model)?.attrs.model as string | undefined;
  const cores = sensorsOf(components, "temperature").filter((s) => /^Core \d+$/.test(s.name)).length;
  const loads = cpus.map((c) => c.values.load).filter((v): v is number => v != null);
  return { cpus, model, threads: cpus.length, cores, avg: loads.length ? loads.reduce((a, b) => a + b, 0) / loads.length : null };
}

/** "Intel Xeon E5-2697 v2 @ 2.70GHz · 12 cores · 24 threads" */
export function cpuLine(components: Component[]): string | null {
  const { model, threads, cores } = cpuInfo(components);
  if (!threads) return null;
  return [model, cores ? `${cores} cores` : null, `${threads} ${threads === 1 ? "thread" : "threads"}`].filter(Boolean).join(" · ");
}

function SubNav({ value, onChange, items }: { value: HealthSub; onChange: (s: HealthSub) => void; items: [HealthSub, string, string][] }) {
  return (
    <div className="flex gap-1 overflow-x-auto no-scrollbar -mx-1 px-1">
      {items.map(([k, label, icon]) => (
        <button key={k} onClick={() => onChange(k)}
          className={`inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs whitespace-nowrap transition-colors ${value === k ? "bg-seg-active text-on-seg-active" : "text-muted hover:text-fg hover:bg-inset"}`}>
          <Icon name={icon} className="w-3.5 h-3.5" />{label}
        </button>
      ))}
    </div>
  );
}

// ---------------------------------------------------------------- memory breakdown (like `free`)

const MEM_PARTS: [string, string, string][] = [
  ["mem_used", "Used", "bg-ns-orange"], ["mem_buffers", "Buffers", "bg-ns-red"],
  ["mem_cached", "Cached", "bg-ns-amber/70"], ["mem_free", "Free", "bg-chip"],
];

function MemoryBreakdown({ stats }: { stats: Component }) {
  const v = stats.values;
  const total = v.mem_total as number | undefined;
  if (!total) return null;
  const pct = (n?: number) => (n == null ? 0 : (n / total) * 100);
  const swapTotal = v.swap_total as number | undefined;
  return (
    <div className="space-y-3">
      <div className="flex items-center gap-3">
        <span className="text-xs font-semibold text-strong w-12">RAM</span>
        <div className="flex-1 h-5 rounded-md overflow-hidden flex bg-chip" role="img"
          aria-label={MEM_PARTS.map(([k, l]) => `${l} ${pct(v[k]).toFixed(0)}%`).join(", ")}>
          {MEM_PARTS.map(([k, label, bg]) => (
            <div key={k} className={`${bg} h-full`} style={{ width: `${pct(v[k])}%` }} title={`${label} ${fmtBytes(v[k])}`} />
          ))}
        </div>
        <span className="text-xs tabular-nums text-fg2 w-12 text-right">{pct(v.mem_used).toFixed(0)}%</span>
      </div>
      {swapTotal ? (
        <div className="flex items-center gap-3">
          <span className="text-xs font-semibold text-strong w-12">Swap</span>
          <div className="flex-1 h-2.5 rounded-md overflow-hidden bg-chip">
            <div className="h-full bg-ns-purple" style={{ width: `${Math.max(v.swap_used ? 0.5 : 0, ((v.swap_used ?? 0) / swapTotal) * 100)}%` }} />
          </div>
          <span className="text-xs tabular-nums text-fg2 w-12 text-right">{(((v.swap_used ?? 0) / swapTotal) * 100).toFixed(0)}%</span>
        </div>
      ) : null}
      <div className="grid grid-cols-2 sm:grid-cols-3 gap-x-6 gap-y-1.5 text-xs">
        {MEM_PARTS.map(([k, label, bg]) => (
          <span key={k} className="inline-flex items-center gap-2 min-w-0">
            <span className={`w-2.5 h-2.5 rounded-sm shrink-0 ${bg}`} />
            <span className="text-muted">{label}</span>
            <span className="text-fg tabular-nums truncate">{fmtBytes(v[k])} ({pct(v[k]).toFixed(0)}%)</span>
          </span>
        ))}
        <span className="inline-flex items-center gap-2"><span className="w-2.5 h-2.5 rounded-sm shrink-0 bg-ns-teal" /><span className="text-muted">Available</span><span className="text-fg tabular-nums">{fmtBytes(v.mem_available)}</span></span>
        <span className="inline-flex items-center gap-2"><span className="w-2.5 h-2.5 rounded-sm shrink-0 bg-ns-purple" /><span className="text-muted">Swap</span><span className="text-fg tabular-nums">{fmtBytes(v.swap_used)} of {fmtBytes(swapTotal)}</span></span>
        <span className="inline-flex items-center gap-2"><span className="w-2.5 h-2.5 rounded-sm shrink-0 border border-line" /><span className="text-muted">Total</span><span className="text-fg tabular-nums">{fmtBytes(total)}</span></span>
      </div>
    </div>
  );
}

/** Where swap lives (needs the netsync-disks extend) and whether it's an Intel Optane drive. */
function SwapDevices({ stats }: { stats: Component }) {
  const swaps = (stats.attrs.swaps ?? []) as { device: string; disk: string; kind: string; size_kb: number; used_kb: number | null; model: string | null; optane: boolean }[];
  if (!stats.attrs.extend) {
    return (
      <p className="text-xs text-muted">
        The swap device and disk models aren't visible over standard SNMP. Add the <code className="text-fg">netsync-disks</code> extend
        to <code className="text-fg">/etc/snmp/snmpd.conf</code> on the host (see <span className="text-fg">docs/HOST-METRICS.md</span>) and
        press Rediscover: NETsync then shows which disk holds swap and recognises Intel Optane drives.
      </p>
    );
  }
  if (!swaps.length) return <p className="text-xs text-muted">No swap configured.</p>;
  return (
    <ul className="space-y-1.5">
      {swaps.map((s) => (
        <li key={s.device} className="flex flex-wrap items-center gap-2 text-xs">
          <span className="font-mono text-fg">{s.device}</span>
          {s.optane && <span className="pill pill-ok text-xxs px-2 py-0.5">Intel Optane</span>}
          <span className="text-muted">{s.model ?? (s.disk.startsWith("dm-") ? "on LVM / device-mapper" : "model unknown")}</span>
          <span className="text-muted">· {fmtBytes(s.size_kb * 1024)}{s.used_kb != null ? `, ${fmtBytes(s.used_kb * 1024)} used` : ""}</span>
        </li>
      ))}
    </ul>
  );
}

// ---------------------------------------------------------------- sensors

/** warn/crit of the service checking this component (or, with ``check``, the first service of that check). */
function limitsOf(services: Service[], componentId: number | null, check?: string): { warn?: number; crit?: number } {
  const s = services.find((x) => (componentId != null ? x.component_id === componentId : x.check === check));
  const p = (s?.perf ?? {}) as Record<string, number>;
  return { ...(p.warn != null ? { warn: p.warn } : {}), ...(p.crit != null ? { crit: p.crit } : {}) };
}

function SensorTable({ items, services, unit, range, deviceId }: {
  items: Component[]; services: Service[]; unit: "celsius" | "rpm"; range: string; deviceId: number;
}) {
  const [open, setOpen] = useState<number | null>(null);
  const fmt = FORMATS[unit];
  const groups = [...new Set(items.map((c) => c.attrs.group ?? "Board"))];
  const top = Math.max(0, ...items.map((c) => Number(c.values.value) || 0));
  return (
    <>
      {groups.map((g) => (
        <Card key={g} title={g === "Processor" ? "Processor sensors" : g === "Board" ? (unit === "rpm" ? "Fans" : "Board sensors") : g}>
          <table className="tbl"><tbody>
            {items.filter((c) => (c.attrs.group ?? "Board") === g).map((c) => {
              const svc = services.find((s) => s.component_id === c.id);
              const value = c.values.value != null ? Number(c.values.value) : null;
              const warn = svc?.perf?.warn ?? null, crit = svc?.perf?.crit ?? null;
              const below = (svc?.perf as any)?.direction === "below";
              // the scale: past the critical limit for temperatures, a bit above the fastest fan for speeds
              const max = unit === "celsius"
                ? Math.max(100, (crit ?? 0) * 1.15, (value ?? 0) * 1.1)
                : Math.max(top * 1.25, (warn ?? 0) * 1.5, 1000);
              return (
                <Fragment key={c.id}>
                  <tr className="cursor-pointer" onClick={() => setOpen(open === c.id ? null : c.id)}>
                    <td className="text-strong font-medium w-40 whitespace-nowrap">
                      <div className="flex items-center gap-2">
                        <Icon name="chevron" className={`w-3.5 h-3.5 text-muted transition-transform ${open === c.id ? "rotate-90" : ""}`} />
                        <span className="truncate max-w-[9rem]" title={c.name}>{c.name}</span>
                      </div>
                    </td>
                    <td><LevelBar value={value} max={max} warn={warn} crit={crit} below={below} fmt={fmt} state={svc?.state} /></td>
                  </tr>
                  {open === c.id && (
                    <tr><td colSpan={2} className="bg-inset/40">
                      <MetricChart deviceId={deviceId} componentId={c.id} range={range} format={fmt} area={false} height={180}
                        metrics={[{ name: "value", label: c.name }]} />
                    </td></tr>
                  )}
                </Fragment>
              );
            })}
          </tbody></table>
        </Card>
      ))}
    </>
  );
}

// ---------------------------------------------------------------- pages

function Section({ title, onOpen, children }: { title: string; onOpen?: () => void; children: ReactNode }) {
  return (
    <Card title={onOpen ? <button className="hover:text-accent transition-colors" onClick={onOpen}>{title}</button> : title} flush={false}>
      {children}
    </Card>
  );
}

export default function HealthTab({ deviceId, components, services, range, sub, onSub }: {
  deviceId: number; components: Component[]; services: Service[]; range: string; sub: HealthSub; onSub: (s: HealthSub) => void;
}) {
  const { byId } = usePresets();
  const names = useMetricNames(deviceId);
  const cpu = cpuInfo(components);
  const stats = components.find((c) => c.kind === "system_stats");
  const mempool = components.find((c) => c.kind === "mempool");
  const storage = components.filter((c) => c.kind === "storage");
  const disks = components.filter((c) => c.kind === "disk");
  const temps = sensorsOf(components, "temperature");
  const fans = sensorsOf(components, "fan");
  const items: [HealthSub, string, string][] = ([
    ["overview", "Overview", "grid"],
    ...(cpu.threads ? [["processor", "Processor", "server"]] : []),
    ...(stats || mempool ? [["memory", "Memory", "sliders"]] : []),
    ...(storage.length ? [["storage", "Storage", "list"]] : []),
    ...(disks.length ? [["diskio", "Disk I/O", "pulse"]] : []),
    ...(temps.length ? [["temperature", "Temperature", "alert"]] : []),
    ...(fans.length ? [["fanspeed", "Fan speed", "refresh"]] : []),
  ] as [HealthSub, string, string][]);
  if (items.length === 1) return <Card><Empty>No health components discovered</Empty></Card>;
  const fmtPct = FORMATS.pct;

  return (
    <div className="space-y-4">
      <SubNav value={sub} onChange={onSub} items={items} />

      {sub === "overview" && (
        <div className="grid xl:grid-cols-2 gap-4">
          <div className="space-y-4">
            {cpu.threads > 0 && (
              <Section title="Processors" onOpen={() => onSub("processor")}>
                <div className="flex flex-wrap items-center gap-x-3 gap-y-1 mb-3">
                  <span className="text-sm font-semibold text-strong">{cpu.model ?? "Processor"}</span>
                  <span className="pill text-xxs px-2 py-0.5 bg-chip border-line text-fg2">× {cpu.threads} threads</span>
                  {cpu.cores > 0 && <span className="pill text-xxs px-2 py-0.5 bg-chip border-line text-fg2">{cpu.cores} cores</span>}
                </div>
                <Bar wide pct={cpu.avg} {...limitsOf(services, null, "cpu_util")} />
                <div className="mt-3"><MetricChart deviceId={deviceId} range={range} metrics={[{ name: "cpu_util", label: "CPU" }]} format={fmtPct} height={140} /></div>
              </Section>
            )}
            {(stats?.values.mem_total || mempool) && (
              <Section title="Memory" onOpen={() => onSub("memory")}>
                {stats?.values.mem_total ? <MemoryBreakdown stats={stats} /> : <Bar pct={mempool!.values.pct} />}
              </Section>
            )}
            {storage.length > 0 && (
              <Section title="Storage" onOpen={() => onSub("storage")}>
                <table className="tbl -mx-4 -mb-4 w-[calc(100%+2rem)]"><tbody>
                  {storage.map((c) => (
                    <tr key={c.id}>
                      <td className="text-strong font-medium truncate max-w-[10rem]" title={c.name}>{c.name}</td>
                      <td><Bar wide pct={c.values.pct} {...limitsOf(services, c.id)} /></td>
                      <td className={`text-xs text-muted text-right whitespace-nowrap ${hideSm}`}>{fmtBytes(c.values.used)} / {fmtBytes(c.values.size)}</td>
                    </tr>
                  ))}
                </tbody></table>
              </Section>
            )}
          </div>
          <div className="space-y-4">
            {temps.length > 0 && <SensorTable items={temps} services={services} unit="celsius" range={range} deviceId={deviceId} />}
            {fans.length > 0 && <SensorTable items={fans} services={services} unit="rpm" range={range} deviceId={deviceId} />}
          </div>
        </div>
      )}

      {sub === "processor" && (
        <>
          <Card title="Processor" flush={false}>
            <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
              <span className="text-base font-semibold text-strong">{cpu.model ?? "Processor"}</span>
              <span className="pill text-xxs px-2 py-0.5 bg-chip border-line text-fg2">× {cpu.threads} threads</span>
              {cpu.cores > 0 && <span className="pill text-xxs px-2 py-0.5 bg-chip border-line text-fg2">{cpu.cores} physical cores</span>}
              <span className="text-xs text-muted">average {cpu.avg == null ? "–" : fmtPct(cpu.avg)}</span>
            </div>
          </Card>
          <PresetGrid deviceId={deviceId} names={names} range={range} ids={["cpu", "load", "cpu_detail", "cpu_extended"]} />
          <Card title={`Processors · ${cpu.threads} threads`} flush={false}>
            <MultiChart deviceId={deviceId} components={cpu.cpus} metric="load" range={range} format={fmtPct} height={260} />
          </Card>
          <Card title="Per thread">
            <div className="grid sm:grid-cols-2 xl:grid-cols-3 gap-x-6 gap-y-1 p-4">
              {cpu.cpus.map((c) => (
                <div key={c.id} className="flex items-center gap-3 text-xs">
                  <span className="w-14 text-muted shrink-0">{c.name}</span><Bar wide pct={c.values.load} {...limitsOf(services, c.id)} />
                </div>
              ))}
            </div>
          </Card>
        </>
      )}

      {sub === "memory" && (
        <>
          {stats?.values.mem_total ? (
            <Card title="Memory" flush={false}>
              <MemoryBreakdown stats={stats} />
              <div className="border-t border-line mt-4 pt-3">
                <div className="text-xs font-semibold text-strong mb-1.5">Swap device</div>
                <SwapDevices stats={stats} />
              </div>
            </Card>
          ) : mempool && <Card title="Memory" flush={false}><Bar pct={mempool.values.pct} /></Card>}
          <PresetGrid deviceId={deviceId} names={names} range={range} ids={["mem_detail", "mem_usage", "swap_usage", "swap_io"]} />
          {!stats?.values.mem_total && mempool && byId("memory") && (
            <PresetCard deviceId={deviceId} preset={byId("memory")!} componentId={mempool.id} range={range} ruler={100} />
          )}
        </>
      )}

      {sub === "storage" && (
        <>
          <Card title="Filesystem usage" flush={false}>
            <MultiChart deviceId={deviceId} components={storage} metric="used_pct" range={range} format={fmtPct} height={240} />
          </Card>
          <StorageTable deviceId={deviceId} storage={storage} range={range} services={services} />
          <PresetGrid deviceId={deviceId} names={names} range={range} ids={["system_io"]} />
        </>
      )}

      {sub === "diskio" && (
        <div className="space-y-4">
          {disks.map((d) => (
            <div key={d.id} className="space-y-2">
              <div className="flex flex-wrap items-center gap-2">
                <span className="text-sm font-semibold text-strong font-mono">{d.name}</span>
                {d.attrs.model && <span className="text-xs text-muted">{d.attrs.model}</span>}
                {d.attrs.size && <span className="text-xs text-muted">· {d.attrs.size}</span>}
                {d.attrs.optane && <span className="pill pill-ok text-xxs px-2 py-0.5">Intel Optane</span>}
                {d.attrs.swap && <span className="pill text-xxs px-2 py-0.5 bg-ns-purple/[.12] border-ns-purple/40 text-ns-purple">swap</span>}
              </div>
              <div className="grid lg:grid-cols-2 gap-4">
                {(["disk_io", "disk_ops"] as const).map((id) => byId(id) && (
                  <PresetCard key={id} deviceId={deviceId} preset={byId(id)!} componentId={d.id} range={range} height={180} />
                ))}
              </div>
            </div>
          ))}
        </div>
      )}

      {sub === "temperature" && (
        <>
          <Card title="Temperature" flush={false}>
            <MultiChart deviceId={deviceId} components={temps} metric="value" range={range} format={FORMATS.celsius} height={280} />
          </Card>
          <SensorTable items={temps} services={services} unit="celsius" range={range} deviceId={deviceId} />
        </>
      )}

      {sub === "fanspeed" && (
        <>
          <Card title="Fan speed" flush={false}>
            <MultiChart deviceId={deviceId} components={fans} metric="value" range={range} format={FORMATS.rpm} height={240} />
          </Card>
          <SensorTable items={fans} services={services} unit="rpm" range={range} deviceId={deviceId} />
        </>
      )}
    </div>
  );
}

/** Filesystems with sizes; expanding one shows its used space in bytes, scaled to the filesystem size. */
function StorageTable({ deviceId, storage, range, services }: { deviceId: number; storage: Component[]; range: string; services: Service[] }) {
  const [open, setOpen] = useState<number | null>(null);
  return (
    <Card title="Filesystems">
      <table className="tbl">
        <thead><tr><th>Mountpoint</th><th className={hideSm}>Size</th><th className={hideSm}>Used</th><th className={hideSm}>Free</th><th>Usage</th></tr></thead>
        <tbody>
          {storage.map((c) => (
            <Fragment key={c.id}>
              <tr className="cursor-pointer" onClick={() => setOpen(open === c.id ? null : c.id)}>
                <td className="text-strong font-medium">
                  <div className="flex items-center gap-2">
                    <Icon name="chevron" className={`w-3.5 h-3.5 text-muted transition-transform ${open === c.id ? "rotate-90" : ""}`} />
                    <span className="truncate max-w-[14rem]" title={c.name}>{c.name}</span>
                  </div>
                </td>
                <td className={`text-xs tabular-nums ${hideSm}`}>{fmtBytes(c.values.size)}</td>
                <td className={`text-xs tabular-nums ${hideSm}`}>{fmtBytes(c.values.used)}</td>
                <td className={`text-xs tabular-nums ${hideSm}`}>{c.values.size != null ? fmtBytes(c.values.size - (c.values.used ?? 0)) : "–"}</td>
                <td className="w-[45%]"><Bar wide pct={c.values.pct} {...limitsOf(services, c.id)} /></td>
              </tr>
              {open === c.id && (
                <tr><td colSpan={5} className="bg-inset/40">
                  <MetricChart deviceId={deviceId} componentId={c.id} range={range} format={FORMATS.bytes} height={200}
                    metrics={[{ name: "used_bytes", label: "used" }]} ruler={c.values.size} rulerLabel="size" />
                </td></tr>
              )}
            </Fragment>
          ))}
        </tbody>
      </table>
    </Card>
  );
}
