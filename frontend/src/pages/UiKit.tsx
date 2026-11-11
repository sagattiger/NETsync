/** Dev-only page (/ui-kit): every widget look with fake data, to compare with docs/design/netsync-ui-kit.svg.
 *  Only routed in dev builds or when built with VITE_UI_KIT=1 (see routes.tsx). */
import { ReactNode, useMemo, useState } from "react";
import { fmtBps, Heartbeat, Series } from "../api";
import { Donut, Gauge, HBars, Kpi, nsVar, Ring, STATE_VARS } from "../components/Charts";
import { TimeChart } from "../components/MetricChart";
import { PageHeader, Page } from "../components/Layout";
import { Segmented, StateBadge, WidgetHead } from "../components/ui";
import { ChartStyle, CHART_STYLES } from "../lib/chartTheme";
import { HeartbeatBar, StatusPill } from "./probes/shared";
import { FORMATS } from "../presets";

const HOUR = 3_600_000;

/** Deterministic pseudo-random walk so the page looks the same on every load. */
function walk(seed: number, n: number, base: number, amp: number, gapAt?: number): [string, number, number, number][] {
  let x = seed;
  const rnd = () => ((x = (x * 9301 + 49297) % 233280) / 233280);
  const t0 = Date.now() - 24 * HOUR;
  return Array.from({ length: n }, (_, i) => {
    const wave = Math.sin(i / 6 + seed) * amp * 0.6 + Math.sin(i / 2.3) * amp * 0.2;
    const avg = Math.max(0, base + wave + (rnd() - 0.5) * amp * 0.15);
    const spread = amp * (0.15 + rnd() * 0.5);
    const v: [string, number, number, number] = [new Date(t0 + (i * 24 * HOUR) / n).toISOString(), avg, Math.max(0, avg - spread * rnd()), avg + spread];
    return gapAt != null && i >= gapAt && i < gapAt + 3 ? [v[0], null as unknown as number, null as unknown as number, null as unknown as number] : v;
  });
}

function Box({ title, dot, cols = "xl:col-span-4", children }: { title: string; dot?: string; cols?: string; children: ReactNode }) {
  return (
    <section className={`card col-span-1 md:col-span-6 ${cols}`}>
      <WidgetHead lead={<span className="dot glow" style={{ background: dot ?? nsVar("orange"), color: dot ?? nsVar("orange") }} />} title={title}
        right={<span className="px-1.5 text-lg leading-none text-muted">⋯</span>} />
      <div className="overflow-hidden rounded-b-2xl">{children}</div>
    </section>
  );
}

export default function UiKit() {
  const [style, setStyle] = useState<ChartStyle>("area");
  const traffic: Series = useMemo(() => ({ in: walk(3, 48, 260e6, 140e6, 34), out: walk(7, 48, 180e6, 90e6, 34), peers: walk(11, 48, 80e6, 40e6) }), []);
  const spikes: Series = useMemo(() => ({ errors: walk(5, 48, 12, 30).map(([t, a, b, c], i) => [t, i % 9 === 4 ? a * 4 : a, b, c]) }), []);
  const jitter: Series = useMemo(() => ({ rtt: walk(2, 40, 3.2, 2.4) }), []);
  const beats: Heartbeat[] = useMemo(() => Array.from({ length: 100 }, (_, i) => ({
    time: new Date(Date.now() - (100 - i) * 60_000).toISOString(),
    state: [61, 62, 89].includes(i) ? 1 : [63, 92].includes(i) ? 2 : i === 38 ? 3 : 0,
    response_ms: 150 + (i % 7) * 9, message: null, maintenance: false,
  })), []);
  const mbps = (v: number) => fmtBps(v);
  const ms = FORMATS.ms;

  return (
    <>
      <PageHeader title="UI kit" sub="Every widget with fake data · compare with docs/design/netsync-ui-kit.svg"
        actions={<Segmented value={style} onChange={setStyle} options={CHART_STYLES} />} />
      <Page>
        <div className="flex flex-wrap gap-3">
          {["pink", "orange", "purple", "amber", "teal", "red", "green", "grey"].map((n) => (
            <span key={n} className="inline-flex items-center gap-2 text-xs text-muted">
              <span className="w-5 h-5 rounded-md border border-line" style={{ background: nsVar(n) }} />{n}
            </span>
          ))}
        </div>
        <div className="grid grid-cols-1 md:grid-cols-6 xl:grid-cols-12 gap-4">
          <Box title="Network traffic" cols="xl:col-span-6">
            <div className="px-3 pb-3">
              <TimeChart data={traffic} metrics={[{ name: "in", label: "in" }, { name: "out", label: "out" }, { name: "peers", label: "peers" }]}
                format={mbps} height={260} style={style} />
            </div>
          </Box>
          <Box title="Active alerts" dot={nsVar("amber")} cols="xl:col-span-3">
            <div className="px-4 pb-4 pt-1">
              <Donut center={12} caption="open" items={[
                { label: "warning", value: 7, color: STATE_VARS[1] }, { label: "critical", value: 5, color: STATE_VARS[2] }]} />
            </div>
          </Box>
          <Box title="CPU load" dot={nsVar("purple")} cols="xl:col-span-3">
            <div className="px-4 pb-4 pt-1"><Gauge value={87} warn={90} crit={95} text="87%" label="CPU" /></div>
          </Box>

          <Box title="Traffic spikes" dot={nsVar("pink")} cols="xl:col-span-3">
            <div className="px-3 pb-3"><TimeChart data={spikes} metrics={[{ name: "errors", label: "errors" }]} colors={["#FF58AE"]}
              format={FORMATS.rate} height={200} style="spike" /></div>
          </Box>
          <Box title="Packet loss / jitter" dot={nsVar("teal")} cols="xl:col-span-6">
            <div className="px-3 pb-3"><TimeChart data={jitter} metrics={[{ name: "rtt", label: "RTT" }]} format={ms} height={200} style="range" /></div>
          </Box>
          <Box title="Bandwidth" cols="xl:col-span-3">
            <div className="px-4 pb-4 pt-1">
              <HBars items={[["ether1", 84e6], ["ether2", 72e6], ["sfp1", 63e6], ["wlan", 48e6], ["vpn", 36e6]].map(([label, v]) => ({ label: label as string, value: v as number, text: fmtBps(v as number) }))} />
            </div>
          </Box>

          <Box title="Node health" dot={nsVar("teal")} cols="xl:col-span-6">
            <div className="flex flex-wrap justify-around gap-4 px-4 pb-5 pt-2">
              <Ring value={74} label="pve001" color={nsVar("teal")} size={112} />
              <Ring value={48} label="pve002" color={nsVar("orange")} size={112} />
              <Ring value={92} label="pve003" color={nsVar("purple")} size={112} />
            </div>
          </Box>
          <Box title="Uptime" dot={nsVar("green")} cols="xl:col-span-3">
            <Kpi text="99.98%" caption="last 30 days" spark={[99.9, 100, 100, 99.95, 100, 99.99, 100, 100]} color={nsVar("green")} />
          </Box>
          <Box title="Data" dot={nsVar("purple")} cols="xl:col-span-3">
            <Kpi text="1.2 TB" caption="transferred today" spark={[3, 4, 6, 5, 7, 8, 7, 9]} color={nsVar("purple")} />
          </Box>
          <Box title="Latency" dot={nsVar("orange")} cols="xl:col-span-3">
            <Kpi text="4.3 ms" caption="Google DNS" spark={[5, 3, 4, 6, 3, 4, 2, 3]} />
          </Box>

          <Box title="Heartbeat · last 100 checks" dot={nsVar("green")} cols="xl:col-span-9">
            <div className="px-4 pb-4 pt-1 space-y-3">
              <HeartbeatBar beats={beats} height="h-[38px]" />
              <div className="flex flex-wrap items-baseline gap-x-2.5 gap-y-1 text-xs text-muted">
                <span>24 h <b className="text-strong tabular-nums">99.98%</b></span><span className="text-faint">·</span>
                <span>7 d <b className="text-strong tabular-nums">99.90%</b></span><span className="text-faint">·</span>
                <span>30 d <b className="text-strong tabular-nums">99.95%</b></span><span className="text-faint">·</span>
                <span>cert <b className="text-warn tabular-nums">12 days</b></span><span className="text-faint">·</span>
                <span>HTTP 200</span><span className="text-faint">·</span><span className="tabular-nums">182 ms</span>
              </div>
            </div>
          </Box>
          <Box title="Status" dot={nsVar("green")} cols="xl:col-span-12">
            <div className="px-4 pb-4 pt-1 space-y-4">
              <div className="flex flex-wrap gap-2">
                <StateBadge state={0} label="Operational" /><StateBadge state={1} label="Warning" />
                <StateBadge state={2} label="Critical" /><StateBadge state={3} label="No data" />
              </div>
              <div className="flex flex-wrap gap-2">
                <StatusPill enabled state={0} /><StatusPill enabled state={1} /><StatusPill enabled state={2} />
                <StatusPill enabled state={3} /><StatusPill enabled maintenance state={0} /><StatusPill enabled={false} state={0} />
              </div>
            </div>
          </Box>
        </div>
      </Page>
    </>
  );
}
