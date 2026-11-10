import { ReactNode, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api, Group, Probe, ProbeKind, ProbeTestResult } from "../../api";
import { Icon } from "../../components/Icon";
import { Modal } from "../../components/ui";
import { fmtMs, KINDS, kindMeta, useMe } from "./shared";

type Cfg = Record<string, any>;
export interface SectionProps {
  cfg: Cfg; setCfg: (patch: Cfg) => void; secrets: Cfg; setSecret: (k: string, v: any) => void;
  saved: Cfg; f: FormState; set: (patch: Partial<FormState>) => void;
}
interface FormState {
  name: string; kind: ProbeKind; target: string; port: number | null; interval_s: number; timeout_s: number;
  retries: number; retry_interval_s: number | null; upside_down: boolean; resend_every: number; count: number;
  enabled: boolean; tags: string[]; description: string; group_ids: number[]; config: Cfg;
}

// --------------------------------------------------------------------------- small inputs

export function Field({ label, hint, children, className = "" }: { label: string; hint?: ReactNode; children: ReactNode; className?: string }) {
  return <div className={className}><label className="label">{label}</label>{children}{hint && <div className="text-xs text-muted mt-1">{hint}</div>}</div>;
}
export function Check({ label, hint, checked, onChange }: { label: string; hint?: ReactNode; checked: boolean; onChange: (v: boolean) => void }) {
  return (
    <label className="flex items-start gap-2.5 cursor-pointer select-none">
      <input type="checkbox" className="mt-0.5" checked={checked} onChange={(e) => onChange(e.target.checked)} />
      <span className="text-sm text-fg">{label}{hint && <span className="block text-xs text-muted">{hint}</span>}</span>
    </label>
  );
}
const num = (v: string, fallback: number | null = null) => (v === "" ? fallback : Number(v));

/** Write-only secret: empty = keep the saved value; "Clear" removes it. */
export function SecretInput({ name, label, saved, secrets, setSecret, multiline }: {
  name: string; label: string; saved: Cfg; secrets: Cfg; setSecret: (k: string, v: any) => void; multiline?: boolean;
}) {
  const isSet = !!saved[`has_${name}`] && secrets[name] !== "";
  const value = typeof secrets[name] === "string" ? secrets[name] : "";
  const props = {
    className: "input w-full font-mono", value, autoComplete: "new-password",
    placeholder: isSet ? "•••••• saved (leave empty to keep)" : "",
    onChange: (e: any) => setSecret(name, e.target.value || undefined),
  };
  return (
    <Field label={label} hint={isSet && <button type="button" className="text-crit hover:underline" onClick={() => setSecret(name, "")}>Clear saved value</button>}>
      {multiline ? <textarea rows={4} {...props} /> : <input type="password" {...props} />}
    </Field>
  );
}

function HeadersEditor({ saved, secrets, setSecret }: { saved: Cfg; secrets: Cfg; setSecret: (k: string, v: any) => void }) {
  const names: string[] = saved.header_names ?? [];
  const [editing, setEditing] = useState(!names.length);
  const [rows, setRows] = useState<{ k: string; v: string }[]>(() =>
    Object.entries((secrets.headers as Record<string, string>) ?? {}).map(([k, v]) => ({ k, v })));
  const commit = (rs: { k: string; v: string }[]) => {
    setRows(rs);
    const dict = Object.fromEntries(rs.filter((r) => r.k.trim()).map((r) => [r.k.trim(), r.v]));
    setSecret("headers", Object.keys(dict).length ? dict : names.length ? "" : undefined);
  };
  if (!editing) {
    return (
      <Field label="Request headers (encrypted)">
        <div className="flex items-center gap-2 text-sm">
          <span className="text-fg2 font-mono text-xs">{names.join(", ")}</span>
          <button type="button" className="btn btn-ghost px-2 py-1 text-xs" onClick={() => { setEditing(true); commit([{ k: "", v: "" }]); }}>Replace</button>
        </div>
      </Field>
    );
  }
  return (
    <Field label="Request headers (encrypted)" hint="Values are stored encrypted and never shown again.">
      <div className="space-y-2">
        {rows.map((r, i) => (
          <div key={i} className="flex gap-2">
            <input className="input w-2/5 font-mono" placeholder="X-Api-Key" value={r.k} onChange={(e) => commit(rows.map((x, j) => (j === i ? { ...x, k: e.target.value } : x)))} />
            <input className="input flex-1 font-mono" type="password" autoComplete="new-password" placeholder="value" value={r.v}
              onChange={(e) => commit(rows.map((x, j) => (j === i ? { ...x, v: e.target.value } : x)))} />
            <button type="button" className="btn btn-ghost px-2" onClick={() => commit(rows.filter((_, j) => j !== i))}><Icon name="x" className="w-3.5 h-3.5" /></button>
          </div>
        ))}
        <button type="button" className="btn btn-ghost px-2 py-1 text-xs" onClick={() => setRows([...rows, { k: "", v: "" }])}><Icon name="plus" className="w-3 h-3" /> Add header</button>
      </div>
    </Field>
  );
}

function CertDays({ cfg, setCfg }: { cfg: Cfg; setCfg: (p: Cfg) => void }) {
  return (
    <div className="grid grid-cols-2 gap-4">
      <Field label="Certificate WARN below (days)" hint="Empty: threshold rules (default 21)">
        <input className="input w-full" type="number" min={0} value={cfg.warn_days ?? ""} onChange={(e) => setCfg({ warn_days: num(e.target.value) })} /></Field>
      <Field label="Certificate CRIT below (days)" hint="Empty: threshold rules (default 7)">
        <input className="input w-full" type="number" min={0} value={cfg.crit_days ?? ""} onChange={(e) => setCfg({ crit_days: num(e.target.value) })} /></Field>
    </div>
  );
}

// --------------------------------------------------------------------------- per-kind sections

function IcmpSection({ f, set }: SectionProps) {
  return (
    <Field label="Pings per round">
      <input className="input w-32" type="number" min={1} max={20} value={f.count} onChange={(e) => set({ count: Math.max(1, Math.min(20, +e.target.value || 1)) })} />
    </Field>
  );
}

function TcpSection({ cfg, setCfg }: SectionProps) {
  return (
    <div className="space-y-4">
      <div className="grid sm:grid-cols-2 gap-4">
        <Field label="Send after connecting (optional)" hint={<>e.g. <code className="font-mono">QUIT\r\n</code>; \r \n \t are escapes</>}>
          <input className="input w-full font-mono" maxLength={1024} value={cfg.send ?? ""} onChange={(e) => setCfg({ send: e.target.value || null })} /></Field>
        <Field label="Expect in the first bytes (optional)" hint="Banner check, e.g. 220 for SMTP or SSH- for SSH">
          <input className="input w-full font-mono" maxLength={512} value={cfg.expect ?? ""} onChange={(e) => setCfg({ expect: e.target.value || null })} /></Field>
      </div>
      <div className="flex flex-wrap gap-x-6 gap-y-2">
        <Check label="Expect is a regex" checked={!!cfg.expect_regex} onChange={(v) => setCfg({ expect_regex: v })} />
        <Check label="TLS" hint="TLS handshake; records the certificate" checked={!!cfg.tls} onChange={(v) => setCfg({ tls: v })} />
        {cfg.tls && <Check label="Ignore TLS errors" checked={!!cfg.ignore_tls} onChange={(v) => setCfg({ ignore_tls: v })} />}
      </div>
      {cfg.tls && cfg.ignore_tls && <div className="text-xs text-warn">Certificate problems (untrusted chain) won't mark the probe down.</div>}
      {cfg.tls && <CertDays cfg={cfg} setCfg={setCfg} />}
    </div>
  );
}

const METHODS = ["GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"];

export function HttpSection({ cfg, setCfg, secrets, setSecret, saved, f }: SectionProps) {
  const https = f.target.trim().toLowerCase().startsWith("https://");
  const auth = cfg.auth ?? "none";
  return (
    <div className="space-y-4">
      <div className="grid sm:grid-cols-3 gap-4">
        <Field label="Method">
          <select className="input w-full" value={cfg.method ?? "GET"} onChange={(e) => setCfg({ method: e.target.value })}>
            {METHODS.map((m) => <option key={m}>{m}</option>)}
          </select></Field>
        <Field label="Accepted status codes" hint="Lists and ranges: 200-299,301" className="sm:col-span-2">
          <input className="input w-full font-mono" value={cfg.accepted_codes ?? "200-299"} onChange={(e) => setCfg({ accepted_codes: e.target.value })} /></Field>
      </div>
      <div className="grid sm:grid-cols-[1fr_auto] gap-4 items-end">
        <Field label="Keyword (optional)" hint="Searched in the first 1 MB of the response">
          <input className="input w-full" maxLength={1024} value={cfg.keyword ?? ""} onChange={(e) => setCfg({ keyword: e.target.value || null })} /></Field>
        <div className="space-y-1.5 pb-1">
          <Check label="Must be absent" checked={!!cfg.keyword_absent} onChange={(v) => setCfg({ keyword_absent: v })} />
          <Check label="Case-insensitive" checked={!!cfg.keyword_case_insensitive} onChange={(v) => setCfg({ keyword_case_insensitive: v })} />
        </div>
      </div>
      <div className="flex flex-wrap items-center gap-x-6 gap-y-2">
        <Check label="Follow redirects" checked={cfg.follow_redirects ?? true} onChange={(v) => setCfg({ follow_redirects: v })} />
        {(cfg.follow_redirects ?? true) && (
          <label className="text-sm text-fg flex items-center gap-2">max <input className="input w-16 py-1" type="number" min={0} max={10} value={cfg.max_redirects ?? 10}
            onChange={(e) => setCfg({ max_redirects: Math.max(0, Math.min(10, +e.target.value || 0)) })} /></label>
        )}
        <Check label="Ignore TLS errors" checked={!!cfg.ignore_tls} onChange={(v) => setCfg({ ignore_tls: v })} />
      </div>
      {cfg.ignore_tls && <div className="rounded-lg border border-warn/40 bg-warn/10 text-warn text-xs p-2.5">TLS errors are ignored: an expired or untrusted certificate will not mark this probe down.</div>}

      <Field label="Authentication">
        <select className="input w-full sm:w-60" value={auth} onChange={(e) => setCfg({ auth: e.target.value })}>
          <option value="none">None</option><option value="basic">Basic (user + password)</option>
          <option value="bearer">Bearer token</option><option value="header">Custom header</option>
        </select></Field>
      {auth === "basic" && (
        <div className="grid sm:grid-cols-2 gap-4">
          <Field label="User"><input className="input w-full" autoComplete="off" value={cfg.auth_user ?? ""} onChange={(e) => setCfg({ auth_user: e.target.value || null })} /></Field>
          <SecretInput name="password" label="Password (encrypted)" saved={saved} secrets={secrets} setSecret={setSecret} />
        </div>
      )}
      {auth === "bearer" && <SecretInput name="token" label="Token (encrypted)" saved={saved} secrets={secrets} setSecret={setSecret} />}
      {auth === "header" && (
        <div className="grid sm:grid-cols-2 gap-4">
          <Field label="Header name"><input className="input w-full font-mono" placeholder="X-Api-Key" value={cfg.auth_header_name ?? ""} onChange={(e) => setCfg({ auth_header_name: e.target.value || null })} /></Field>
          <SecretInput name="header_value" label="Header value (encrypted)" saved={saved} secrets={secrets} setSecret={setSecret} />
        </div>
      )}
      <HeadersEditor saved={saved} secrets={secrets} setSecret={setSecret} />

      {!["GET", "HEAD"].includes(cfg.method ?? "GET") && (
        <div className="space-y-2">
          <div className="flex flex-wrap items-center gap-4">
            <label className="label mb-0">Body</label>
            <select className="input py-1 w-28" value={cfg.body_type ?? "raw"} onChange={(e) => setCfg({ body_type: e.target.value })}>
              <option value="raw">Raw</option><option value="json">JSON</option><option value="form">Form</option>
            </select>
            <Check label="Secret (encrypted)" checked={!!cfg.body_secret} onChange={(v) => setCfg({ body_secret: v, body: v ? null : cfg.body })} />
          </div>
          {cfg.body_secret
            ? <SecretInput name="body" label="Body (encrypted)" saved={saved} secrets={secrets} setSecret={setSecret} multiline />
            : <textarea className="input w-full font-mono text-xs" rows={4} maxLength={65536} value={cfg.body ?? ""} onChange={(e) => setCfg({ body: e.target.value || null })}
                placeholder={cfg.body_type === "json" ? '{"key": "value"}' : cfg.body_type === "form" ? "a=1&b=2" : ""} />}
        </div>
      )}
      {https && <CertDays cfg={cfg} setCfg={setCfg} />}
    </div>
  );
}

const RECORD_TYPES = ["A", "AAAA", "CNAME", "MX", "TXT", "NS", "SOA", "PTR", "CAA", "SRV"];

function DnsSection({ cfg, setCfg }: SectionProps) {
  const [expected, setExpected] = useState<string>((cfg.expected ?? []).join("\n"));
  return (
    <div className="space-y-4">
      <div className="grid sm:grid-cols-3 gap-4">
        <Field label="Record type">
          <select className="input w-full" value={cfg.record_type ?? "A"} onChange={(e) => setCfg({ record_type: e.target.value })}>
            {RECORD_TYPES.map((t) => <option key={t}>{t}</option>)}
          </select></Field>
        <Field label="Resolver (optional)" hint="Empty: the system resolver">
          <input className="input w-full font-mono" placeholder="1.1.1.1" value={cfg.resolver ?? ""} onChange={(e) => setCfg({ resolver: e.target.value || null })} /></Field>
        <Field label="Resolver port">
          <input className="input w-full" type="number" min={1} max={65535} value={cfg.resolver_port ?? 53} onChange={(e) => setCfg({ resolver_port: +e.target.value || 53 })} /></Field>
      </div>
      <div className="grid sm:grid-cols-[1fr_auto] gap-4 items-start">
        <Field label="Expected values (optional, one per line)" hint="e.g. 93.184.216.34, or mail.example.com for MX. PTR: enter the IP address as the name.">
          <textarea className="input w-full font-mono text-xs" rows={3} value={expected}
            onChange={(e) => { setExpected(e.target.value); setCfg({ expected: e.target.value.split("\n").map((x) => x.trim()).filter(Boolean) }); }} /></Field>
        <Field label="Match">
          <select className="input w-full" value={cfg.match ?? "any"} onChange={(e) => setCfg({ match: e.target.value })}>
            <option value="any">any value</option><option value="all">all values</option>
          </select></Field>
      </div>
    </div>
  );
}

function UdpSection({ cfg, setCfg }: SectionProps) {
  return (
    <div className="space-y-4">
      <div className="grid sm:grid-cols-[1fr_auto] gap-4 items-end">
        <Field label="Payload to send (optional)"><input className="input w-full font-mono" maxLength={2048} value={cfg.payload ?? ""} onChange={(e) => setCfg({ payload: e.target.value || null })} /></Field>
        <div className="pb-2"><Check label="Hex" checked={!!cfg.payload_hex} onChange={(v) => setCfg({ payload_hex: v })} /></div>
      </div>
      <div className="grid sm:grid-cols-[1fr_auto] gap-4">
        <Field label="Expected reply (optional)"><input className="input w-full font-mono" maxLength={512} value={cfg.expect ?? ""} onChange={(e) => setCfg({ expect: e.target.value || null })} /></Field>
        <Field label="Match as">
          <select className="input w-full" value={cfg.expect_mode ?? "substring"} onChange={(e) => setCfg({ expect_mode: e.target.value })}>
            <option value="substring">text</option><option value="regex">regex</option><option value="hex">hex bytes</option>
          </select></Field>
      </div>
      {!cfg.expect && <div className="rounded-lg border border-line bg-inset text-xs text-fg2 p-2.5">
        Without an expected reply, UP only means no ICMP "port unreachable" or socket error came back. UDP has no handshake: a firewall that silently drops packets looks the same as a working service.</div>}
    </div>
  );
}

function TlsSection({ cfg, setCfg }: SectionProps) {
  return (
    <div className="space-y-4">
      <div className="grid sm:grid-cols-2 gap-4">
        <Field label="SNI / hostname to check (optional)" hint="Default: the host above">
          <input className="input w-full font-mono" value={cfg.sni ?? ""} onChange={(e) => setCfg({ sni: e.target.value || null })} /></Field>
        <Field label="STARTTLS" hint="For mail and FTP servers on their plain ports (25/587, 143, 110, 21)">
          <select className="input w-full" value={cfg.starttls ?? ""} onChange={(e) => setCfg({ starttls: e.target.value || null })}>
            <option value="">None (TLS from the start)</option><option value="smtp">SMTP</option><option value="imap">IMAP</option>
            <option value="pop3">POP3</option><option value="ftp">FTP</option>
          </select></Field>
      </div>
      <CertDays cfg={cfg} setCfg={setCfg} />
      <div className="text-xs text-muted">DOWN when the certificate is expired, untrusted or doesn't match the hostname. The Certificate expiry check turns WARN / CRIT at the thresholds and notifies once at each.</div>
    </div>
  );
}

/** Kind -> its own fields. Later kinds register here too. */
export const SECTIONS: Partial<Record<ProbeKind, (p: SectionProps) => ReactNode>> = {
  icmp: IcmpSection, tcp: TcpSection, http: HttpSection, dns: DnsSection, udp: UdpSection, tls: TlsSection,
};

// --------------------------------------------------------------------------- test result

export function TestResult({ r }: { r: ProbeTestResult }) {
  return (
    <div className={`rounded-lg border p-3 text-sm space-y-2 ${r.effective_up ? "border-ok/40 bg-ok/5" : "border-crit/40 bg-crit/5"}`}>
      <div className="flex items-center gap-3">
        <span className={`font-semibold ${r.effective_up ? "text-ok" : "text-crit"}`}>{r.effective_up ? "UP" : "DOWN"}</span>
        <span className="text-strong">{r.message}</span>
        {r.response_ms != null && <span className="ml-auto tabular-nums text-fg2">{fmtMs(r.response_ms)}</span>}
      </div>
      {Object.keys(r.metrics).length > 0 && (
        <div className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted">
          {Object.entries(r.metrics).map(([k, v]) => <span key={k}><span className="font-mono">{k}</span> {Number.isInteger(v) ? v : v.toFixed(2)}</span>)}
        </div>
      )}
      {r.checks.map((c) => <div key={c.name} className="text-xs"><span className="text-strong">{c.name}</span>: {c.output}{c.state && c.state !== "OK" ? ` (${c.state})` : ""}</div>)}
      {r.cert && <div className="text-xs text-fg2">Certificate: {r.cert.subject_cn} · issuer {r.cert.issuer} · {r.cert.days_left.toFixed(0)} days left
        {r.cert.hostname_match === false && <span className="text-crit"> · hostname mismatch</span>}{r.cert.chain_valid === false && <span className="text-crit"> · untrusted</span>}</div>}
    </div>
  );
}

// --------------------------------------------------------------------------- form

const INTERVALS = [20, 30, 60, 120, 300, 600, 1800, 3600];
const fmtInterval = (s: number) => (s < 60 ? `${s} s` : s < 3600 ? `${s / 60} min` : `${s / 3600} h`);

export function ProbeForm({ initial, onClose, onSaved }: { initial?: Probe; onClose: () => void; onSaved?: (p: Probe) => void }) {
  const qc = useQueryClient();
  const me = useMe();
  const { data: groups = [] } = useQuery({ queryKey: ["groups"], queryFn: () => api<Group[]>("/groups") });
  const { data: kinds = [] } = useQuery({ queryKey: ["probe-kinds"], queryFn: () => api<{ kind: ProbeKind; default_port: number | null; needs_port: boolean }[]>("/probes/kinds"), staleTime: Infinity });
  const [f, setF] = useState<FormState>({
    name: initial?.name ?? "", kind: initial?.kind ?? "http", target: initial?.target ?? "", port: initial?.port ?? null,
    interval_s: initial?.interval_s ?? 60, timeout_s: initial?.timeout_s ?? 10, retries: initial?.retries ?? 1,
    retry_interval_s: initial?.retry_interval_s ?? null, upside_down: initial?.upside_down ?? false,
    resend_every: initial?.resend_every ?? 0, count: initial?.count ?? 5, enabled: initial?.enabled ?? true,
    tags: initial?.tags ?? [], description: initial?.description ?? "", group_ids: initial?.group_ids ?? [],
    config: initial?.config ?? {},
  });
  const [secrets, setSecrets] = useState<Cfg>({});
  const [tagInput, setTagInput] = useState("");
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);
  const [testing, setTesting] = useState(false);
  const [result, setResult] = useState<ProbeTestResult | null>(null);
  const [more, setMore] = useState(false);
  const set = (patch: Partial<FormState>) => { setF((p) => ({ ...p, ...patch })); setResult(null); };
  const setCfg = (patch: Cfg) => set({ config: { ...f.config, ...patch } });
  const setSecret = (k: string, v: any) => setSecrets((s) => { const n = { ...s }; if (v === undefined) delete n[k]; else n[k] = v; return n; });
  const saved = initial && initial.kind === f.kind ? initial.secrets : {};
  const meta = kindMeta(f.kind);
  const kindInfo = kinds.find((k) => k.kind === f.kind);
  const Section = SECTIONS[f.kind];

  function changeKind(kind: ProbeKind) {
    const info = kinds.find((k) => k.kind === kind);
    set({ kind, config: initial?.kind === kind ? initial.config : {}, port: initial?.kind === kind ? initial.port : info?.default_port ?? null,
      target: kind === "push" ? "" : f.target });
    setSecrets({});
  }

  function body() {
    const tags = tagInput.trim() ? [...f.tags, tagInput.trim()] : f.tags;
    return { ...f, tags, description: f.description || null, name: f.name.trim(), target: f.target.trim(),
      ...(Object.keys(secrets).length || !initial ? { secrets } : {}) };
  }

  async function test() {
    setError(""); setTesting(true); setResult(null);
    try {
      setResult(await api<ProbeTestResult>(`/probes/test${initial ? `?probe_id=${initial.id}` : ""}`, { body: body() }));
    } catch (e: any) { setError(e.message); } finally { setTesting(false); }
  }

  async function save() {
    setError(""); setSaving(true);
    try {
      const p = initial ? await api<Probe>(`/probes/${initial.id}`, { method: "PUT", body: body() }) : await api<Probe>("/probes", { body: body() });
      qc.invalidateQueries({ queryKey: ["probes"] });
      qc.invalidateQueries({ queryKey: ["probe", p.id] });
      onSaved?.(p);
      onClose();
    } catch (e: any) { setError(e.message); } finally { setSaving(false); }
  }

  const available = kinds.length ? kinds.map((k) => k.kind) : (["icmp", "tcp", "http"] as ProbeKind[]);
  const ready = f.name.trim() && (f.kind === "push" || f.target.trim()) && (!kindInfo?.needs_port || f.port);

  return (
    <Modal title={initial ? `Edit probe · ${initial.name}` : "New probe"} onClose={onClose} wide>
      <div className="space-y-5">
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
          {available.map((k) => (
            <button key={k} type="button" onClick={() => changeKind(k)}
              className={`text-left px-3 py-2 rounded-xl border transition-colors flex items-center gap-2 ${f.kind === k ? "border-accent bg-accent/5" : "border-edge hover:bg-inset"}`}>
              <Icon name={KINDS[k]?.icon ?? "pulse"} className="w-4 h-4 text-muted" />
              <span className="text-sm font-medium text-strong truncate">{KINDS[k]?.label ?? k}</span>
            </button>
          ))}
        </div>
        <div className="text-xs text-muted -mt-2">{meta.help}</div>

        <div className="grid sm:grid-cols-[1fr_2fr] gap-4">
          <Field label="Name"><input className="input w-full" autoFocus maxLength={64} value={f.name} onChange={(e) => set({ name: e.target.value })} placeholder="My website" /></Field>
          {f.kind !== "push" && (
            <div className="grid grid-cols-[1fr_auto] gap-2">
              <Field label={meta.target}><input className="input w-full font-mono" maxLength={2048} value={f.target} onChange={(e) => set({ target: e.target.value })} placeholder={meta.placeholder} /></Field>
              {kindInfo?.needs_port && (
                <Field label="Port"><input className="input w-24" type="number" min={1} max={65535} value={f.port ?? ""} onChange={(e) => set({ port: num(e.target.value) })} /></Field>
              )}
            </div>
          )}
        </div>

        {Section && <Section cfg={f.config} setCfg={setCfg} secrets={secrets} setSecret={setSecret} saved={saved} f={f} set={set} />}

        <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
          <Field label="Check every">
            <select className="input w-full" value={f.interval_s} onChange={(e) => set({ interval_s: +e.target.value })}>
              {[...new Set([...INTERVALS, f.interval_s])].sort((a, b) => a - b).map((s) => <option key={s} value={s}>{fmtInterval(s)}</option>)}
            </select></Field>
          <Field label="Timeout (s)"><input className="input w-full" type="number" min={1} max={120} value={f.timeout_s} onChange={(e) => set({ timeout_s: Math.max(1, Math.min(120, +e.target.value || 1)) })} /></Field>
          <Field label="Retries" hint="Failures before DOWN"><input className="input w-full" type="number" min={1} max={20} value={f.retries} onChange={(e) => set({ retries: Math.max(1, Math.min(20, +e.target.value || 1)) })} /></Field>
          <Field label="Retry every">
            <select className="input w-full" value={f.retry_interval_s ?? ""} onChange={(e) => set({ retry_interval_s: num(e.target.value) })}>
              <option value="">same as interval</option>
              {INTERVALS.map((s) => <option key={s} value={s}>{fmtInterval(s)}</option>)}
            </select></Field>
        </div>

        <button type="button" className="flex items-center gap-2 text-sm font-medium text-strong" onClick={() => setMore((v) => !v)}>
          <Icon name="chevron" className={`w-3.5 h-3.5 transition-transform ${more ? "rotate-90" : ""}`} /> More options
          <span className="text-xs font-normal text-muted">upside down, notifications, tags, groups</span>
        </button>
        {more && (
          <div className="space-y-4">
            <div className="flex flex-wrap gap-x-6 gap-y-3">
              <Check label="Upside down" hint="Invert up/down, e.g. a port that must stay closed" checked={f.upside_down} onChange={(v) => set({ upside_down: v })} />
              <Check label="Enabled" checked={f.enabled} onChange={(v) => set({ enabled: v })} />
            </div>
            <Field label="Resend notification while down" hint="0 = only when the state changes">
              <div className="flex items-center gap-2 text-sm text-fg">every <input className="input w-20" type="number" min={0} max={1000} value={f.resend_every}
                onChange={(e) => set({ resend_every: Math.max(0, Math.min(1000, +e.target.value || 0)) })} /> checks</div></Field>
            <Field label="Tags">
              <div className="flex flex-wrap items-center gap-2">
                {f.tags.map((t) => (
                  <span key={t} className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full bg-chip text-xs text-fg">{t}
                    <button type="button" onClick={() => set({ tags: f.tags.filter((x) => x !== t) })}><Icon name="x" className="w-3 h-3" /></button></span>
                ))}
                <input className="input py-1 w-40" maxLength={32} value={tagInput} placeholder="add tag, Enter" onChange={(e) => setTagInput(e.target.value)}
                  onKeyDown={(e) => { if (e.key === "Enter" && tagInput.trim()) { e.preventDefault(); if (!f.tags.includes(tagInput.trim())) set({ tags: [...f.tags, tagInput.trim()] }); setTagInput(""); } }} />
              </div></Field>
            <Field label="Description"><textarea className="input w-full" rows={2} maxLength={2000} value={f.description} onChange={(e) => set({ description: e.target.value })} /></Field>
            {groups.length > 0 && (
              <Field label={`Device groups${me?.role !== "admin" ? " (yours)" : ""}`}>
                <div className="flex flex-wrap gap-2">
                  {groups.map((g) => {
                    const on = f.group_ids.includes(g.id);
                    return <button key={g.id} type="button" onClick={() => set({ group_ids: on ? f.group_ids.filter((x) => x !== g.id) : [...f.group_ids, g.id] })}
                      className={`px-2.5 py-1 rounded-full text-xs border ${on ? "border-accent bg-accent/10 text-accent" : "border-edge text-muted hover:text-strong"}`}>{g.name}</button>;
                  })}
                </div></Field>
            )}
            <div className="text-xs text-muted">Operators can point probes at internal addresses on purpose. Status, Response time and kind-specific checks use your threshold rules, so problems, downtimes and notifications work as for devices.</div>
          </div>
        )}

        {result && <TestResult r={result} />}
        {error && <div className="text-xs text-crit whitespace-pre-wrap">{error}</div>}
        <div className="flex items-center justify-between gap-2">
          <button type="button" className="btn" onClick={test} disabled={testing || !ready || f.kind === "push"}>
            <Icon name="play" className="w-3.5 h-3.5" /> {testing ? "Testing…" : "Test now"}</button>
          <div className="flex gap-2">
            <button className="btn" onClick={onClose}>Cancel</button>
            <button className="btn btn-primary" onClick={save} disabled={saving || !ready}>{saving ? "Saving…" : initial ? "Save" : "Add probe"}</button>
          </div>
        </div>
      </div>
    </Modal>
  );
}
