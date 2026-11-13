/** Device → Ports: one row per port with traffic, utilisation, packets, speed/MTU, MAC and addresses
 *  (like Observium's port list), filters, and a graphs view. */
import { Fragment, useMemo, useState } from "react";
import { Component, fmtBps } from "../../api";
import { AddToDashboard } from "../../components/AddToDashboard";
import { Icon } from "../../components/Icon";
import { MetricChart } from "../../components/MetricChart";
import { Card, Empty, hideLg, hideMd, hideSm } from "../../components/ui";
import { usePresets } from "../../presets";

const PORT_GRAPHS = ["port_packets", "port_nucast", "port_pkt_size", "port_util"];

/** IANA ifType → what the port is */
const IF_TYPES: Record<number, string> = {
  1: "Other", 6: "Ethernet", 23: "PPP", 24: "Loopback", 53: "Virtual", 71: "Wi-Fi", 131: "Tunnel", 135: "VLAN",
  136: "VLAN", 161: "Bond (LAG)", 166: "MPLS", 209: "Bridge", 117: "Gigabit Ethernet", 62: "Fast Ethernet",
  150: "MPLS tunnel", 244: "WWAN", 237: "LTE",
};

type Status = "up" | "down" | "admin";
const statusOf = (p: Component): Status => (p.values.admin === 2 ? "admin" : p.values.oper === 1 ? "up" : "down");
const STRIPE: Record<Status, string> = { up: "bg-ok", down: "bg-crit", admin: "bg-faint" };
const LABEL: Record<Status, string> = { up: "up", down: "down", admin: "admin down" };

function fmtPps(v: number | null | undefined) {
  if (v == null) return "-";
  return v >= 1000 ? `${(v / 1000).toFixed(1)}k pps` : `${v < 10 ? v.toFixed(1) : Math.round(v)} pps`;
}
const pct = (v: number | null | undefined) => (v == null ? "-" : `${v < 10 ? v.toFixed(1) : Math.round(v)}%`);
const natural = (a: string, b: string) => a.localeCompare(b, undefined, { numeric: true, sensitivity: "base" });

function InOut({ dIn, dOut, warn }: { dIn: string; dOut: string; warn?: boolean }) {
  return (
    <div className={`text-xs tabular-nums leading-5 whitespace-nowrap ${warn ? "text-warn" : ""}`}>
      <div><Icon name="arrow" className="w-3 h-3 inline rotate-90 text-ok mr-1 align-[-1px]" />{dIn}</div>
      <div><Icon name="arrow" className="w-3 h-3 inline -rotate-90 text-accent mr-1 align-[-1px]" />{dOut}</div>
    </div>
  );
}

function PortGraphs({ deviceId, port, range }: { deviceId: number; port: Component; range: string }) {
  const { byId } = usePresets();
  return (
    <>
      <div className="flex justify-end -mb-2">
        <AddToDashboard deviceId={deviceId} preset="port_traffic" componentId={port.id} />
      </div>
      <div className="grid lg:grid-cols-2 gap-6 py-2">
        <div>
          <div className="text-xs text-muted mb-1">Traffic</div>
          <MetricChart deviceId={deviceId} componentId={port.id} range={range} format={fmtBps}
            metrics={[{ name: "in_bps", label: "in" }, { name: "out_bps", label: "out" }]} ruler={port.attrs.speed || null} rulerLabel="link" />
        </div>
        <div>
          <div className="text-xs text-muted mb-1">Errors & discards per second</div>
          <MetricChart deviceId={deviceId} componentId={port.id} range={range} area={false} format={(x) => x.toFixed(2)}
            metrics={[{ name: "in_errors" }, { name: "out_errors" }, { name: "in_discards" }, { name: "out_discards" }]} />
        </div>
        {PORT_GRAPHS.map((gid) => {
          const g = byId(gid);
          return g && (
            <div key={gid}>
              <div className="text-xs text-muted mb-1">{g.label}</div>
              <MetricChart deviceId={deviceId} componentId={port.id} range={range} area={g.area} format={g.format}
                metrics={g.metrics} ruler={gid === "port_util" ? 100 : null} rulerLabel="link" />
            </div>
          );
        })}
      </div>
    </>
  );
}

export default function PortsTab({ deviceId, ports, range }: { deviceId: number; ports: Component[]; range: string }) {
  const [open, setOpen] = useState<number | null>(null);
  const [filter, setFilter] = useState("");
  const [show, setShow] = useState<"all" | Status | "errors">("all");
  const [sort, setSort] = useState<"name" | "traffic">("name");
  const [view, setView] = useState<"list" | "graphs">("list");

  const counts = useMemo(() => {
    const c = { all: ports.length, up: 0, down: 0, admin: 0, errors: 0 };
    for (const p of ports) {
      c[statusOf(p)] += 1;
      if (hasErrors(p)) c.errors += 1;
    }
    return c;
  }, [ports]);

  const rows = useMemo(() => {
    const q = filter.toLowerCase();
    return ports
      .filter((p) => !q || `${p.name} ${p.descr ?? ""} ${p.attrs.mac ?? ""} ${(p.attrs.ipv4 ?? []).join(" ")} ${(p.attrs.ipv6 ?? []).join(" ")}`.toLowerCase().includes(q))
      .filter((p) => show === "all" || (show === "errors" ? hasErrors(p) : statusOf(p) === show))
      .sort((a, b) => sort === "traffic"
        ? ((b.values.in_bps ?? 0) + (b.values.out_bps ?? 0)) - ((a.values.in_bps ?? 0) + (a.values.out_bps ?? 0))
        : natural(a.name, b.name));
  }, [ports, filter, show, sort]);

  if (!ports.length) return <Card><Empty>No ports discovered</Empty></Card>;

  const chip = (key: typeof show, label: string, n: number) => (
    <button key={key} onClick={() => setShow(key)}
      className={`px-2.5 h-7 rounded-md text-xs whitespace-nowrap ${show === key ? "bg-active text-strong font-medium" : "text-muted hover:text-fg"}`}>
      {label} <span className="text-faint tabular-nums">{n}</span>
    </button>
  );

  return (
    <Card title={`Ports · ${ports.length}`} actions={
      <div className="flex flex-wrap items-center gap-2">
        <div className="hidden md:flex items-center">
          {chip("all", "All", counts.all)}{chip("up", "Up", counts.up)}{chip("down", "Down", counts.down)}
          {chip("admin", "Disabled", counts.admin)}{chip("errors", "Errors", counts.errors)}
        </div>
        <select className="input h-7 py-0 text-xs" value={sort} onChange={(e) => setSort(e.target.value as typeof sort)} title="Sort">
          <option value="name">By name</option><option value="traffic">By traffic</option>
        </select>
        <div className="seg">
          <button className={view === "list" ? "bg-seg-active text-on-seg-active" : ""} onClick={() => setView("list")}>List</button>
          <button className={view === "graphs" ? "bg-seg-active text-on-seg-active" : ""} onClick={() => setView("graphs")}>Graphs</button>
        </div>
        <input className="input py-1 text-xs w-36 sm:w-48" placeholder="Filter name, IP, MAC…" value={filter} onChange={(e) => setFilter(e.target.value)} />
      </div>
    }>
      {view === "graphs" ? (
        <div className="grid md:grid-cols-2 2xl:grid-cols-3 gap-4 p-4">
          {rows.slice(0, 60).map((p) => (
            <div key={p.id} className="border border-line rounded-lg p-3">
              <div className="flex items-center gap-2 text-sm mb-1">
                <span className={`w-2 h-2 rounded-full ${STRIPE[statusOf(p)]}`} />
                <span className="font-medium text-strong">{p.name}</span>
                <span className="text-xs text-muted truncate">{p.descr ?? ""}</span>
                <span className="flex-1" />
                <span className="text-xs text-muted tabular-nums">{fmtBps(p.values.in_bps)} / {fmtBps(p.values.out_bps)}</span>
              </div>
              <MetricChart deviceId={deviceId} componentId={p.id} range={range} format={fmtBps} height={120} compact
                metrics={[{ name: "in_bps", label: "in" }, { name: "out_bps", label: "out" }]} />
            </div>
          ))}
          {rows.length > 60 && <div className="text-xs text-muted">Showing the first 60; filter to see others.</div>}
        </div>
      ) : (
        <table className="tbl">
          <thead><tr>
            <th className="w-1 p-0" /><th>Port</th><th>Traffic</th><th className={hideSm}>Utilisation</th>
            <th className={hideMd}>Packets</th><th className={hideMd}>Speed / MTU</th><th className={hideLg}>Type / MAC</th>
          </tr></thead>
          <tbody>
            {rows.map((p) => {
              const v = p.values, a = p.attrs, st = statusOf(p);
              const v6 = (a.ipv6 ?? []).filter((x: string) => !x.toLowerCase().startsWith("fe80"));
              const errs = errorRate(p);
              const busy = Math.max(v.in_util ?? 0, v.out_util ?? 0) >= 80;
              return (
                <Fragment key={p.id}>
                  <tr className="cursor-pointer align-top" onClick={() => setOpen(open === p.id ? null : p.id)}>
                    <td className="p-0"><span className={`block w-1 min-h-[2.75rem] h-full ${STRIPE[st]}`} title={LABEL[st]} /></td>
                    <td className="min-w-[12rem]">
                      <div className="flex items-center gap-2">
                        <span className="font-medium text-strong">{p.name}</span>
                        {v6.length > 0 && <span className="pill text-[10px] px-1.5 py-0 bg-accent/15 border-accent/30 text-accent" title={v6.join("\n")}>IPv6</span>}
                        {st !== "up" && <span className={`text-[10px] ${st === "down" ? "text-crit" : "text-muted"}`}>{LABEL[st]}</span>}
                        {errs > 0 && <span className="text-[10px] text-crit" title="errors + discards per second">⚠ {errs.toFixed(errs < 10 ? 1 : 0)}/s errors</span>}
                        <Icon name="chevron" className={`w-3 h-3 text-muted transition-transform ${open === p.id ? "rotate-90" : ""}`} />
                      </div>
                      {p.descr && <div className="text-xs text-fg2 mt-0.5">{p.descr}</div>}
                      {(a.ipv4 ?? []).length > 0 && <div className="text-xs text-muted font-mono mt-0.5">{a.ipv4.join(", ")}</div>}
                      {v6.length > 0 && <div className={`text-xs text-muted font-mono mt-0.5 truncate max-w-[22rem] ${hideMd}`} title={v6.join("\n")}>{v6[0]}{v6.length > 1 ? ` +${v6.length - 1}` : ""}</div>}
                    </td>
                    <td><InOut dIn={fmtBps(v.in_bps)} dOut={fmtBps(v.out_bps)} /></td>
                    <td className={hideSm}><InOut dIn={pct(v.in_util)} dOut={pct(v.out_util)} warn={busy} /></td>
                    <td className={hideMd}><InOut dIn={fmtPps(v.in_pps)} dOut={fmtPps(v.out_pps)} /></td>
                    <td className={`text-xs leading-5 whitespace-nowrap ${hideMd}`}>
                      <div className="text-strong">{a.speed ? fmtBps(a.speed).replace(".0 ", " ") : "-"}</div>
                      <div className="text-muted">{a.mtu ?? "-"}</div>
                    </td>
                    <td className={`text-xs leading-5 ${hideLg}`}>
                      <div className="text-strong">{IF_TYPES[a.if_type] ?? (a.if_type ? `type ${a.if_type}` : "-")}</div>
                      <div className="text-muted font-mono">{a.mac ?? ""}</div>
                    </td>
                  </tr>
                  {open === p.id && (
                    <tr><td colSpan={7} className="bg-inset/40"><PortGraphs deviceId={deviceId} port={p} range={range} /></td></tr>
                  )}
                </Fragment>
              );
            })}
          </tbody>
        </table>
      )}
    </Card>
  );
}

function errorRate(p: Component): number {
  const v = p.values;
  return (v.in_errors_rate ?? 0) + (v.out_errors_rate ?? 0) + (v.in_discards_rate ?? 0) + (v.out_discards_rate ?? 0);
}
const hasErrors = (p: Component) => errorRate(p) > 0;
