"""SSH bastion: desktop SSH clients (OpenSSH, PuTTY, Muxus...) reach servers through NETsync.

    ssh -p 2222 alice:pve002@netsync-host        (also "alice@pve002" as user name: ssh -l alice@pve002)

Everything happens in keyboard-interactive prompts, which every client supports:

1. "NETsync password for alice": NETsync checks it, the user's rights on the server, and opens an audited session.
2. The gateway prepares ns-alice on the server (as for the web terminal), then asks for its password, or lets the
   user choose one the first time.
3. The gateway logs in as ns-alice and connects the client's shell or command to it.

The gateway ends the SSH connection itself (no plain jump host), so NETsync decides who gets in and with which
rights, and the server sees the user's own account. Port forwarding, agent forwarding and SFTP are off.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import re
import time
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

import asyncssh
import httpx
from gateway import Gateway, GatewayError, Store, Ticket, target_of, valid_password

log = logging.getLogger("netsync.bastion")

TITLE = "NETsync"
USER = re.compile(r"^(?P<user>[^:@+/\s]{1,64})[:@+/](?P<target>[A-Za-z0-9._:-]{1,255})$")
MAX_TRIES = 3


def parse_username(raw: str) -> tuple[str, str] | None:
    m = USER.match(raw or "")
    return (m.group("user"), m.group("target")) if m else None


class CoreError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status


class Core:
    """Calls into NETsync (the plugin API)."""

    def __init__(self, url: str, secret: str):
        self.url, self.secret = url.rstrip("/"), secret

    async def login(self, username: str, password: str, target: str, client_ip: str) -> dict:
        try:
            async with httpx.AsyncClient(timeout=20) as c:
                r = await c.post(f"{self.url}/api/plugin-api/terminal/bastion", json={
                    "username": username, "password": password, "target": target, "client_ip": client_ip},
                    headers={"Authorization": f"Bearer {self.secret}"})
        except httpx.HTTPError as e:
            raise CoreError(503, f"NETsync is not reachable: {e}") from e
        if r.status_code >= 400:
            try:
                detail = r.json().get("detail") or r.text
            except ValueError:
                detail = r.text
            raise CoreError(r.status_code, str(detail)[:300])
        return r.json()


Report = Callable[..., Awaitable[None]]


def host_key(store: Store) -> asyncssh.SSHKey:
    f = Path(store.dir) / "bastion_ed25519"
    if not f.exists():
        f.write_bytes(asyncssh.generate_private_key("ssh-ed25519", comment="netsync-bastion").export_private_key())
        f.chmod(0o600)
    return asyncssh.read_private_key(str(f))


class BastionServer(asyncssh.SSHServer):
    """One per client connection: walks through the prompts, then holds the connection to the server."""

    def __init__(self, gw: Gateway, store: Store, core: Core, report: Report):
        self.gw, self.store, self.core, self.report = gw, store, core, report
        self.state = "start"
        self.user = self.target = ""
        self.peer = ""
        self.ticket: Ticket | None = None
        self.upstream: asyncssh.SSHClientConnection | None = None
        self.tries = 0
        self.message = ""
        self.conn: asyncssh.SSHServerConnection | None = None
        self.attempts = 0  # NETsync password attempts on this connection
        self.started = time.time()
        self.sent = [0, 0]
        self.reported = False

    # ------------------------------------------------------------------ connection

    def connection_made(self, conn: asyncssh.SSHServerConnection) -> None:
        peer = conn.get_extra_info("peername") or ("", 0)
        self.peer = str(peer[0])
        self.conn = conn

    def connection_lost(self, exc: Exception | None) -> None:
        if self.upstream is not None:
            self.upstream.close()
        if self.ticket and not self.reported:
            self.reported = True
            asyncio.get_event_loop().create_task(self.report(
                self.ticket.sid, status="ended" if self.state == "done" else "failed",
                reason=("closed" if self.state == "done" else f"left at {self.state}") + " (desktop client)",
                bytes_in=self.sent[0], bytes_out=self.sent[1], seconds=round(time.time() - self.started, 1)))

    def begin_auth(self, username: str) -> bool:
        return True

    def password_auth_supported(self) -> bool:
        return False

    def public_key_auth_supported(self) -> bool:
        return False

    def kbdint_auth_supported(self) -> bool:
        return True

    # ------------------------------------------------------------------ prompts

    @staticmethod
    def challenge(instructions: str, *prompts: tuple[str, bool]):
        return TITLE, instructions, "", list(prompts)

    def fatal(self, message: str):
        self.state, self.message = "fatal", message
        log.info("bastion %s %s:%s: %s", self.peer, self.user, self.target, message)
        return self.challenge(message, ("Press Enter to close: ", True))

    def get_kbdint_challenge(self, username: str, lang: str, submethods: str):
        # clients retry keyboard-interactive after a failure: after an error or 3 wrong passwords, refuse outright
        if self.state == "fatal" or self.attempts >= MAX_TRIES:
            reason = self.message or "Too many failed logins."
            asyncio.get_event_loop().call_soon(self.conn.disconnect, asyncssh.DISC_NO_MORE_AUTH_METHODS_AVAILABLE, reason)
            return False
        parsed = parse_username(username)
        if not parsed:
            return self.fatal("Log in as <your NETsync user>:<server>, for example: ssh -p 2222 alice:pve002@netsync")
        self.user, self.target = parsed
        self.state = "netsync"
        return self.challenge(f"Connecting to {self.target}.", (f"NETsync password for {self.user}: ", False))

    async def validate_kbdint_response(self, username: str, responses: list[str]) -> Any:
        answer = responses[0] if responses else ""
        if self.state == "netsync":
            return await self._netsync(answer)
        if self.state == "new":
            return await self._new_password(responses)
        if self.state == "server":
            return await self._login(answer)
        return False  # fatal or unexpected

    async def _netsync(self, password: str):
        try:
            info = await self.core.login(self.user, password, self.target, self.peer)
        except CoreError as e:
            if e.status == 401:
                self.attempts += 1
                return False  # wrong NETsync password: the client asks again (up to 3 times)
            return self.fatal(str(e))
        self.ticket = Ticket(sid=info["sid"], username=self.user, account=info["account"], level=info["level"],
                             device_id=int(info["device_id"]), hostname=info["hostname"], host=info["host"],
                             port=int(info.get("port", 22)), exp=time.time() + 60)
        t = self.ticket
        try:
            out = await self.gw.manage(t.host, t.port, "ensure", t.account, t.level)
        except GatewayError as e:
            return self.fatal(str(e))
        self.store.remember(target_of(t.host, t.port), t, bool(out.get("created")))
        if out.get("has_password"):
            self.state = "server"
            return self.challenge(f"Logged in to NETsync as {self.user} ({info.get('level_label', t.level)}).",
                                  (f"Password for {t.account} on {t.hostname}: ", False))
        self.state = "new"
        return self.challenge(
            f"NETsync created {t.account} for you on {t.hostname}. Choose its password (at least 10 characters). "
            f"You'll use it here, in the NETsync web terminal, and for sudo.",
            ("New password: ", False), ("Repeat it: ", False))

    async def _new_password(self, responses: list[str]):
        t = self.ticket
        pw, again = (list(responses) + ["", ""])[:2]
        if pw != again:
            return self.challenge("The passwords don't match.", ("New password: ", False), ("Repeat it: ", False))
        if err := valid_password(pw):
            return self.challenge(err, ("New password: ", False), ("Repeat it: ", False))
        try:
            await self.gw.manage(t.host, t.port, "passwd", t.account, stdin=pw + "\n")
        except GatewayError as e:
            return self.challenge(str(e), ("New password: ", False), ("Repeat it: ", False))
        return await self._login(pw)

    async def _login(self, password: str):
        t = self.ticket
        try:
            self.upstream = await self.gw.login(t.host, t.port, t.account, password)
        except asyncssh.PermissionDenied:
            self.tries += 1
            if self.tries >= MAX_TRIES:
                self.state, self.message = "fatal", "Wrong server password too many times."
                return False
            self.state = "server"
            return self.challenge("Wrong password, try again.", (f"Password for {t.account} on {t.hostname}: ", False))
        except GatewayError as e:
            return self.fatal(str(e))
        self.state = "done"
        await self.report(t.sid, status="connected", account=t.account)
        return True


async def handle(process: asyncssh.SSHServerProcess) -> None:
    """Connect the client's shell or command to the same on the server."""
    srv: BastionServer = process.get_extra_info("connection").get_owner()
    up = srv.upstream
    if up is None:
        process.exit(1)
        return
    if process.subsystem:
        process.stderr.write(f"NETsync: {process.subsystem} is not available through the bastion yet.\r\n".encode())
        process.exit(1)
        return
    kw: dict[str, Any] = {}
    if process.term_type:
        cols, rows = process.term_size[:2]
        kw = {"term_type": process.term_type, "term_size": (cols or 80, rows or 24)}
    remote = await up.create_process(process.command, encoding=None, **kw)

    async def pump(reader, writer, index):
        while True:
            data = await reader.read(65536)
            if not data:
                return
            srv.sent[index] += len(data)
            writer.write(data)

    async def client_to_server():
        while True:
            try:
                data = await process.stdin.read(65536)
            except asyncssh.TerminalSizeChanged as e:
                remote.change_terminal_size(e.width, e.height)
                continue
            except asyncssh.BreakReceived:
                continue
            if not data:
                remote.stdin.write_eof()
                return
            srv.sent[0] += len(data)
            remote.stdin.write(data)

    upload = asyncio.create_task(client_to_server())
    try:
        await asyncio.gather(pump(remote.stdout, process.stdout, 1), pump(remote.stderr, process.stderr, 1))
        status = (await remote.wait()).exit_status
    except (asyncssh.Error, OSError):
        status = 255
    finally:
        upload.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await upload
    process.exit(status if isinstance(status, int) and status >= 0 else 0)


async def start(gw: Gateway, store: Store, core: Core, report: Report, port: int, host: str = "") -> asyncssh.SSHAcceptor:
    key = host_key(store)
    server = await asyncssh.create_server(
        lambda: BastionServer(gw, store, core, report), host, port, server_host_keys=[key], encoding=None,
        process_factory=handle, kbdint_auth=True, password_auth=False, public_key_auth=False,
        agent_forwarding=False, x11_forwarding=False, allow_scp=False, login_timeout=180,
        keepalive_interval=30, keepalive_count_max=4)
    log.info("bastion listening on port %s (host key %s)", port, key.get_fingerprint())
    return server


def fingerprint(store: Store) -> str:
    return host_key(store).get_fingerprint()
