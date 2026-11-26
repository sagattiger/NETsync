/** Settings → General → Discovery: tick what was found on your devices to ignore it, instead of writing rules by hand.
 * Each tick adds (or removes) one line in the existing ignore settings; nothing is saved until Save is pressed. */
import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "../../api";
import { Modal } from "../../components/ui";

interface Choice {
  key: string; label: string; hint?: string; field: string; rule: string;
  count: number; device_count: number; device_names: string[]; examples: string[]; all_ignored: boolean;
}
type Group = Record<string, Choice[]>;
type Found = Record<"port" | "storage" | "processor" | "sensor", Group>;
export type PickerKind = keyof Found;

const KIND = {
  port: { title: "ports", noun: ["port", "ports"], tabs: [["patterns", "By name pattern"], ["types", "By type"], ["names", "By name"]] },
  storage: { title: "storage", noun: ["volume", "volumes"], tabs: [["names", "By name"], ["patterns", "By pattern"]] },
  processor: { title: "processors", noun: ["processor", "processors"], tabs: [["patterns", "By pattern"], ["names", "By name"]] },
  sensor: { title: "sensors", noun: ["sensor", "sensors"], tabs: [["patterns", "By pattern"], ["names", "By name"]] },
} as const;

export const PICKER_SECTIONS: Record<string, PickerKind> = {
  "Port discovery": "port", "Storage discovery": "storage", "Processor discovery": "processor", "Sensor discovery": "sensor",
};

/** Whether this rule is already in the (unsaved) settings. */
function has(config: Record<string, any>, field: string, rule: string): boolean {
  const v = config[field];
  return Array.isArray(v) ? v.includes(rule) : String(v ?? "").split("\n").some((l) => l.trim() === rule);
}

function toggled(config: Record<string, any>, field: string, rule: string, on: boolean): any {
  const v = config[field];
  if (Array.isArray(v) || field.endsWith("_types")) {
    const list: string[] = Array.isArray(v) ? v : [];
    return on ? [...new Set([...list, rule])] : list.filter((x) => x !== rule);
  }
  const lines = String(v ?? "").split("\n").map((l) => l.trim()).filter(Boolean);
  return (on ? [...new Set([...lines, rule])] : lines.filter((l) => l !== rule)).join("\n");
}

export function IgnorePickerButton({ kind, config, set }: { kind: PickerKind; config: Record<string, any>; set: (k: string, v: any) => void }) {
  const [open, setOpen] = useState(false);
  return (
    <>
      <button type="button" className="btn w-full justify-center" onClick={() => setOpen(true)}>
        Choose {KIND[kind].title} to ignore from what was discovered…
      </button>
      {open && <IgnorePicker kind={kind} config={config} set={set} onClose={() => setOpen(false)} />}
    </>
  );
}

function IgnorePicker({ kind, config, set, onClose }: { kind: PickerKind; config: Record<string, any>; set: (k: string, v: any) => void; onClose: () => void }) {
  const { data, isLoading, error } = useQuery({ queryKey: ["discovered"], queryFn: () => api<Found>("/plugins/general/discovered"), staleTime: 30_000 });
  const meta = KIND[kind];
  const tabs = meta.tabs.filter(([t]) => (data?.[kind]?.[t]?.length ?? 0) > 0);
  const [tab, setTab] = useState<string>(meta.tabs[0][0]);
  const [q, setQ] = useState("");
  const active = tabs.some(([t]) => t === tab) ? tab : tabs[0]?.[0];
  const rows = useMemo(() => {
    const all = (active && data?.[kind]?.[active]) || [];
    const s = q.trim().toLowerCase();
    return s ? all.filter((c) => [c.label, c.hint, ...c.examples, ...c.device_names].some((x) => x?.toLowerCase().includes(s))) : all;
  }, [data, kind, active, q]);
  const picked = (c: Choice) => has(config, c.field, c.rule);
  const n = (count: number) => `${count} ${meta.noun[count === 1 ? 0 : 1]}`;

  return (
    <Modal title={`Ignore ${meta.title}`} onClose={onClose} wide>
      <p className="text-xs text-muted mb-3">
        Everything discovery has found on your devices. Tick what you don't want to monitor; it's added to the ignore lists
        below. Press <b className="text-strong">Save</b> afterwards: what you ticked is removed right away (with its alerts) and left out of future discoveries.
      </p>
      {isLoading ? <div className="text-sm text-muted py-6 text-center">Loading…</div>
        : error ? <div className="text-sm text-crit">{(error as Error).message}</div>
        : !tabs.length ? <div className="text-sm text-muted py-6 text-center">Nothing discovered yet.</div> : (
        <>
          <div className="flex flex-wrap items-center gap-2 mb-3">
            <div className="flex gap-1" role="tablist">
              {tabs.map(([t, label]) => (
                <button key={t} type="button" role="tab" aria-selected={t === active} onClick={() => setTab(t)}
                  className={`px-2.5 py-1 rounded-md text-xs ${t === active ? "bg-accent/15 text-strong font-medium" : "text-muted hover:text-fg hover:bg-inset"}`}>{label}</button>
              ))}
            </div>
            <input className="input flex-1 min-w-[10rem] text-xs py-1.5" placeholder="Filter…" value={q} onChange={(e) => setQ(e.target.value)} aria-label="Filter" />
          </div>
          <ul className="max-h-[55vh] overflow-y-auto divide-y divide-line border border-line rounded-lg">
            {rows.map((c) => {
              const on = picked(c);
              const done = c.all_ignored && !on;
              return (
                <li key={`${c.field}:${c.rule}`}>
                  <label className={`flex items-start gap-3 px-3 py-2.5 cursor-pointer hover:bg-inset ${on ? "bg-accent/5" : ""}`}>
                    <input type="checkbox" className="mt-0.5" checked={on || done} disabled={done}
                      onChange={(e) => set(c.field, toggled(config, c.field, c.rule, e.target.checked))} />
                    <span className="min-w-0 flex-1">
                      <span className="flex flex-wrap items-baseline gap-x-2">
                        <span className="font-mono text-xs text-strong break-all">{c.label}</span>
                        {c.hint && <span className="text-xs text-fg2">{c.hint}</span>}
                        {done && <span className="text-xxs text-muted">already ignored by your rules</span>}
                      </span>
                      <span className="block text-xs text-muted mt-0.5">
                        {n(c.count)} on {c.device_count} device{c.device_count === 1 ? "" : "s"}: {c.device_names.join(", ")}{c.device_count > c.device_names.length ? "…" : ""}
                        {active !== "names" && c.examples.length > 0 && <> · e.g. <span className="font-mono">{c.examples.join(", ")}</span></>}
                      </span>
                    </span>
                  </label>
                </li>
              );
            })}
            {!rows.length && <li className="px-3 py-4 text-xs text-muted text-center">No match</li>}
          </ul>
        </>
      )}
      <div className="mt-4 flex justify-end"><button className="btn btn-primary" onClick={onClose}>Done</button></div>
    </Modal>
  );
}
