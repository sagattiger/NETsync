"""SSH gateway: tickets, setup script, and a full browser session against a local test SSH server.

Run: pytest plugins/ssh/test_gateway.py (needs fastapi, httpx, asyncssh).
"""

import asyncio
import json
import os
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE), str(HERE.parent / "sdk")]
SECRET = "nsp_plg_test-secret"
os.environ["NETSYNC_PLUGIN_SECRET"] = SECRET


@pytest.fixture(autouse=True)
def data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("NETSYNC_DATA", str(tmp_path))
    return tmp_path


import asyncssh  # noqa: E402
import gateway  # noqa: E402


def ticket(**kw):
    p = {"sid": "s1", "username": "alice", "account": "ns-alice", "level": "read", "device_id": 1,
         "hostname": "srv1", "host": "127.0.0.1", "port": 22, "exp": time.time() + 60, **kw}
    return gateway.sign(p, SECRET)


def test_tickets_are_signed_single_use_and_expire():
    gateway._used.clear()
    t = gateway.verify(ticket(), SECRET)
    assert t.account == "ns-alice" and t.level == "read"
    with pytest.raises(gateway.GatewayError, match="already used"):
        gateway.verify(ticket(), SECRET)
    with pytest.raises(gateway.GatewayError, match="invalid"):
        gateway.verify(ticket(sid="s2"), "other-secret")
    with pytest.raises(gateway.GatewayError, match="expired"):
        gateway.verify(ticket(sid="s3", exp=time.time() - 1), SECRET)
    for bad in ({"account": "root"}, {"account": "ns-x; rm"}, {"level": "admin"}):
        with pytest.raises(gateway.GatewayError, match="invalid"):
            gateway.verify(ticket(sid="s-" + json.dumps(bad), **bad), SECRET)


def test_core_and_gateway_sign_the_same_way():
    backend = HERE.parent.parent / "backend"
    sys.path.insert(0, str(backend))
    try:
        from netsync.terminal import sign as core_sign
    except Exception:  # noqa: BLE001 - backend not importable here
        pytest.skip("backend not importable")
    gateway._used.clear()
    payload = {"sid": "x9", "username": "bob", "account": "ns-bob", "level": "full", "device_id": 3, "hostname": "h",
               "host": "10.0.0.1", "port": 22, "exp": int(time.time()) + 60}
    assert gateway.verify(core_sign(payload, SECRET), SECRET).username == "bob"


def test_passwords():
    assert gateway.valid_password("short")
    assert gateway.valid_password("a" * 10) is None
    assert gateway.valid_password("line\nbreak-long")


def test_setup_script_is_valid_bash_and_has_no_placeholders(data_dir):
    store = gateway.Store(data_dir)
    script = gateway.setup_script(store.public_key, "10.128.101.112")
    assert "__" not in script.replace("__name__", "")
    assert 'from="%s"' in script and "10.128.101.112" in script and store.public_key in script
    with pytest.raises(gateway.GatewayError):
        gateway.setup_script(store.public_key, "1.2.3.4; rm -rf /")
    bash = shutil.which("bash")
    if bash:
        for text in (script, (HERE / "netsync-account").read_text()):
            r = subprocess.run([bash, "-n"], input=text.encode(), capture_output=True)
            assert r.returncode == 0, r.stderr


def test_store_accounts_and_removals(data_dir):
    s = gateway.Store(data_dir)
    t = gateway.verify(ticket(sid="st1"), SECRET)
    s.remember("srv1:22", t, True)
    s.remember("srv2:22", t, True)
    assert {a["target"] for a in s.accounts("ns-alice")} == {"srv1:22", "srv2:22"}
    assert s.queue_removal("ns-alice") == 2
    s.removed("srv1:22", "ns-alice")
    s.removal_failed("srv2:22", "ns-alice", "offline")
    assert [(r["target"], r["tries"]) for r in s.pending_removals()] == [("srv2:22", 1)]
    s.remember("srv2:22", t, False)  # logging in again cancels a pending removal
    assert s.pending_removals() == []
    # the key survives a restart
    assert gateway.Store(data_dir).public_key == s.public_key


# --------------------------------------------------------------------------- full session against a fake server

class FakeServer(asyncssh.SSHServer):
    """netsync (key) runs netsync-account; ns-* accounts log in with their password and get an echo shell."""

    accounts: dict = {}
    gateway_key: asyncssh.SSHKey | None = None
    commands: list = []

    def begin_auth(self, username):
        return True

    def public_key_auth_supported(self):
        return True

    def validate_public_key(self, username, key):
        return username == "netsync" and key.public_data == self.gateway_key.public_data

    def password_auth_supported(self):
        return True

    def validate_password(self, username, password):
        return self.accounts.get(username, {}).get("password") == password


async def handle(process: asyncssh.SSHServerProcess):
    user = process.get_extra_info("username")
    if user == "netsync":
        args = (process.command or "").split()
        FakeServer.commands.append(args)
        acc = FakeServer.accounts
        if args[1] == "ensure":
            created = args[2] not in acc
            acc.setdefault(args[2], {"password": None})["level"] = args[3]
            out = {"ok": True, "created": created, "has_password": bool(acc[args[2]]["password"])}
        elif args[1] == "passwd":
            acc[args[2]]["password"] = (await process.stdin.readline()).rstrip("\n")
            out = {"ok": True}
        elif args[1] == "remove":
            acc.pop(args[2], None)
            out = {"ok": True}
        else:
            out = {"ok": True, "version": 1}
        process.stdout.write(json.dumps(out) + "\n")
        process.exit(0)
        return
    process.stdout.write(f"welcome {user}\r\n")
    while True:
        line = await process.stdin.readline()
        if not line or line.strip() == "exit":
            break
        process.stdout.write(f"echo:{line.strip()}\r\n")
    process.exit(0)


@pytest.fixture
def ssh_server(data_dir):
    loop = asyncio.new_event_loop()
    host_key = asyncssh.generate_private_key("ssh-ed25519")
    started = threading.Event()
    box = {}

    async def run():
        box["server"] = await asyncssh.create_server(FakeServer, "127.0.0.1", 0, server_host_keys=[host_key],
                                                     process_factory=handle)
        box["port"] = box["server"].sockets[0].getsockname()[1]
        started.set()

    threading.Thread(target=lambda: (loop.run_until_complete(run()), loop.run_forever()), daemon=True).start()
    started.wait(10)
    FakeServer.accounts, FakeServer.commands = {}, []
    yield box["port"]
    loop.call_soon_threadsafe(loop.stop)


def test_browser_session_creates_account_sets_password_and_bridges(ssh_server, data_dir, monkeypatch):
    import importlib

    from fastapi.testclient import TestClient

    app_mod = importlib.import_module("app")
    importlib.reload(app_mod)
    FakeServer.gateway_key = app_mod.store.key
    reports = []

    async def fake_report(sid, **fields):
        reports.append(fields)

    monkeypatch.setattr(app_mod, "report", fake_report)
    app_mod.app.router.on_startup.clear()  # no background loops in the test
    client = TestClient(app_mod.app)
    gateway._used.clear()

    def connect(sid, password_flow):
        tk = ticket(sid=sid, port=ssh_server, level="write")
        with client.websocket_connect("/public/ws", subprotocols=[f"ticket.{tk}"]) as ws:
            ws.send_text(json.dumps({"t": "resize", "cols": 100, "rows": 30}))
            seen = []
            while True:
                msg = json.loads(ws.receive_text())
                seen.append(msg["t"])
                if password_flow.get(msg["t"]):
                    ws.send_text(json.dumps(password_flow[msg["t"]].pop(0)))
                if msg["t"] == "connected":
                    break
                assert msg["t"] not in ("error", "closed"), msg
            out = ws.receive_bytes()
            assert b"welcome ns-alice" in out
            ws.send_text(json.dumps({"t": "input", "d": "hello\n"}))
            assert b"echo:hello" in ws.receive_bytes()
            ws.send_text(json.dumps({"t": "input", "d": "exit\n"}))
            while True:
                m = ws.receive()
                if m.get("text") and json.loads(m["text"]).get("t") == "closed":
                    break
        return seen

    # first time: the account is created, a too-short password is refused, then a good one is set
    seen = connect("w1", {"set_password": [{"t": "new_password", "v": "short"}, {"t": "new_password", "v": "a-long-password"}],
                          "password_error": []})
    assert seen[:2] == ["status", "set_password"] and "password_error" in seen
    assert FakeServer.accounts["ns-alice"] == {"password": "a-long-password", "level": "write"}
    assert FakeServer.commands[0] == ["netsync-account", "ensure", "ns-alice", "write"]
    # next time: asked for the password; a wrong one is retried
    seen = connect("w2", {"ask_password": [{"t": "password", "v": "wrong-password"}, {"t": "password", "v": "a-long-password"}]})
    assert seen.count("ask_password") == 2
    assert [r["status"] for r in reports] == ["connected", "ended", "connected", "ended"]
    assert reports[1]["bytes_in"] > 0 and reports[1]["bytes_out"] > 0
    # the host key was trusted on first use and the account is remembered for later removal
    assert app_mod.store.host_key(f"127.0.0.1:{ssh_server}")
    assert app_mod.store.accounts("ns-alice")[0]["level"] == "write"


def test_bad_ticket_is_refused(data_dir):
    import importlib

    from fastapi.testclient import TestClient
    from starlette.websockets import WebSocketDisconnect

    app_mod = importlib.import_module("app")
    app_mod.app.router.on_startup.clear()
    client = TestClient(app_mod.app)
    with pytest.raises(WebSocketDisconnect), client.websocket_connect("/public/ws", subprotocols=["ticket.nope"]) as ws:
        ws.receive_text()


def test_removal_runs_against_the_server(ssh_server, data_dir):
    store = gateway.Store(data_dir)
    FakeServer.gateway_key = store.key
    gw = gateway.Gateway(store)
    FakeServer.accounts["ns-bob"] = {"password": "x", "level": "read"}
    t = gateway.verify(ticket(sid="rm1", account="ns-bob", port=ssh_server), SECRET)
    store.remember(f"127.0.0.1:{ssh_server}", t, True)
    store.queue_removal("ns-bob")
    assert asyncio.run(gw.run_removals()) == 1
    assert "ns-bob" not in FakeServer.accounts and store.accounts("ns-bob") == []
