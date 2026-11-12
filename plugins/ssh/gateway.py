"""NETsync SSH gateway: browser terminals on Linux servers with per-user accounts managed by NETsync.

How a session runs:

1. NETsync checks the user's terminal access on the device (none/read/write/full) and signs a one-minute ticket
   with the plugin secret (user, account ns-<user>, level, device address).
2. The browser opens ``/plugins/ssh/public/ws`` with the ticket as WebSocket subprotocol.
3. The gateway logs in as ``netsync`` with its own key (never leaves this container) and runs
   ``netsync-account ensure ns-alice <level>``: creates the account the first time, sets its groups (sudo rights).
4. A new account (or a user who forgot it) chooses a password for that server; otherwise the user types it.
5. The gateway logs in as ns-alice with that password and bridges the shell: binary frames are terminal bytes,
   text frames are JSON control messages.

Data in /data: the gateway key, trusted host keys and which accounts exist where (to remove them later).
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import json
import logging
import os
import re
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import asyncssh

log = logging.getLogger("netsync.ssh")

HERE = Path(__file__).resolve().parent
ACCOUNT = re.compile(r"^ns-[a-z0-9][a-z0-9_-]{0,28}$")
LEVELS = ("read", "write", "full")
TICKET_TTL = 90
MIN_PASSWORD = 10
CONNECT_TIMEOUT = 15


class GatewayError(Exception):
    """Something the user should read."""


# --------------------------------------------------------------------------- tickets

@dataclass
class Ticket:
    sid: str
    username: str
    account: str
    level: str
    device_id: int
    hostname: str
    host: str
    port: int
    exp: float


def b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def sign(payload: dict, secret: str) -> str:
    """Same format NETsync uses: base64url(json) "." base64url(hmac-sha256)."""
    body = b64(json.dumps(payload, separators=(",", ":")).encode())
    mac = hmac.new(secret.encode(), body.encode(), hashlib.sha256).digest()
    return f"{body}.{b64(mac)}"


_used: dict[str, float] = {}


def verify(token: str, secret: str, now: float | None = None) -> Ticket:
    now = now or time.time()
    try:
        body, mac = token.split(".", 1)
        want = hmac.new(secret.encode(), body.encode(), hashlib.sha256).digest()
        if not secret or not hmac.compare_digest(want, unb64(mac)):
            raise ValueError
        p = json.loads(unb64(body))
        t = Ticket(sid=str(p["sid"]), username=str(p["username"]), account=str(p["account"]), level=str(p["level"]),
                   device_id=int(p["device_id"]), hostname=str(p["hostname"]), host=str(p["host"]),
                   port=int(p.get("port", 22)), exp=float(p["exp"]))
    except (ValueError, KeyError, TypeError, json.JSONDecodeError) as e:
        raise GatewayError("invalid ticket") from e
    if t.exp < now:
        raise GatewayError("ticket expired, open the terminal again")
    if t.sid in _used:
        raise GatewayError("ticket already used")
    if not ACCOUNT.match(t.account) or t.level not in LEVELS:
        raise GatewayError("invalid ticket")
    for k in [k for k, v in _used.items() if v < now]:
        del _used[k]
    _used[t.sid] = t.exp + 60
    return t


# --------------------------------------------------------------------------- state

class Store:
    """Gateway key, trusted host keys and managed accounts (SQLite in /data)."""

    def __init__(self, path: Path | None = None):
        path = path or Path(os.environ.get("NETSYNC_DATA", "/data"))
        path.mkdir(parents=True, exist_ok=True)
        self.dir = path
        self.db = sqlite3.connect(path / "gateway.db", check_same_thread=False)
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS host_keys (target TEXT PRIMARY KEY, key TEXT NOT NULL, added REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS accounts (target TEXT NOT NULL, account TEXT NOT NULL, device_id INTEGER,
                hostname TEXT, level TEXT, created REAL, last_login REAL, PRIMARY KEY (target, account));
            CREATE TABLE IF NOT EXISTS removals (target TEXT NOT NULL, account TEXT NOT NULL, port INTEGER,
                tries INTEGER DEFAULT 0, last_error TEXT, PRIMARY KEY (target, account));
        """)
        self.db.commit()
        self.key = self._key()

    def _key(self) -> asyncssh.SSHKey:
        f = self.dir / "netsync_ed25519"
        if not f.exists():
            k = asyncssh.generate_private_key("ssh-ed25519", comment="netsync-gateway")
            f.write_bytes(k.export_private_key())
            f.chmod(0o600)
        return asyncssh.read_private_key(str(f))

    @property
    def public_key(self) -> str:
        return self.key.export_public_key().decode().strip()

    def host_key(self, target: str) -> str | None:
        row = self.db.execute("SELECT key FROM host_keys WHERE target=?", (target,)).fetchone()
        return row[0] if row else None

    def trust(self, target: str, key: str) -> None:
        self.db.execute("INSERT OR REPLACE INTO host_keys VALUES (?,?,?)", (target, key, time.time()))
        self.db.commit()

    def forget_host(self, target: str) -> bool:
        n = self.db.execute("DELETE FROM host_keys WHERE target=?", (target,)).rowcount
        self.db.commit()
        return n > 0

    def host_keys(self) -> list[dict]:
        return [{"target": t, "fingerprint": asyncssh.import_public_key(k).get_fingerprint(), "added": a}
                for t, k, a in self.db.execute("SELECT target, key, added FROM host_keys ORDER BY target")]

    def remember(self, target: str, t: Ticket, created: bool) -> None:
        now = time.time()
        self.db.execute("""INSERT INTO accounts VALUES (?,?,?,?,?,?,?) ON CONFLICT(target, account) DO UPDATE SET
                           level=excluded.level, hostname=excluded.hostname, last_login=excluded.last_login""",
                        (target, t.account, t.device_id, t.hostname, t.level, now, now))
        self.db.execute("DELETE FROM removals WHERE target=? AND account=?", (target, t.account))
        self.db.commit()

    def accounts(self, account: str | None = None) -> list[dict]:
        q = "SELECT target, account, device_id, hostname, level, created, last_login FROM accounts"
        rows = self.db.execute(q + (" WHERE account=?" if account else "") + " ORDER BY account, hostname",
                               (account,) if account else ())
        keys = ("target", "account", "device_id", "hostname", "level", "created", "last_login")
        return [dict(zip(keys, r, strict=True)) for r in rows]

    def queue_removal(self, account: str) -> int:
        rows = self.accounts(account)
        for r in rows:
            self.db.execute("INSERT OR IGNORE INTO removals (target, account) VALUES (?,?)", (r["target"], account))
        self.db.commit()
        return len(rows)

    def removals(self) -> list[tuple[str, str, int]]:
        return list(self.db.execute("SELECT target, account, tries FROM removals"))

    def removed(self, target: str, account: str) -> None:
        self.db.execute("DELETE FROM removals WHERE target=? AND account=?", (target, account))
        self.db.execute("DELETE FROM accounts WHERE target=? AND account=?", (target, account))
        self.db.commit()

    def removal_failed(self, target: str, account: str, error: str) -> None:
        self.db.execute("UPDATE removals SET tries=tries+1, last_error=? WHERE target=? AND account=?",
                        (error[:500], target, account))
        self.db.commit()

    def pending_removals(self) -> list[dict]:
        return [{"target": t, "account": a, "tries": n, "last_error": e}
                for t, a, n, e in self.db.execute("SELECT target, account, tries, last_error FROM removals")]


def target_of(host: str, port: int) -> str:
    return f"{host}:{port}"


def split_target(target: str) -> tuple[str, int]:
    host, _, port = target.rpartition(":")
    return host, int(port)


# --------------------------------------------------------------------------- ssh

class Gateway:
    def __init__(self, store: Store):
        self.store = store

    def _known_hosts(self, target: str):
        key = self.store.host_key(target)
        return ([asyncssh.import_public_key(key)], [], []) if key else None

    async def _connect(self, host: str, port: int, **kw) -> asyncssh.SSHClientConnection:
        target = target_of(host, port)
        known = self._known_hosts(target)
        try:
            conn = await asyncio.wait_for(asyncssh.connect(
                host, port, known_hosts=known, agent_path=None, keepalive_interval=30, keepalive_count_max=4,
                connect_timeout=CONNECT_TIMEOUT, **kw), CONNECT_TIMEOUT + 5)
        except asyncssh.HostKeyNotVerifiable as e:
            raise GatewayError(f"The host key of {host} changed since NETsync first connected. If the server was "
                               f"reinstalled, an admin can reset its key in Setup → Terminal.") from e
        except asyncssh.PermissionDenied:
            raise
        except (OSError, asyncio.TimeoutError, asyncssh.Error) as e:
            raise GatewayError(f"Cannot connect to {host}:{port}: {e}") from e
        if known is None:  # first contact: trust on first use
            self.store.trust(target, conn.get_server_host_key().export_public_key().decode().strip())
        return conn

    async def manage(self, host: str, port: int, *args: str, stdin: str | None = None) -> dict:
        """Run netsync-account on the server through the netsync account."""
        try:
            conn = await self._connect(host, port, username="netsync", client_keys=[self.store.key], password=None,
                                       preferred_auth="publickey")
        except asyncssh.PermissionDenied as e:
            raise GatewayError(f"{host} is not set up for NETsync terminals yet. An admin has to run the setup "
                               f"command on it once (Setup → Terminal).") from e
        async with conn:
            r = await conn.run(" ".join(("netsync-account", *args)), input=stdin, check=False, timeout=60)
        text = (r.stdout or "").strip().splitlines()
        try:
            out = json.loads(text[-1]) if text else {}
        except json.JSONDecodeError:
            out = {}
        if not out.get("ok"):
            err = out.get("error") or (r.stderr or "").strip()[:300] or f"exit {r.exit_status}"
            if "sudo" in err.lower() or "password is required" in err.lower():
                err = f"sudo refused the netsync account ({err}). Run the setup command on {host} again."
            raise GatewayError(f"{host}: {err}")
        return out

    async def login(self, host: str, port: int, account: str, password: str) -> asyncssh.SSHClientConnection:
        return await self._connect(host, port, username=account, password=password, client_keys=[],
                                   preferred_auth="password,keyboard-interactive", kbdint_auth=True)

    async def remove(self, target: str, account: str) -> None:
        host, port = split_target(target)
        await self.manage(host, port, "remove", account)
        self.store.removed(target, account)

    async def run_removals(self) -> int:
        done = 0
        for target, account, _tries in self.store.removals():
            try:
                await self.remove(target, account)
                done += 1
                log.info("removed %s from %s", account, target)
            except GatewayError as e:
                self.store.removal_failed(target, account, str(e))
                log.warning("could not remove %s from %s: %s", account, target, e)
        return done


def valid_password(pw: str) -> str | None:
    if len(pw) < MIN_PASSWORD:
        return f"At least {MIN_PASSWORD} characters."
    if len(pw) > 128 or any(c in pw for c in "\r\n\0"):
        return "Too long or contains line breaks."
    return None


# --------------------------------------------------------------------------- setup script

SOURCE = re.compile(r"^[0-9A-Fa-f:.]{3,45}(/\d{1,3})?$")


def setup_script(public_key: str, source: str) -> str:
    if not SOURCE.match(source):
        raise GatewayError("source must be the IP address (or CIDR) NETsync connects from")
    if not re.match(r"^ssh-ed25519 [A-Za-z0-9+/=]+( [\w@.-]+)?$", public_key):
        raise GatewayError("unexpected gateway key format")
    account = (HERE / "netsync-account").read_text()
    return ((HERE / "setup.sh").read_text().replace("__SOURCE__", source).replace("__PUBKEY__", public_key)
            .replace("__ACCOUNT_SCRIPT__", account.rstrip("\n")))


def strip_none(d: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in d.items() if v is not None}
