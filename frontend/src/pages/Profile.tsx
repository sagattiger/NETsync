import { ReactNode, useEffect, useRef, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api, fmtAgo, fmtDateTime, Me, Preferences, prefs } from "../api";
import { Avatar } from "../components/Avatar";
import { Icon } from "../components/Icon";
import { Page, PageHeader } from "../components/Layout";
import { Segmented } from "../components/ui";
import { ThemeChoice, useTheme } from "../theme";

const AVATAR_SIZE = 256;

function Section({ icon, title, sub, children }: { icon: string; title: string; sub?: string; children: ReactNode }) {
  return (
    <section className="card">
      <header className="px-5 py-4 border-b border-line flex items-start gap-3">
        <span className="w-8 h-8 rounded-lg bg-inset border border-line flex items-center justify-center text-fg2 shrink-0">
          <Icon name={icon} className="w-4 h-4" />
        </span>
        <div>
          <h2 className="font-medium text-strong">{title}</h2>
          {sub && <p className="text-xs text-muted mt-0.5">{sub}</p>}
        </div>
      </header>
      <div className="p-5">{children}</div>
    </section>
  );
}

function Row({ label, hint, children }: { label: string; hint?: string; children: ReactNode }) {
  return (
    <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2 py-3 first:pt-0 last:pb-0 border-b border-line/70 last:border-0">
      <div>
        <div className="text-sm text-strong">{label}</div>
        {hint && <div className="text-xs text-muted">{hint}</div>}
      </div>
      <div className="shrink-0">{children}</div>
    </div>
  );
}

/** Center-crop and scale an image file to a square WebP data URL. */
function resizeImage(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const img = new Image();
    img.onload = () => {
      const side = Math.min(img.width, img.height);
      const canvas = document.createElement("canvas");
      canvas.width = canvas.height = AVATAR_SIZE;
      const ctx = canvas.getContext("2d")!;
      ctx.drawImage(img, (img.width - side) / 2, (img.height - side) / 2, side, side, 0, 0, AVATAR_SIZE, AVATAR_SIZE);
      URL.revokeObjectURL(img.src);
      const webp = canvas.toDataURL("image/webp", 0.88);
      resolve(webp.startsWith("data:image/webp") ? webp : canvas.toDataURL("image/png"));
    };
    img.onerror = () => reject(new Error("Could not read that image"));
    img.src = URL.createObjectURL(file);
  });
}

function timezones(): string[] {
  try {
    return (Intl as any).supportedValuesOf("timeZone") as string[];
  } catch {
    return ["UTC"];
  }
}

export default function Profile() {
  const qc = useQueryClient();
  const { choice, setChoice } = useTheme();
  const { data: me } = useQuery({ queryKey: ["me"], queryFn: () => api<Me>("/auth/me") });
  const fileRef = useRef<HTMLInputElement>(null);
  const [info, setInfo] = useState({ full_name: "", email: "", phone: "", job_title: "", timezone: "" });
  const [infoMsg, setInfoMsg] = useState("");
  const [avatarErr, setAvatarErr] = useState("");
  const [pw, setPw] = useState({ current: "", next: "", confirm: "" });
  const [pwMsg, setPwMsg] = useState<{ ok: boolean; text: string } | null>(null);

  useEffect(() => {
    if (me) setInfo({
      full_name: me.full_name ?? "", email: me.email ?? "", phone: me.phone ?? "",
      job_title: me.job_title ?? "", timezone: me.timezone ?? "",
    });
  }, [me]);

  if (!me) return null;
  const p = me.preferences;
  const update = (m: Me) => { qc.setQueryData(["me"], m); prefs.set(m.preferences); };

  async function saveInfo() {
    setInfoMsg("");
    try { update(await api<Me>("/auth/me", { method: "PATCH", body: info })); setInfoMsg("Saved"); }
    catch (e: any) { setInfoMsg(e.message); }
  }

  async function setPref<K extends keyof Preferences>(key: K, value: Preferences[K]) {
    if (key === "theme") setChoice(value as ThemeChoice);
    update(await api<Me>("/auth/me", { method: "PATCH", body: { preferences: { [key]: value } } }));
  }

  async function onAvatar(file: File | undefined) {
    if (!file) return;
    setAvatarErr("");
    try {
      const data_url = await resizeImage(file);
      update(await api<Me>("/auth/me/avatar", { method: "PUT", body: { data_url } }));
      qc.invalidateQueries({ queryKey: ["history"] });
    } catch (e: any) { setAvatarErr(e.message); }
    if (fileRef.current) fileRef.current.value = "";
  }

  async function changePassword() {
    setPwMsg(null);
    if (pw.next !== pw.confirm) return setPwMsg({ ok: false, text: "New passwords do not match" });
    try {
      await api("/auth/password", { body: { current: pw.current, new: pw.next } });
      setPw({ current: "", next: "", confirm: "" });
      setPwMsg({ ok: true, text: "Password changed" });
      qc.invalidateQueries({ queryKey: ["me"] });
    } catch (e: any) { setPwMsg({ ok: false, text: e.message }); }
  }

  const strength = [/.{12,}/, /[A-Z]/, /[a-z]/, /\d/, /[^A-Za-z0-9]/].filter((re) => re.test(pw.next)).length;
  const strengthLabel = ["", "Weak", "Weak", "Fair", "Good", "Strong"][strength];

  return (
    <>
      <PageHeader title="Profile" sub="Your account, preferences and security" />
      <Page>
        {/* identity header */}
        <div className="card p-5 flex flex-col sm:flex-row sm:items-center gap-5">
          <div className="relative w-fit group">
            <Avatar name={me.full_name || me.username} url={me.avatar_url} size={88} />
            <button onClick={() => fileRef.current?.click()} title="Change picture"
              className="absolute -bottom-1 -right-1 w-8 h-8 rounded-full bg-primary text-on-primary border-2 border-surface flex items-center justify-center hover:scale-105 transition">
              <Icon name="camera" className="w-4 h-4" />
            </button>
            <input ref={fileRef} type="file" accept="image/png,image/jpeg,image/webp,image/gif" hidden onChange={(e) => onAvatar(e.target.files?.[0])} />
          </div>
          <div className="flex-1 min-w-0">
            <div className="text-xl font-semibold text-strong tracking-tight">{me.full_name || me.username}</div>
            <div className="text-sm text-muted">@{me.username}{me.job_title ? ` · ${me.job_title}` : ""}</div>
            <div className="flex flex-wrap gap-1.5 mt-2.5">
              <span className="text-xxs font-semibold uppercase tracking-wide px-2 py-0.5 rounded-full bg-accent/15 text-accent">{me.role}</span>
              {(me.role === "admin" ? ["all devices"] : me.groups).map((g) => (
                <span key={g} className="text-xxs px-2 py-0.5 rounded-full bg-chip text-fg2">{g}</span>
              ))}
            </div>
            {avatarErr && <div className="text-xs text-crit mt-2">{avatarErr}</div>}
          </div>
          <div className="grid grid-cols-2 sm:grid-cols-1 gap-x-6 gap-y-2 text-xs sm:text-right">
            <div><div className="text-muted">Member since</div><div className="text-fg">{fmtDateTime(me.created_at)}</div></div>
            <div><div className="text-muted">Last sign-in</div><div className="text-fg">{fmtAgo(me.last_login)}</div></div>
          </div>
        </div>
        {me.avatar_url && (
          <div className="-mt-2 text-right">
            <button className="text-xs text-muted hover:text-crit" onClick={async () => update(await api<Me>("/auth/me/avatar", { method: "DELETE" }))}>
              Remove picture
            </button>
          </div>
        )}

        <div className="grid xl:grid-cols-2 gap-4 items-start">
          <Section icon="user" title="Personal information" sub="Shown to other users on comments and notes">
            <div className="grid sm:grid-cols-2 gap-4">
              <div className="sm:col-span-2"><label className="label">Full name</label>
                <input className="input w-full" value={info.full_name} onChange={(e) => setInfo({ ...info, full_name: e.target.value })} /></div>
              <div><label className="label">Email (used for notifications)</label>
                <input className="input w-full" type="email" value={info.email} onChange={(e) => setInfo({ ...info, email: e.target.value })} /></div>
              <div><label className="label">Phone</label>
                <input className="input w-full" value={info.phone} onChange={(e) => setInfo({ ...info, phone: e.target.value })} /></div>
              <div><label className="label">Job title</label>
                <input className="input w-full" value={info.job_title} onChange={(e) => setInfo({ ...info, job_title: e.target.value })} placeholder="Network engineer" /></div>
              <div><label className="label">Time zone</label>
                <select className="input w-full" value={info.timezone} onChange={(e) => setInfo({ ...info, timezone: e.target.value })}>
                  <option value="">Browser default</option>
                  {timezones().map((tz) => <option key={tz}>{tz}</option>)}
                </select></div>
            </div>
            <div className="mt-5 flex items-center gap-3">
              <button className="btn btn-primary" onClick={saveInfo}>Save changes</button>
              {infoMsg && <span className={`text-xs ${infoMsg === "Saved" ? "text-ok" : "text-crit"}`}>{infoMsg}</span>}
            </div>
          </Section>

          <Section icon="palette" title="Interface" sub="Saved to your account, so they follow you to any browser">
            <Row label="Theme">
              <Segmented value={choice} onChange={(v) => setPref("theme", v)} options={[["light", "Light"], ["dark", "Dark"], ["system", "System"]]} />
            </Row>
            <Row label="Default graph range" hint="Used when opening a device">
              <Segmented value={p.default_range ?? "24h"} onChange={(v) => setPref("default_range", v)}
                options={[["1h", "1h"], ["6h", "6h"], ["24h", "24h"], ["7d", "7d"], ["30d", "30d"]]} />
            </Row>
            <Row label="Time format">
              <Segmented value={p.time_format ?? "24h"} onChange={(v) => setPref("time_format", v)} options={[["24h", "24-hour"], ["12h", "12-hour"]]} />
            </Row>
            <Row label="Auto refresh" hint="How often lists and states reload">
              <Segmented value={p.refresh_interval ?? "30"} onChange={(v) => setPref("refresh_interval", v)}
                options={[["10", "10s"], ["30", "30s"], ["60", "1m"], ["300", "5m"]]} />
            </Row>
            <Row label="Table density">
              <Segmented value={p.table_density ?? "comfortable"} onChange={(v) => setPref("table_density", v)}
                options={[["comfortable", "Comfortable"], ["compact", "Compact"]]} />
            </Row>
            <Row label="Start page" hint="Where you land after signing in">
              <Segmented value={p.landing_page ?? "/"} onChange={(v) => setPref("landing_page", v)}
                options={[["/", "Overview"], ["/problems", "Problems"], ["/devices", "Devices"]]} />
            </Row>
          </Section>

          <Section icon="lock" title="Password" sub={me.password_changed_at ? `Last changed ${fmtAgo(me.password_changed_at)}` : "Never changed"}>
            <form className="grid gap-4 max-w-sm" onSubmit={(e) => { e.preventDefault(); changePassword(); }}>
              <input type="text" autoComplete="username" value={me.username} readOnly hidden />
              <div><label className="label">Current password</label>
                <input className="input w-full" type="password" autoComplete="current-password" value={pw.current} onChange={(e) => setPw({ ...pw, current: e.target.value })} /></div>
              <div><label className="label">New password</label>
                <input className="input w-full" type="password" autoComplete="new-password" value={pw.next} onChange={(e) => setPw({ ...pw, next: e.target.value })} />
                {pw.next && (
                  <div className="flex items-center gap-2 mt-2">
                    <div className="flex gap-1 flex-1">
                      {[1, 2, 3, 4, 5].map((i) => (
                        <span key={i} className={`h-1 flex-1 rounded-full ${i <= strength ? (strength >= 4 ? "bg-ok" : strength >= 3 ? "bg-warn" : "bg-crit") : "bg-chip"}`} />
                      ))}
                    </div>
                    <span className="text-xxs text-muted w-12 text-right">{strengthLabel}</span>
                  </div>
                )}
              </div>
              <div><label className="label">Confirm new password</label>
                <input className="input w-full" type="password" autoComplete="new-password" value={pw.confirm} onChange={(e) => setPw({ ...pw, confirm: e.target.value })} /></div>
              <div className="flex items-center gap-3">
                <button className="btn btn-primary" disabled={!pw.current || pw.next.length < 8}>Change password</button>
                {pwMsg && <span className={`text-xs ${pwMsg.ok ? "text-ok" : "text-crit"}`}>{pwMsg.text}</span>}
              </div>
              <p className="text-xs text-muted">At least 8 characters. Longer passphrases with mixed characters are stronger.</p>
            </form>
          </Section>

          <Section icon="check" title="Account" sub="Managed by an administrator">
            <Row label="Username"><span className="text-sm text-fg font-mono">{me.username}</span></Row>
            <Row label="Role" hint={me.role === "admin" ? "Full access" : me.role === "operator" ? "Manage devices, acknowledge, comment and pin" : "Read only"}>
              <span className="text-sm text-fg capitalize">{me.role}</span>
            </Row>
            <Row label="Device groups"><span className="text-sm text-fg">{me.role === "admin" ? "All devices" : me.groups.join(", ") || "None"}</span></Row>
            <Row label="Account created"><span className="text-sm text-fg">{fmtDateTime(me.created_at)}</span></Row>
            <Row label="Last sign-in"><span className="text-sm text-fg">{fmtDateTime(me.last_login)}</span></Row>
          </Section>
        </div>
      </Page>
    </>
  );
}
