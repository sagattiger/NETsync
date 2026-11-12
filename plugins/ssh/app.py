"""NETsync SSH gateway plugin: browser terminals (see gateway.py) plus the account lifecycle.

Routes:
  GET  /health, /manifest                  plugin protocol (manifest needs the secret)
  WS   /public/ws                          the browser terminal (ticket as subprotocol "ticket.<ticket>")
  GET  /admin/info                         gateway key, trusted host keys, managed accounts (secret)
  POST /admin/setup {"source"}             setup script for servers (secret)
  POST /admin/check {"host","port"}        is a server set up? (secret)
  POST /admin/forget-host {"target"}       forget a host key after a reinstall (secret)
  POST /admin/remove {"account"}           remove an account from every server now (secret)
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import time

import asyncssh
import httpx
from fastapi import Request, WebSocket, WebSocketDisconnect
from gateway import Gateway, GatewayError, Store, Ticket, setup_script, target_of, valid_password, verify
from netsync_plugin import NetsyncPlugin

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("netsync.ssh")

plugin = NetsyncPlugin("ssh", version="0.1.0", permissions=["terminal", "events"],
                       description="SSH terminal in the browser with per-user accounts on Linux servers")
store = Store()
gw = Gateway(store)
app = plugin.app()
MAX_TRIES = 3
RECONCILE_EVERY = 3600
REMOVALS_EVERY = 600


# --------------------------------------------------------------------------- reporting to NETsync

async def report(sid: str, **fields) -> None:
    try:
        async with httpx.AsyncClient(timeout=10) as c:
            await c.patch(f"{plugin.netsync_url}/api/plugin-api/terminal/sessions/{sid}",
                          headers={"Authorization": f"Bearer {plugin.secret}"}, json=fields)
    except httpx.HTTPError as e:
        log.warning("could not report session %s: %s", sid, e)


# --------------------------------------------------------------------------- the terminal socket

class Socket:
    """The browser side: JSON control messages in text frames, terminal bytes in binary frames."""

    def __init__(self, ws: WebSocket):
        self.ws = ws
        self.cols, self.rows = 120, 32

    async def send(self, **msg) -> None:
        await self.ws.send_text(json.dumps(msg))

    async def control(self, *kinds: str) -> dict:
        """Wait for one of these messages; size updates are remembered, keystrokes before login are dropped."""
        while True:
            raw = await self.ws.receive_text()
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if msg.get("t") == "resize":
                self.size(msg)
            elif msg.get("t") in kinds:
                return msg

    def size(self, msg: dict) -> tuple[int, int]:
        self.cols = max(10, min(int(msg.get("cols") or self.cols), 500))
        self.rows = max(4, min(int(msg.get("rows") or self.rows), 200))
        return self.cols, self.rows


async def authenticate(sock: Socket, t: Ticket) -> asyncssh.SSHClientConnection:
    """Prepare the account, then log in as it (asking for or setting the user's password)."""
    await sock.send(t="status", msg=f"Preparing {t.account} on {t.hostname}…")
    info = await gw.manage(t.host, t.port, "ensure", t.account, t.level)
    store.remember(target_of(t.host, t.port), t, bool(info.get("created")))
    new = "new" if not info.get("has_password") else None
    tries = 0
    while True:
        if new:
            await sock.send(t="set_password", account=t.account, host=t.hostname, reason=new, min=10)
            msg = await sock.control("new_password", "cancel")
            if msg["t"] == "cancel":
                raise GatewayError("Cancelled.")
            pw = str(msg.get("v") or "")
            if err := valid_password(pw):
                await sock.send(t="password_error", msg=err)
                continue
            try:
                await gw.manage(t.host, t.port, "passwd", t.account, stdin=pw + "\n")
            except GatewayError as e:
                await sock.send(t="password_error", msg=str(e))
                continue
            new = None
        else:
            await sock.send(t="ask_password", account=t.account, host=t.hostname, retry=tries > 0)
            msg = await sock.control("password", "reset_password", "cancel")
            if msg["t"] == "cancel":
                raise GatewayError("Cancelled.")
            if msg["t"] == "reset_password":
                new = "reset"
                continue
            pw = str(msg.get("v") or "")
        await sock.send(t="status", msg=f"Logging in as {t.account}…")
        try:
            return await gw.login(t.host, t.port, t.account, pw)
        except asyncssh.PermissionDenied:
            tries += 1
            if tries >= MAX_TRIES:
                raise GatewayError("Wrong password too many times.") from None


async def bridge(sock: Socket, proc: asyncssh.SSHClientProcess) -> tuple[int, int]:
    counts = [0, 0]  # bytes to the server, bytes to the browser

    async def server_to_browser():
        while True:
            data = await proc.stdout.read(65536)
            if not data:
                return
            counts[1] += len(data)
            await sock.ws.send_bytes(data)  # waits while the browser is slow: natural back-pressure

    async def browser_to_server():
        while True:
            m = await sock.ws.receive()
            if m["type"] == "websocket.disconnect":
                return
            if m.get("bytes"):
                counts[0] += len(m["bytes"])
                proc.stdin.write(m["bytes"])
                continue
            try:
                msg = json.loads(m.get("text") or "{}")
            except json.JSONDecodeError:
                continue
            if msg.get("t") == "input" and isinstance(msg.get("d"), str):
                data = msg["d"].encode()
                counts[0] += len(data)
                proc.stdin.write(data)
            elif msg.get("t") == "resize":
                proc.change_terminal_size(*sock.size(msg))
            elif msg.get("t") == "ping":
                await sock.send(t="pong")

    tasks = [asyncio.create_task(server_to_browser()), asyncio.create_task(browser_to_server())]
    try:
        await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
    return counts[0], counts[1]


@app.websocket("/public/ws")
async def terminal(ws: WebSocket):
    offered = ws.scope.get("subprotocols") or []
    token = next((p[len("ticket."):] for p in offered if p.startswith("ticket.")), "")
    try:
        t = verify(token, plugin.secret)
    except GatewayError as e:
        await ws.close(code=4401, reason=str(e)[:100])
        return
    await ws.accept(subprotocol=f"ticket.{token}")
    sock = Socket(ws)
    started, status, reason, sent = time.time(), "failed", "", (0, 0)
    conn = None
    try:
        conn = await authenticate(sock, t)
        proc = await conn.create_process(term_type="xterm-256color", term_size=(sock.cols, sock.rows), encoding=None)
        await sock.send(t="connected", account=t.account, host=t.hostname, level=t.level)
        await report(t.sid, status="connected", account=t.account)
        status = "ended"
        sent = await bridge(sock, proc)
        reason = "closed"
    except GatewayError as e:
        reason = str(e)
        with contextlib.suppress(Exception):
            await sock.send(t="error", msg=reason)
    except WebSocketDisconnect:
        reason = "browser closed" if status == "ended" else "closed before login"
    except (asyncssh.Error, OSError) as e:
        reason = f"connection lost: {e}"
        with contextlib.suppress(Exception):
            await sock.send(t="error", msg=reason)
    finally:
        if conn is not None:
            conn.close()
        with contextlib.suppress(Exception):
            await sock.send(t="closed", reason=reason)
            await ws.close()
        await report(t.sid, status=status, reason=reason[:500], bytes_in=sent[0], bytes_out=sent[1],
                     seconds=round(time.time() - started, 1))


# --------------------------------------------------------------------------- admin (NETsync core only)

def _admin(request: Request) -> None:
    plugin._check(request)


@app.get("/admin/info")
async def info(request: Request):
    _admin(request)
    return {"public_key": store.public_key, "host_keys": store.host_keys(), "accounts": store.accounts(),
            "pending_removals": store.pending_removals()}


@app.post("/admin/setup")
async def setup(request: Request):
    _admin(request)
    body = await request.json()
    try:
        return {"script": setup_script(store.public_key, str(body.get("source") or "")), "public_key": store.public_key}
    except GatewayError as e:
        return {"error": str(e)}


@app.post("/admin/check")
async def check(request: Request):
    _admin(request)
    body = await request.json()
    try:
        out = await gw.manage(str(body["host"]), int(body.get("port") or 22), "check")
        return {"ok": True, "version": out.get("version")}
    except GatewayError as e:
        return {"ok": False, "error": str(e)}


@app.post("/admin/forget-host")
async def forget_host(request: Request):
    _admin(request)
    body = await request.json()
    return {"ok": store.forget_host(str(body.get("target") or ""))}


@app.post("/admin/remove")
async def remove_now(request: Request):
    _admin(request)
    body = await request.json()
    account = str(body.get("account") or "")
    queued = store.queue_removal(account)
    done = await gw.run_removals()
    return {"queued": queued, "removed": done, "pending": store.pending_removals()}


# --------------------------------------------------------------------------- account lifecycle

async def reconcile() -> None:
    """Remove accounts of NETsync users that no longer exist or are disabled."""
    async with httpx.AsyncClient(timeout=30) as c:
        r = await c.get(f"{plugin.netsync_url}/api/plugin-api/terminal/accounts",
                        headers={"Authorization": f"Bearer {plugin.secret}"})
        r.raise_for_status()
        active = set(r.json().get("accounts") or [])
    for acc in {a["account"] for a in store.accounts()} - active:
        log.info("%s is no longer a NETsync user: removing it from every server", acc)
        store.queue_removal(acc)
    await gw.run_removals()


async def lifecycle() -> None:
    last_reconcile = 0.0
    while True:
        try:
            if time.time() - last_reconcile > RECONCILE_EVERY:
                await reconcile()
                last_reconcile = time.time()
            else:
                await gw.run_removals()
        except Exception as e:  # noqa: BLE001 - keep the loop alive
            log.warning("account check failed: %s", e)
        await asyncio.sleep(REMOVALS_EVERY)


async def listen() -> None:
    """React at once when NETsync removes or disables a user."""
    while True:
        try:
            async for ev in plugin.events():
                if ev.get("type") == "terminal_account_removed" and ev.get("account"):
                    if store.queue_removal(str(ev["account"])):
                        await gw.run_removals()
        except Exception as e:  # noqa: BLE001 - reconnect
            log.info("event stream ended (%s), reconnecting", e)
        await asyncio.sleep(10)


@app.on_event("startup")
async def start() -> None:
    app.state.tasks = [asyncio.create_task(lifecycle()), asyncio.create_task(listen())]
