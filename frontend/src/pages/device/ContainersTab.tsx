/** Docker containers of a host (netsync-docker SNMP extend, docs/DOCKER.md): state, health, CPU, memory, ports. */
import { useState } from "react";
import { Component, fmtBytes, Service } from "../../api";
import { Card, Empty, hideMd, hideSm, StateBadge } from "../../components/ui";
import { FORMATS } from "../../presets";
import { MultiChart } from "./charts";

const pct = FORMATS.pct;

export default function ContainersTab({ deviceId, components, services, range }: {
  deviceId: number; components: Component[]; services: Service[]; range: string;
}) {
  const [q, setQ] = useState("");
  const all = components.filter((c) => c.kind === "container").sort((a, b) =>
    String(a.attrs.project ?? "").localeCompare(String(b.attrs.project ?? "")) || a.name.localeCompare(b.name));
  if (!all.length) return <Card><Empty>No containers found. Set up the netsync-docker extend on this host (docs/DOCKER.md).</Empty></Card>;
  const rows = all.filter((c) => !q || `${c.name} ${c.attrs.image ?? ""} ${c.attrs.project ?? ""}`.toLowerCase().includes(q.toLowerCase()));
  const svc = (c: Component) => services.find((s) => s.component_id === c.id);
  const running = all.filter((c) => c.values.state === "running");
  const data = services.find((s) => s.name === "Docker data");

  return (
    <div className="space-y-4">
      <Card title={`Containers · ${running.length} running of ${all.length}`}
        actions={<input className="input py-1.5 text-xs w-44" placeholder="Filter…" value={q} onChange={(e) => setQ(e.target.value)} />}>
        <div className="overflow-x-auto">
          <table className="tbl">
            <thead><tr>
              <th>Container</th><th className={hideSm}>Image</th><th>State</th><th className={hideMd}>Ports</th>
              <th className="text-right">CPU</th><th className="text-right">Memory</th>
            </tr></thead>
            <tbody>
              {rows.map((c) => {
                const s = svc(c);
                const v = c.values;
                return (
                  <tr key={c.id}>
                    <td className="max-w-[16rem]">
                      <div className="font-medium text-strong truncate" title={c.name}>{c.name}</div>
                      {(c.attrs.project || c.attrs.coolify) && (
                        <div className="text-xxs text-muted truncate">{[c.attrs.coolify, c.attrs.project, c.attrs.service].filter(Boolean).join(" · ")}</div>
                      )}
                    </td>
                    <td className={`text-xs text-fg2 truncate max-w-[16rem] ${hideSm}`} title={c.attrs.image as string}>{c.attrs.image as string}</td>
                    <td className="whitespace-nowrap">
                      {s ? <StateBadge state={s.state} small label={v.state as string} /> : <span className="text-xs text-muted">{v.state as string ?? "–"}</span>}
                      <div className="text-xxs text-muted truncate max-w-[12rem]" title={v.status as string}>{v.status as string}</div>
                    </td>
                    <td className={`text-xs font-mono text-fg2 max-w-[14rem] truncate ${hideMd}`} title={v.ports as string}>
                      {(v.ports as string || "").replace(/, (?:::|\[::\]):\d+(?:-\d+)?->\d+(?:-\d+)?\/\w+/g, "") || "–"}
                    </td>
                    <td className="text-right tabular-nums text-xs">{v.cpu_pct != null ? pct(v.cpu_pct as number) : "–"}</td>
                    <td className="text-right tabular-nums text-xs whitespace-nowrap">
                      {v.mem_bytes != null ? fmtBytes(v.mem_bytes as number) : "–"}
                      {v.mem_pct != null && <span className="text-muted"> · {pct(v.mem_pct as number)}</span>}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
        {data && <div className="px-4 py-2 text-xxs text-muted">{data.output}</div>}
      </Card>
      {running.length > 0 && (
        <div className="grid xl:grid-cols-2 gap-4">
          <Card title="CPU per container" flush={false}>
            <MultiChart deviceId={deviceId} components={running} metric="cpu_pct" range={range} format={pct} height={240} />
          </Card>
          <Card title="Memory per container" flush={false}>
            <MultiChart deviceId={deviceId} components={running} metric="mem_bytes" range={range} format={fmtBytes} height={240} />
          </Card>
        </div>
      )}
    </div>
  );
}
