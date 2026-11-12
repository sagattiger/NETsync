import { createContext, ReactNode, useCallback, useContext, useEffect, useMemo, useRef, useState } from "react";
import { Link, matchPath, useLocation } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api, auth, fmtAgo } from "../api";
import { useAI } from "./AskAI";
import { Icon } from "./Icon";
import { Markdown } from "./Markdown";

/* AI coworker: a chat docked to the right of the page. The model answers from NETsync's read-only tools
   (alert history, syslog, graphs...), each tool it used is shown above the answer. Conversations are saved per user. */

export interface ChatMsg {
  id: number | string; role: "user" | "assistant" | "tool"; content: string;
  tool?: string | null; arguments?: Record<string, any> | null;
  result?: { status?: string; call_id?: number; error?: string | null; message?: string | null; result?: any } | null;
  model?: string | null; duration?: number | null; created_at?: string;
  streaming?: boolean; failed?: boolean;
}
interface Conversation { id: number; title: string; updated_at: string }
interface ConversationFull extends Conversation { messages: ChatMsg[]; busy: boolean }

const OPEN_KEY = "netsync_chat_open";
const CONV_KEY = "netsync_chat_conversation";
const store = {
  get: (k: string) => { try { return localStorage.getItem(k); } catch { return null; } },
  set: (k: string, v: string | null) => { try { v === null ? localStorage.removeItem(k) : localStorage.setItem(k, v); } catch { /* unavailable */ } },
};

interface ChatApi {
  enabled: boolean; model: string | null; open: boolean;
  setOpen: (v: boolean) => void; toggle: () => void;
  ask: (text: string) => void;
  pending: string | null; clearPending: () => void;
}
const Ctx = createContext<ChatApi | null>(null);
export const useChat = () => useContext(Ctx);

/** Reads "data: {...}" events from a streamed POST. */
async function streamPost(path: string, body: unknown, onEvent: (ev: any) => void, signal: AbortSignal) {
  const res = await fetch(`/api${path}`, {
    method: "POST", signal,
    headers: { "Content-Type": "application/json", ...(auth.token ? { Authorization: `Bearer ${auth.token}` } : {}) },
    body: JSON.stringify(body),
  });
  if (!res.ok || !res.body) {
    let detail = res.statusText;
    try { detail = (await res.json()).detail ?? detail; } catch { /* not json */ }
    throw new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
  }
  const reader = res.body.getReader();
  const dec = new TextDecoder();
  let buf = "";
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    buf += dec.decode(value, { stream: true });
    let i;
    while ((i = buf.indexOf("\n\n")) >= 0) {
      const block = buf.slice(0, i);
      buf = buf.slice(i + 2);
      const data = block.split("\n").filter((l) => l.startsWith("data:")).map((l) => l.slice(5).trim()).join("");
      if (data) onEvent(JSON.parse(data));
    }
  }
}

export function ChatProvider({ children }: { children: ReactNode }) {
  const ai = useAI();
  const [open, setOpenState] = useState(() => store.get(OPEN_KEY) === "1");
  const [pending, setPending] = useState<string | null>(null);
  const enabled = !!ai?.chat;
  const setOpen = useCallback((v: boolean) => { setOpenState(v); store.set(OPEN_KEY, v ? "1" : "0"); }, []);
  const toggle = useCallback(() => setOpenState((o) => { store.set(OPEN_KEY, o ? "0" : "1"); return !o; }), []);
  const ask = useCallback((text: string) => { setOpen(true); setPending(text); }, [setOpen]);
  const clearPending = useCallback(() => setPending(null), []);
  const value = useMemo(() => ({ enabled, model: ai?.chat_model ?? null, open: open && enabled, setOpen, toggle, ask, pending, clearPending }),
    [enabled, ai?.chat_model, open, setOpen, toggle, ask, pending, clearPending]);
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

const TOOL_LABELS: Record<string, string> = {
  netsync__find_devices: "Looked up devices",
  netsync__device_overview: "Read the device overview",
  netsync__list_problems: "Listed open problems",
  netsync__alert_history: "Counted alerts",
  netsync__search_syslog: "Searched syslog",
  netsync__metric_summary: "Summarised a graph",
  netsync__call_result: "Checked a request",
};
const toolLabel = (name?: string | null) =>
  (name && TOOL_LABELS[name]) || (name ? name.split("__").pop()!.replace(/_/g, " ").replace(/^./, (c) => c.toUpperCase()) : "Tool");
const argLine = (args?: Record<string, any> | null) =>
  Object.entries(args || {}).filter(([, v]) => v !== "" && v !== null && v !== undefined).map(([k, v]) => `${k}: ${typeof v === "object" ? JSON.stringify(v) : v}`).join(" · ");

function ToolStep({ m }: { m: ChatMsg }) {
  const [open, setOpen] = useState(false);
  const st = m.result?.status ?? "running";
  const icon = st === "running" ? <Icon name="refresh" className="w-3.5 h-3.5 animate-spin text-muted" />
    : st === "done" ? <Icon name="check" className="w-3.5 h-3.5 text-ok" />
    : st === "pending" ? <Icon name="lock" className="w-3.5 h-3.5 text-warn" />
    : <Icon name="x" className="w-3.5 h-3.5 text-crit" />;
  return (
    <div className="rounded-lg border border-line bg-inset/40 text-xs">
      <button onClick={() => setOpen((o) => !o)} className="w-full flex items-center gap-2 px-2.5 py-1.5 text-left">
        {icon}
        <span className="font-medium text-strong shrink-0">{toolLabel(m.tool)}</span>
        <span className="text-muted truncate flex-1">{argLine(m.arguments)}</span>
        <Icon name="chevron" className={`w-3 h-3 text-muted transition-transform ${open ? "rotate-90" : ""}`} />
      </button>
      {st === "pending" && (
        <div className="px-2.5 pb-2 text-warn">
          Needs approval (request #{m.result?.call_id}). <Link to="/setup/ai-tools" className="underline">Open approvals</Link>
        </div>
      )}
      {st === "error" && m.result?.error && <div className="px-2.5 pb-2 text-crit break-words">{m.result.error}</div>}
      {open && (
        <pre className="mx-2.5 mb-2 p-2 rounded-md bg-surface border border-line text-[11px] leading-snug overflow-auto max-h-64 whitespace-pre-wrap break-all">
          {m.tool}{"\n"}{JSON.stringify(m.arguments ?? {}, null, 1)}{"\n\n"}{JSON.stringify(m.result?.result ?? m.result ?? null, null, 1)}
        </pre>
      )}
    </div>
  );
}

function Thinking({ since }: { since: number }) {
  const [, tick] = useState(0);
  useEffect(() => { const t = window.setInterval(() => tick((n) => n + 1), 1000); return () => window.clearInterval(t); }, []);
  const s = Math.round((Date.now() - since) / 1000);
  return (
    <div className="flex items-center gap-2 text-xs text-muted">
      <span className="flex gap-1">{[0, 1, 2].map((i) => <span key={i} className="w-1.5 h-1.5 rounded-full bg-accent animate-pulse" style={{ animationDelay: `${i * 150}ms` }} />)}</span>
      Thinking{s >= 3 ? ` · ${s}s` : "…"}{s >= 20 ? " (loading the model can take a while the first time)" : ""}
    </div>
  );
}

function suggestions(path: string): string[] {
  if (matchPath("/devices/:id/*", path)) return [
    "Summarise the health of this device",
    "How many alerts did this device have in the last 30 days, and for how long?",
    "Any errors in this device's syslog in the last day?",
    "What was the average and peak CPU load this week?",
  ];
  return [
    "What problems are open right now?",
    "Which devices have problems?",
    "Search syslog for 'error' in the last day",
  ];
}

export function ChatPanel({ onClose }: { onClose: () => void }) {
  const qc = useQueryClient();
  const loc = useLocation();
  const chat = useChat();
  const [convId, setConvId] = useState<number | null>(() => Number(store.get(CONV_KEY)) || null);
  const [msgs, setMsgs] = useState<ChatMsg[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [since, setSince] = useState(0);
  const [showHistory, setShowHistory] = useState(false);
  const [error, setError] = useState("");
  const abort = useRef<AbortController | null>(null);
  const scroller = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const stick = useRef(true);

  const convs = useQuery({ queryKey: ["chat-conversations"], queryFn: () => api<Conversation[]>("/plugins/ai/chat/conversations"), enabled: showHistory });

  const load = useCallback(async (id: number | null) => {
    setError("");
    if (!id) { setMsgs([]); return; }
    try {
      const c = await api<ConversationFull>(`/plugins/ai/chat/conversations/${id}`);
      setMsgs(c.messages);
      // an answer still being written (page reloaded meanwhile): check again shortly
      if (c.busy && c.messages[c.messages.length - 1]?.role !== "assistant") window.setTimeout(() => load(id), 2500);
    } catch {
      setConvId(null); store.set(CONV_KEY, null); setMsgs([]);
    }
  }, []);
  useEffect(() => { load(convId); /* eslint-disable-next-line react-hooks/exhaustive-deps */ }, []);
  useEffect(() => () => abort.current?.abort(), []);

  useEffect(() => {
    const el = scroller.current;
    if (el && stick.current) el.scrollTop = el.scrollHeight;
  }, [msgs, busy]);
  useEffect(() => { inputRef.current?.focus(); }, []);

  const select = (id: number | null) => {
    abort.current?.abort();
    setBusy(false);
    setConvId(id); store.set(CONV_KEY, id ? String(id) : null);
    setShowHistory(false);
    load(id);
  };

  const send = useCallback(async (raw: string) => {
    const text = raw.trim();
    if (!text || busy) return;
    setInput(""); setError(""); setBusy(true); setSince(Date.now()); stick.current = true;
    const tmp = `u${Date.now()}`;
    const live = `a${Date.now()}`;
    setMsgs((m) => [...m, { id: tmp, role: "user", content: text }, { id: live, role: "assistant", content: "", streaming: true }]);
    const ctrl = new AbortController();
    abort.current = ctrl;
    // tool steps go before the live answer
    const beforeLive = (m: ChatMsg[], add: ChatMsg) => { const i = m.findIndex((x) => x.id === live); return i < 0 ? [...m, add] : [...m.slice(0, i), add, ...m.slice(i)]; };
    const patchLive = (f: (x: ChatMsg) => ChatMsg) => setMsgs((m) => m.map((x) => (x.id === live ? f(x) : x)));
    let toolSeq = 0;
    try {
      await streamPost("/plugins/ai/chat", { message: text, conversation_id: convId, page: { path: loc.pathname, title: document.title } }, (ev) => {
        if (ev.type === "start") {
          if (ev.conversation_id !== convId) { setConvId(ev.conversation_id); store.set(CONV_KEY, String(ev.conversation_id)); }
          setMsgs((m) => m.map((x) => (x.id === tmp ? { ...x, id: ev.message_id } : x)));
        } else if (ev.type === "delta") {
          patchLive((x) => ({ ...x, content: x.content + ev.text }));
        } else if (ev.type === "reset") {
          patchLive((x) => ({ ...x, content: "" }));
        } else if (ev.type === "tool") {
          toolSeq += 1;
          setMsgs((m) => beforeLive(m, { id: `t${live}${toolSeq}`, role: "tool", content: "", tool: ev.tool, arguments: ev.arguments }));
        } else if (ev.type === "tool_result") {
          setMsgs((m) => m.map((x) => (x.id === `t${live}${toolSeq}` ? { ...x, id: ev.id, result: ev.result } : x)));
        } else if (ev.type === "error") {
          patchLive((x) => ({ ...x, content: x.content || `⚠ ${ev.error}`, failed: true }));
        } else if (ev.type === "done") {
          patchLive((x) => ({ ...x, id: ev.message_id, streaming: false, duration: ev.duration, model: ev.model }));
        }
      }, ctrl.signal);
    } catch (e: any) {
      if (e?.name !== "AbortError") {
        setError(e?.message || "The AI coworker did not answer");
        setMsgs((m) => m.filter((x) => x.id !== live && !(x.id === tmp)));
        setInput(text);
      }
    } finally {
      setBusy(false);
      patchLive((x) => ({ ...x, streaming: false }));
      qc.invalidateQueries({ queryKey: ["chat-conversations"] });
    }
  }, [busy, convId, loc.pathname, qc]);

  // "Follow up in chat" buttons elsewhere in the app: start a new chat with their question
  useEffect(() => {
    if (!chat?.pending || busy) return;
    const text = chat.pending;
    chat.clearPending();
    if (msgs.length) { abort.current?.abort(); setConvId(null); store.set(CONV_KEY, null); setMsgs([]); pendingNew.current = text; }
    else send(text);
  }, [chat, busy, msgs.length, send]);
  const pendingNew = useRef<string | null>(null);
  useEffect(() => {
    if (pendingNew.current && convId === null && msgs.length === 0) { const t = pendingNew.current; pendingNew.current = null; send(t); }
  }, [convId, msgs.length, send]);

  const remove = async (id: number) => {
    await api(`/plugins/ai/chat/conversations/${id}`, { method: "DELETE" }).catch(() => {});
    if (id === convId) select(null);
    qc.invalidateQueries({ queryKey: ["chat-conversations"] });
  };

  const iconBtn = "w-8 h-8 rounded-lg flex items-center justify-center text-muted hover:text-strong hover:bg-active/60";
  const empty = msgs.length === 0;

  return (
    <div className="h-full flex flex-col bg-sidebar overflow-hidden">
      <div className="h-14 shrink-0 flex items-center gap-1 px-3 border-b border-line">
        <span className="w-7 h-7 rounded-lg bg-accent/15 text-accent flex items-center justify-center shrink-0"><Icon name="sparkles" className="w-4 h-4" /></span>
        <div className="min-w-0 flex-1 ml-1.5">
          <div className="text-sm font-semibold text-strong leading-tight">AI coworker</div>
          <div className="text-xxs text-muted truncate">{chat?.model ?? "local model"} · read-only tools</div>
        </div>
        <button className={`${iconBtn} ${showHistory ? "bg-active text-strong" : ""}`} title="Earlier chats" onClick={() => setShowHistory((s) => !s)}><Icon name="list" className="w-4 h-4" /></button>
        <button className={iconBtn} title="New chat" onClick={() => select(null)}><Icon name="plus" className="w-4 h-4" /></button>
        <button className={iconBtn} title="Close" onClick={onClose}><Icon name="x" className="w-4 h-4" /></button>
      </div>

      {showHistory ? (
        <div className="flex-1 overflow-y-auto p-2 space-y-0.5">
          {convs.isLoading && <div className="p-3 text-sm text-muted">Loading…</div>}
          {convs.data?.length === 0 && <div className="p-3 text-sm text-muted">No earlier chats.</div>}
          {convs.data?.map((c) => (
            <div key={c.id} className={`group flex items-center gap-2 rounded-lg px-2.5 py-2 hover:bg-active/50 ${c.id === convId ? "bg-active" : ""}`}>
              <button className="flex-1 min-w-0 text-left" onClick={() => select(c.id)}>
                <div className="text-sm text-strong truncate">{c.title}</div>
                <div className="text-xxs text-muted">{fmtAgo(c.updated_at)}</div>
              </button>
              <button className="opacity-0 group-hover:opacity-100 text-muted hover:text-crit p-1" title="Delete chat" onClick={() => remove(c.id)}>
                <Icon name="trash" className="w-3.5 h-3.5" />
              </button>
            </div>
          ))}
        </div>
      ) : (
        <div ref={scroller} className="flex-1 overflow-y-auto px-3 py-4 space-y-3"
          onScroll={(e) => { const el = e.currentTarget; stick.current = el.scrollHeight - el.scrollTop - el.clientHeight < 60; }}>
          {empty && (
            <div className="pt-6 space-y-4">
              <div className="text-center px-4">
                <div className="text-base font-semibold text-strong">Ask about your network</div>
                <div className="text-xs text-muted mt-1">Alerts, how often and how long they happened, syslog, graphs. The answers come from NETsync's data; each lookup is shown.</div>
              </div>
              <div className="space-y-1.5">
                {suggestions(loc.pathname).map((s) => (
                  <button key={s} onClick={() => send(s)} className="w-full text-left text-sm px-3 py-2 rounded-lg border border-line hover:border-accent/50 hover:bg-active/40 text-fg2">{s}</button>
                ))}
              </div>
            </div>
          )}
          {msgs.map((m) => m.role === "user" ? (
            <div key={m.id} className="flex justify-end">
              <div className="max-w-[85%] rounded-2xl rounded-br-md px-3 py-2 bg-accent text-white text-sm whitespace-pre-wrap break-words">{m.content}</div>
            </div>
          ) : m.role === "tool" ? (
            <ToolStep key={m.id} m={m} />
          ) : (
            <div key={m.id} className="text-sm">
              {m.streaming && !m.content ? <Thinking since={since} /> : (
                <>
                  <Markdown source={m.content || "_(no answer)_"} className={m.failed ? "text-crit" : ""} />
                  {!m.streaming && (m.duration || m.model) && (
                    <div className="text-xxs text-faint mt-1">{m.model}{m.duration ? ` · ${m.duration.toFixed(1)} s` : ""}</div>
                  )}
                </>
              )}
            </div>
          ))}
          {error && <div className="text-xs text-crit bg-crit/10 rounded-lg px-3 py-2">{error}</div>}
        </div>
      )}

      <form className="shrink-0 p-3 border-t border-line" onSubmit={(e) => { e.preventDefault(); send(input); }}>
        <div className="flex items-end gap-2 rounded-xl border border-line bg-surface focus-within:border-accent/60 px-2 py-1.5">
          <textarea ref={inputRef} rows={1} value={input} maxLength={4000}
            onChange={(e) => { setInput(e.target.value); e.target.style.height = "auto"; e.target.style.height = `${Math.min(e.target.scrollHeight, 160)}px`; }}
            onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(input); } }}
            placeholder={busy ? "Answering…" : "Ask the AI coworker…"}
            className="flex-1 resize-none bg-transparent outline-none text-sm py-1 max-h-40 text-strong placeholder:text-muted" />
          {busy ? (
            <button type="button" onClick={() => abort.current?.abort()} title="Stop following (the answer is still saved)"
              className="w-8 h-8 rounded-lg bg-active text-strong flex items-center justify-center shrink-0"><Icon name="pause" className="w-4 h-4" /></button>
          ) : (
            <button type="submit" disabled={!input.trim()} title="Send"
              className="w-8 h-8 rounded-lg bg-accent text-white flex items-center justify-center shrink-0 disabled:opacity-40"><Icon name="arrow" className="w-4 h-4" /></button>
          )}
        </div>
        <div className="text-xxs text-faint mt-1.5 px-1">Small local model: check important numbers in the tool details.</div>
      </form>
    </div>
  );
}
