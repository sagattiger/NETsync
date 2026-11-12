import { FormEvent, useCallback, useEffect, useRef, useState } from "react";
import { Terminal } from "@xterm/xterm";
import { FitAddon } from "@xterm/addon-fit";
import { WebLinksAddon } from "@xterm/addon-web-links";
import "@xterm/xterm/css/xterm.css";
import { api } from "../api";
import { Icon } from "./Icon";

/* Browser SSH terminal (plugins/ssh). NETsync signs a one-minute ticket with the user's rights on the device; the
   socket goes to the plugin, which prepares the user's own account (ns-<user>) on the server and logs in with the
   user's password for that server. Binary frames are terminal bytes, text frames are JSON control messages. */

interface Opened { session_id: string; ticket: string; socket: string; account: string; level: string; level_label: string; hostname: string }
type Phase = "idle" | "opening" | "status" | "ask_password" | "set_password" | "connected" | "closed";

const THEME = {
  background: "#0d1117", foreground: "#e6edf3", cursor: "#e6edf3", selectionBackground: "#264f78",
  black: "#484f58", red: "#ff7b72", green: "#3fb950", yellow: "#d29922", blue: "#58a6ff", magenta: "#bc8cff",
  cyan: "#39c5cf", white: "#b1bac4", brightBlack: "#6e7681", brightRed: "#ffa198", brightGreen: "#56d364",
  brightYellow: "#e3b341", brightBlue: "#79c0ff", brightMagenta: "#d2a8ff", brightCyan: "#56d4dd", brightWhite: "#f0f6fc",
};

export function TerminalView({ deviceId, className = "", onTitle, autoConnect = true }: {
  deviceId: number; className?: string; onTitle?: (t: string) => void; autoConnect?: boolean;
}) {
  const box = useRef<HTMLDivElement>(null);
  const term = useRef<Terminal | null>(null);
  const fit = useRef<FitAddon | null>(null);
  const ws = useRef<WebSocket | null>(null);
  const [phase, setPhase] = useState<Phase>("idle");
  const [info, setInfo] = useState<Opened | null>(null);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const [prompt, setPrompt] = useState<{ account: string; host: string; retry?: boolean; reason?: string; min?: number } | null>(null);
  const [pw, setPw] = useState("");
  const [pw2, setPw2] = useState("");
  const [pwError, setPwError] = useState("");
  const [wasConnected, setWasConnected] = useState(false);

  const send = (msg: object) => { if (ws.current?.readyState === WebSocket.OPEN) ws.current.send(JSON.stringify(msg)); };

  // xterm once per component
  useEffect(() => {
    const t = new Terminal({
      fontFamily: '"JetBrains Mono", "Cascadia Mono", Menlo, Consolas, monospace', fontSize: 13, cursorBlink: true,
      scrollback: 5000, theme: THEME, allowProposedApi: false, convertEol: false,
    });
    const f = new FitAddon();
    t.loadAddon(f);
    t.loadAddon(new WebLinksAddon());
    t.open(box.current!);
    term.current = t;
    fit.current = f;
    const onData = t.onData((d) => send({ t: "input", d }));
    const resize = () => {
      try { f.fit(); } catch { /* hidden */ }
      send({ t: "resize", cols: t.cols, rows: t.rows });
    };
    const ro = new ResizeObserver(resize);
    ro.observe(box.current!);
    resize();
    return () => { ro.disconnect(); onData.dispose(); ws.current?.close(); t.dispose(); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const connect = useCallback(async () => {
    ws.current?.close();
    setError(""); setPrompt(null); setPhase("opening"); setMessage("Opening…"); setWasConnected(false);
    term.current?.reset();
    let o: Opened;
    try {
      o = await api<Opened>("/terminal/sessions", { body: { device_id: deviceId } });
    } catch (e: any) {
      setPhase("closed"); setError(e.message); return;
    }
    setInfo(o);
    onTitle?.(o.hostname);
    const proto = location.protocol === "https:" ? "wss" : "ws";
    const sock = new WebSocket(`${proto}://${location.host}${o.socket}`, [`ticket.${o.ticket}`]);
    sock.binaryType = "arraybuffer";
    ws.current = sock;
    let ping: number | undefined;
    sock.onopen = () => {
      const t = term.current!;
      sock.send(JSON.stringify({ t: "resize", cols: t.cols, rows: t.rows }));
      ping = window.setInterval(() => sock.readyState === WebSocket.OPEN && sock.send(JSON.stringify({ t: "ping" })), 30_000);
    };
    sock.onmessage = (ev) => {
      if (typeof ev.data !== "string") { term.current?.write(new Uint8Array(ev.data)); return; }
      const m = JSON.parse(ev.data);
      if (m.t === "status") { setPhase("status"); setMessage(m.msg); }
      else if (m.t === "ask_password" || m.t === "set_password") {
        setPw(""); setPw2(""); setPwError(m.retry ? "Wrong password, try again." : "");
        setPrompt({ account: m.account, host: m.host, retry: m.retry, reason: m.reason, min: m.min });
        setPhase(m.t);
      } else if (m.t === "password_error") { setPwError(m.msg); }
      else if (m.t === "connected") { setPhase("connected"); setWasConnected(true); setPrompt(null); setTimeout(() => { fit.current?.fit(); term.current?.focus(); }, 0); }
      else if (m.t === "error") { setError(m.msg); }
      else if (m.t === "closed") { setPhase("closed"); setMessage(m.reason || "Closed"); }
    };
    sock.onclose = (ev) => {
      window.clearInterval(ping);
      setPhase((p) => (p === "closed" ? p : "closed"));
      if (ev.code === 4401) setError(ev.reason || "The terminal refused the session ticket.");
      else setMessage((m) => m || "Disconnected");
    };
  }, [deviceId, onTitle]);

  useEffect(() => { if (autoConnect) connect(); /* eslint-disable-next-line react-hooks/exhaustive-deps */ }, [deviceId]);

  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (phase === "set_password") {
      if (pw.length < (prompt?.min ?? 10)) { setPwError(`At least ${prompt?.min ?? 10} characters.`); return; }
      if (pw !== pw2) { setPwError("The passwords don't match."); return; }
      send({ t: "new_password", v: pw });
    } else {
      send({ t: "password", v: pw });
    }
    setPwError(""); setPhase("status"); setMessage("Checking…"); setPw(""); setPw2("");
  };

  // after a session ends the output stays readable; only a bar at the bottom offers to reconnect
  const overlay = phase !== "connected" && !(phase === "closed" && wasConnected && !error);
  return (
    <div className={`relative flex flex-col rounded-xl overflow-hidden border border-line bg-[#0d1117] ${className}`}>
      <div className="h-9 shrink-0 flex items-center gap-2 px-3 text-xs bg-[#161b22] text-[#8b949e] border-b border-[#30363d]">
        <span className={`w-2 h-2 rounded-full ${phase === "connected" ? "bg-ok" : phase === "closed" ? "bg-crit" : "bg-warn animate-pulse"}`} />
        <span className="text-[#e6edf3] font-medium truncate">{info ? `${info.account}@${info.hostname}` : "Terminal"}</span>
        {info && <span className="px-1.5 py-0.5 rounded bg-[#30363d] text-[10px] uppercase tracking-wide">{info.level_label}</span>}
        <span className="flex-1" />
        {phase === "connected" && (
          <button className="hover:text-white px-1.5" title="Disconnect" onClick={() => ws.current?.close()}><Icon name="x" className="w-3.5 h-3.5" /></button>
        )}
        {phase === "closed" && (
          <button className="hover:text-white flex items-center gap-1 px-1.5" onClick={connect}><Icon name="refresh" className="w-3.5 h-3.5" /> Reconnect</button>
        )}
      </div>
      <div className="relative flex-1 min-h-0">
        <div ref={box} className="absolute inset-0 p-1.5" />
        {overlay && (
          <div className="absolute inset-0 bg-[#0d1117]/85 flex items-center justify-center p-4">
            {(phase === "ask_password" || phase === "set_password") && prompt ? (
              <form onSubmit={submit} className="w-full max-w-sm rounded-xl border border-[#30363d] bg-[#161b22] p-5 space-y-3 text-[#e6edf3]">
                <div className="flex items-center gap-2"><Icon name="lock" className="w-4 h-4 text-accent" />
                  <span className="font-semibold">{phase === "set_password" ? (prompt.reason === "reset" ? "Choose a new password" : "Choose your password") : "Password"}</span></div>
                <p className="text-xs text-[#8b949e]">
                  {phase === "set_password"
                    ? <>NETsync created <b className="text-[#e6edf3]">{prompt.account}</b> for you on <b className="text-[#e6edf3]">{prompt.host}</b>{prompt.reason === "reset" ? " already. The new password replaces the old one." : ". This password is only for this server; you'll use it here and for sudo."}</>
                    : <>Your password for <b className="text-[#e6edf3]">{prompt.account}</b> on <b className="text-[#e6edf3]">{prompt.host}</b>.</>}
                </p>
                <input type="password" autoFocus autoComplete={phase === "set_password" ? "new-password" : "current-password"} value={pw}
                  onChange={(e) => setPw(e.target.value)} placeholder="Password"
                  className="w-full h-9 rounded-lg bg-[#0d1117] border border-[#30363d] px-3 text-sm outline-none focus:border-accent" />
                {phase === "set_password" && (
                  <input type="password" autoComplete="new-password" value={pw2} onChange={(e) => setPw2(e.target.value)} placeholder="Repeat password"
                    className="w-full h-9 rounded-lg bg-[#0d1117] border border-[#30363d] px-3 text-sm outline-none focus:border-accent" />
                )}
                {pwError && <div className="text-xs text-crit">{pwError}</div>}
                <div className="flex items-center gap-2 pt-1">
                  {phase === "ask_password" && (
                    <button type="button" className="text-xs text-[#8b949e] hover:text-white underline" onClick={() => send({ t: "reset_password" })}>Forgot it? Set a new one</button>
                  )}
                  <span className="flex-1" />
                  <button type="button" className="btn h-8" onClick={() => send({ t: "cancel" })}>Cancel</button>
                  <button type="submit" className="btn btn-primary h-8" disabled={!pw}>{phase === "set_password" ? "Save and connect" : "Connect"}</button>
                </div>
              </form>
            ) : (
              <div className="text-center space-y-3 max-w-md">
                {phase === "closed" ? <Icon name="terminal" className="w-6 h-6 mx-auto text-[#8b949e]" /> : <Icon name="refresh" className="w-5 h-5 mx-auto text-[#8b949e] animate-spin" />}
                {error ? <div className="text-sm text-crit break-words">{error}</div> : <div className="text-sm text-[#8b949e]">{phase === "idle" ? "Not connected" : message}</div>}
                {(phase === "closed" || phase === "idle") && <button className="btn btn-primary h-8" onClick={connect}>{phase === "idle" ? "Connect" : "Connect again"}</button>}
              </div>
            )}
          </div>
        )}
        {phase === "closed" && wasConnected && !error && (
          <div className="absolute left-0 right-0 bottom-0 flex items-center gap-3 px-3 py-2 bg-[#161b22] border-t border-[#30363d] text-xs text-[#8b949e]">
            <span className="flex-1 truncate">Session ended{message ? `: ${message}` : ""}</span>
            <button className="btn btn-primary h-7" onClick={connect}>Connect again</button>
          </div>
        )}
      </div>
    </div>
  );
}
