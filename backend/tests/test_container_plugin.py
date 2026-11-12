"""The example container plugin (plugins/sdk + plugins/examples/hello) against NETsync's plugin client."""

import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from netsync.tools import remote
from netsync.tools.base import Actor, ToolContext, ToolError

PLUGINS = Path(__file__).resolve().parents[2] / "plugins"
SECRET = "nsp_plg_test-secret"


@pytest.fixture
def hello(monkeypatch):
    monkeypatch.setenv("NETSYNC_PLUGIN_SECRET", SECRET)
    sys.path.insert(0, str(PLUGINS / "sdk"))
    try:
        spec = importlib.util.spec_from_file_location("hello_app", PLUGINS / "examples" / "hello" / "app.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
    finally:
        sys.path.remove(str(PLUGINS / "sdk"))
    transport = httpx.ASGITransport(app=mod.app)
    real = httpx.AsyncClient

    def client(*a, **kw):
        kw["transport"] = transport
        return real(*a, **kw)

    monkeypatch.setattr(remote.httpx, "AsyncClient", client)
    monkeypatch.setattr(remote, "secret_of", lambda p: p._secret)
    return mod


def plugin_row(secret=SECRET, granted=("tools",)):
    return SimpleNamespace(name="hello", url="http://hello", _secret=secret, enabled=True, status="pending",
                           manifest={}, granted=list(granted), status_detail=None, last_seen=None)


async def test_manifest_refresh_and_tool_call(hello, monkeypatch):
    p = plugin_row()
    await remote.refresh(p)
    assert p.status == "online", p.status_detail
    assert {t["name"]: t["risk"] for t in p.manifest["tools"]} == {"greet": "read", "problem_count": "read",
                                                                   "write_note": "write"}
    assert p.manifest["permissions"] == ["tools", "call:read"]
    tools = {t.name: t for t in remote.tools_of(p)}
    assert set(tools) == {"hello__greet", "hello__problem_count", "hello__write_note"}

    async def row(*_a, **_k):
        return p

    class FakeSession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        scalar = staticmethod(row)

    monkeypatch.setattr(remote, "SessionLocal", FakeSession)
    ctx = ToolContext(Actor("user", "alice"), call_id=5, origin="chat")
    out = await remote.call(tools["hello__greet"], ctx, {"name": "Elison"})
    assert out == {"text": "Hello Elison!", "asked_by": "user:alice"}
    assert (await remote.call(tools["hello__write_note"], ctx, {"note": "x"}))["approved_call"] == 5


async def test_wrong_secret_is_reported(hello):
    p = plugin_row(secret="nsp_plg_wrong")
    await remote.refresh(p)
    assert p.status == "error" and "secret" in p.status_detail


async def test_plugin_errors_become_tool_errors(hello, monkeypatch):
    p = plugin_row()
    await remote.refresh(p)

    class FakeSession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def scalar(self, *a, **k):
            return p

    monkeypatch.setattr(remote, "SessionLocal", FakeSession)
    tool = next(t for t in remote.tools_of(p) if t.name == "hello__problem_count")
    # NETsync isn't reachable from this test: the plugin's own call fails and comes back as a tool error
    with pytest.raises(ToolError):
        await remote.call(tool, ToolContext(Actor("user", "a")), {})
