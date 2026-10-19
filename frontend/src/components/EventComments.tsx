import { useState } from "react";
import { createPortal } from "react-dom";
import { Link } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api, DeviceEvent, EventComment, fmtDateTime, Me, PinnedEvent } from "../api";
import { Avatar } from "./Avatar";
import { Icon } from "./Icon";
import { StateBadge } from "./ui";

const useMe = () => useQuery({ queryKey: ["me"], queryFn: () => api<Me>("/auth/me") }).data;

function invalidate(qc: ReturnType<typeof useQueryClient>, deviceId: number) {
  qc.invalidateQueries({ queryKey: ["history", deviceId] });
  qc.invalidateQueries({ queryKey: ["pinned"] });
}

function CommentLine({ c, compact }: { c: EventComment; compact?: boolean }) {
  return (
    <div className="flex gap-2.5">
      <Avatar name={c.author} url={c.author_avatar} size={compact ? 22 : 28} />
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-baseline gap-x-2 text-xs">
          <span className="font-medium text-strong">{c.author}</span>
          <span className="text-muted" title={fmtDateTime(c.created_at)}>{fmtDateTime(c.created_at)}</span>
          {c.pinned && <span className="inline-flex items-center gap-0.5 text-accent font-medium"><Icon name="pin" className="w-3 h-3" />pinned</span>}
          {c.updated_at && <span className="text-muted">(edited)</span>}
        </div>
        <div className={`text-fg whitespace-pre-wrap break-words ${compact ? "text-xs mt-0.5 line-clamp-3" : "text-sm mt-1"}`}>{c.body}</div>
      </div>
    </div>
  );
}

/** The sticker shown on an event row. Hovering reveals the comments; clicking the row opens the thread. */
export function CommentSticker({ event }: { event: DeviceEvent }) {
  const n = event.comments.length;
  const [pos, setPos] = useState<{ top: number; left: number } | null>(null);
  const show = (e: React.MouseEvent) => {
    if (!window.matchMedia("(hover: hover)").matches) return; // touch: tap opens the thread instead
    const r = (e.currentTarget as HTMLElement).getBoundingClientRect();
    const below = r.bottom + 8 + 220 < window.innerHeight;
    setPos({ top: below ? r.bottom + 8 : Math.max(8, r.top - 228), left: Math.max(8, Math.min(r.right - 320, window.innerWidth - 328)) });
  };
  if (!n) {
    return (
      <span className="opacity-0 group-hover:opacity-100 transition-opacity inline-flex items-center gap-1 text-xxs text-muted">
        <Icon name="message" className="w-3.5 h-3.5" /> Comment
      </span>
    );
  }
  return (
    <span className="inline-flex items-center gap-1.5" onMouseEnter={show} onMouseLeave={() => setPos(null)}>
      {event.pinned && (
        <span className="inline-flex items-center justify-center w-6 h-6 rounded-full bg-accent text-white" title="Pinned">
          <Icon name="pin" className="w-3.5 h-3.5" />
        </span>
      )}
      <span className="inline-flex items-center gap-1 pl-1.5 pr-2 h-6 rounded-full bg-accent/15 text-accent text-xs font-semibold">
        <Icon name="message" className="w-3.5 h-3.5" />{n}
      </span>
      {/* hover card: portalled with fixed position so table scroll containers don't clip it */}
      {pos && createPortal(
        <div style={{ position: "fixed", top: pos.top, left: pos.left, width: 320 }} className="z-[60] pointer-events-none">
          <div className="rounded-xl border border-edge bg-surface shadow-xl p-3 space-y-3 text-left">
            {event.comments.slice(-3).map((c) => <CommentLine key={c.id} c={c} compact />)}
            {n > 3 && <div className="text-xxs text-muted">+{n - 3} more · click to open</div>}
          </div>
        </div>,
        document.body,
      )}
    </span>
  );
}

/** Full comment thread with add / pin / delete, shown when an event row is expanded. */
export function CommentThread({ deviceId, event }: { deviceId: number; event: DeviceEvent }) {
  const qc = useQueryClient();
  const me = useMe();
  const [body, setBody] = useState("");
  const [pin, setPin] = useState(false);
  const [error, setError] = useState("");
  const canPin = me?.role !== "viewer";

  async function add() {
    if (!body.trim()) return;
    setError("");
    try {
      await api(`/devices/${deviceId}/events/comments`, {
        body: { service_id: event.service_id, event_time: event.time, body, pinned: pin },
      });
      setBody("");
      setPin(false);
      invalidate(qc, deviceId);
    } catch (e: any) { setError(e.message); }
  }

  async function togglePin(c: EventComment) {
    await api(`/events/comments/${c.id}`, { method: "PATCH", body: { pinned: !c.pinned } });
    invalidate(qc, deviceId);
  }

  async function remove(c: EventComment) {
    if (!confirm("Delete this comment?")) return;
    await api(`/events/comments/${c.id}`, { method: "DELETE" });
    invalidate(qc, deviceId);
  }

  return (
    <div className="py-2 space-y-4 max-w-3xl" onClick={(e) => e.stopPropagation()}>
      {event.output && <div className="text-xs text-muted">Output: <span className="text-fg2">{event.output}</span></div>}
      {event.comments.map((c) => (
        <div key={c.id} className="flex items-start gap-2 group/c">
          <div className="flex-1"><CommentLine c={c} /></div>
          <div className="flex gap-1 opacity-60 group-hover/c:opacity-100">
            {canPin && (
              <button className={`p-1.5 rounded-md hover:bg-inset ${c.pinned ? "text-accent" : "text-muted"}`} title={c.pinned ? "Unpin" : "Pin"} onClick={() => togglePin(c)}>
                <Icon name="pin" className="w-3.5 h-3.5" />
              </button>
            )}
            {(c.author_id === me?.id || me?.role === "admin") && (
              <button className="p-1.5 rounded-md text-muted hover:text-crit hover:bg-inset" title="Delete" onClick={() => remove(c)}>
                <Icon name="trash" className="w-3.5 h-3.5" />
              </button>
            )}
          </div>
        </div>
      ))}
      <div className="flex gap-2.5">
        <Avatar name={me?.full_name || me?.username} url={me?.avatar_url} size={28} />
        <div className="flex-1 space-y-2">
          <textarea className="input w-full min-h-[4.5rem] resize-y" value={body} onChange={(e) => setBody(e.target.value)}
            placeholder={event.comments.length ? "Reply…" : "Add a comment, e.g. “Known issue, we will get it fixed by October 31st.”"}
            onKeyDown={(e) => { if ((e.ctrlKey || e.metaKey) && e.key === "Enter") add(); }} />
          <div className="flex flex-wrap items-center gap-3">
            <button className="btn btn-primary" onClick={add} disabled={!body.trim()}>Comment</button>
            {canPin && (
              <label className="flex items-center gap-2 text-xs text-fg2 cursor-pointer select-none">
                <input type="checkbox" className="accent-accent" checked={pin} onChange={(e) => setPin(e.target.checked)} />
                <Icon name="pin" className="w-3.5 h-3.5" /> Pin this event
              </label>
            )}
            {error && <span className="text-xs text-crit">{error}</span>}
          </div>
        </div>
      </div>
    </div>
  );
}

/** Pinned events (all devices, or one). */
export function PinnedEvents({ deviceId, showDevice }: { deviceId?: number; showDevice?: boolean }) {
  const qc = useQueryClient();
  const me = useMe();
  const { data = [] } = useQuery({
    queryKey: ["pinned", deviceId ?? "all"],
    queryFn: () => api<PinnedEvent[]>(deviceId ? `/devices/${deviceId}/events/pinned` : "/events/pinned"),
    refetchInterval: 60_000,
  });
  if (!data.length) return null;

  async function unpin(e: PinnedEvent) {
    await Promise.all(e.comments.filter((c) => c.pinned).map((c) =>
      api(`/events/comments/${c.id}`, { method: "PATCH", body: { pinned: false } })));
    invalidate(qc, e.device_id);
  }

  return (
    <section className="card overflow-hidden border-accent/40">
      <header className="card-title flex items-center gap-2">
        <Icon name="pin" className="w-4 h-4 text-accent" /> Pinned events · {data.length}
      </header>
      <ul className="divide-y divide-line">
        {data.map((e) => {
          const pinComment = [...e.comments].reverse().find((c) => c.pinned)!;
          return (
            <li key={`${e.device_id}-${e.service_id}-${e.time}`} className="px-4 py-3.5 flex flex-col sm:flex-row gap-3">
              <div className="sm:w-64 shrink-0 space-y-1">
                {showDevice && <Link to={`/devices/${e.device_id}/events`} className="link text-sm">{e.hostname}</Link>}
                <div className="text-sm text-strong">{e.service ?? "Service"}</div>
                <div className="flex items-center gap-1.5">
                  <StateBadge state={e.old_state} small /><span className="text-muted text-xs">→</span><StateBadge state={e.new_state} small />
                </div>
                <div className="text-xxs text-muted">{fmtDateTime(e.time)}</div>
              </div>
              <div className="flex-1 min-w-0 rounded-lg bg-accent/5 border border-accent/20 p-3">
                <CommentLine c={pinComment} />
                {e.comments.length > 1 && <div className="text-xxs text-muted mt-2 pl-[38px]">{e.comments.length - 1} more comment{e.comments.length > 2 ? "s" : ""}</div>}
              </div>
              {me?.role !== "viewer" && (
                <button className="btn btn-ghost self-start text-muted" onClick={() => unpin(e)} title="Unpin">
                  <Icon name="pin" className="w-3.5 h-3.5" /> Unpin
                </button>
              )}
            </li>
          );
        })}
      </ul>
    </section>
  );
}
