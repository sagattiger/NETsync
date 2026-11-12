"""Tool hub: tool definitions, argument checks, redaction, MCP JSON-RPC, container-plugin manifests, alert episodes."""

from datetime import UTC, datetime, timedelta

import pytest

from netsync.models import State
from netsync.tools import api as tool_api
from netsync.tools import remote
from netsync.tools.base import Actor, Tool, ToolError, redact, schema, validate_args
from netsync.tools.builtin import TOOLS, episodes

NOW = datetime(2026, 11, 12, 12, 0, tzinfo=UTC)


# --------------------------------------------------------------------------- definitions and arguments

def test_tool_names_are_mcp_and_claude_safe():
    for t in TOOLS:
        assert t.name.startswith("netsync__") and t.risk == "read"
        d = t.describe()
        assert d["inputSchema"]["type"] == "object" and d["annotations"]["readOnlyHint"] is True
    with pytest.raises(ValueError):
        Tool("NetSync.find", "x", schema({}))
    with pytest.raises(ValueError):
        Tool("netsync_find", "x", schema({}))


def test_validate_args_types_defaults_and_limits():
    s = schema({"device": {"type": "string", "maxLength": 5}, "days": {"type": "integer", "minimum": 1, "maximum": 30,
                                                                         "default": 7},
                "level": {"type": "string", "enum": ["a", "b"]}}, ["device"])
    assert validate_args(s, {"device": "x"}) == {"device": "x", "days": 7}
    assert validate_args(s, {"device": "x", "days": "3"})["days"] == 3
    assert validate_args(s, {"device": "x", "days": 3.0})["days"] == 3
    for bad, msg in [({}, "missing"), ({"device": "toolong"}, "longer"), ({"device": "x", "days": 0}, "at least"),
                     ({"device": "x", "days": True}, "integer"), ({"device": "x", "level": "c"}, "one of"),
                     ({"device": "x", "other": 1}, "unknown")]:
        with pytest.raises(ToolError, match=msg):
            validate_args(s, bad)
    with pytest.raises(ToolError):
        validate_args(s, ["not", "an", "object"])


def test_redact_hides_secret_looking_keys():
    assert redact({"host": "a", "password": "p", "nested": {"api_key": "k", "x": [{"token": "t"}]}}) == \
        {"host": "a", "password": "********", "nested": {"api_key": "********", "x": [{"token": "********"}]}}


def test_actor_patterns():
    a = Actor("token", "claude", tools=["netsync__*", "ssh__run_readonly"])
    assert a.may_use("netsync__find_devices") and a.may_use("ssh__run_readonly")
    assert not a.may_use("ssh__run_command") and not a.write
    assert Actor("token", "x").may_use("anything__goes")


# --------------------------------------------------------------------------- alert episodes

def test_episodes_count_and_minutes():
    t = lambda h: NOW - timedelta(hours=h)  # noqa: E731
    changes = [
        (t(50), State.OK, State.WARN), (t(49), State.WARN, State.CRIT), (t(48), State.CRIT, State.OK),  # 2 h
        (t(10), State.OK, State.CRIT), (t(9.5), State.CRIT, State.OK),  # 30 min
        (t(1), State.OK, State.WARN),  # still open: 60 min
    ]
    eps = episodes(changes, NOW - timedelta(days=7), NOW)
    assert [e["minutes"] for e in eps] == [120, 30, 60]
    assert [e["worst"] for e in eps] == ["CRIT", "CRIT", "WARN"]
    assert eps[-1]["end"] is None
    # a problem that started before the window counts only its minutes inside the window
    eps = episodes(changes, NOW - timedelta(hours=48.5), NOW)
    assert [e["minutes"] for e in eps] == [30, 30, 60]


# --------------------------------------------------------------------------- container plugin manifests

def test_parse_manifest():
    m = remote.parse_manifest("ssh", {
        "name": "ssh", "version": "1.0", "permissions": ["tools", "events", "root:everything"],
        "tools": [{"name": "run_readonly", "description": "Run a safe command", "risk": "read",
                   "input_schema": {"type": "object", "properties": {"cmd": {"type": "string"}}}},
                  {"name": "restart_service", "risk": "write", "inputSchema": {"type": "object", "properties": {}}}],
    })
    assert m["permissions"] == ["tools", "events"]  # unknown permissions are dropped
    assert [(t["name"], t["risk"]) for t in m["tools"]] == [("run_readonly", "read"), ("restart_service", "write")]
    for bad in ({"name": "other"}, {"name": "ssh", "tools": [{"name": "Bad-Name"}]},
                {"name": "ssh", "tools": [{"name": "x", "input_schema": {"type": "string"}}]}, "nope"):
        with pytest.raises(ValueError):
            remote.parse_manifest("ssh", bad)


def test_remote_tools_only_when_online_and_granted():
    from types import SimpleNamespace

    manifest = {"tools": [{"name": "run", "description": "d", "input_schema": {"type": "object"}, "risk": "write"}]}
    p = SimpleNamespace(name="ssh", enabled=True, status="online", granted=["tools"], manifest=manifest)
    [t] = remote.tools_of(p)
    assert t.name == "ssh__run" and t.risk == "write" and t.plugin == "ssh" and t.handler is None
    assert remote.tools_of(SimpleNamespace(**{**p.__dict__, "granted": []})) == []
    assert remote.tools_of(SimpleNamespace(**{**p.__dict__, "status": "offline"})) == []


def test_valid_url():
    assert remote.valid_url("http://netsync-ssh:8080/") == "http://netsync-ssh:8080"
    for bad in ("ftp://x", "http://user:pw@host", "netsync-ssh:8080"):
        with pytest.raises(ValueError):
            remote.valid_url(bad)


# --------------------------------------------------------------------------- MCP JSON-RPC

@pytest.fixture
def fake_hub(monkeypatch):
    calls = []

    async def visible(actor):
        return [t for t in TOOLS if actor.may_use(t.name)]

    async def call(name, args, actor, origin, reason=None):
        calls.append((name, args, origin))
        if name == "netsync__boom":
            raise ToolError("unknown tool: netsync__boom")
        if name == "netsync__write_thing":
            return {"status": "pending", "call_id": 7, "message": "Waiting for approval"}
        return {"status": "done", "call_id": 1, "result": {"count": 2}, "error": None}

    monkeypatch.setattr(tool_api.hub, "visible_tools", visible)
    monkeypatch.setattr(tool_api.hub, "call", call)
    return calls


async def test_mcp_initialize_list_and_call(fake_hub):
    actor = Actor("token", "t", tools=["netsync__*"])
    init = await tool_api.handle_rpc({"jsonrpc": "2.0", "id": 1, "method": "initialize",
                                      "params": {"protocolVersion": "2025-03-26"}}, actor)
    assert init["result"]["protocolVersion"] == "2025-03-26" and "tools" in init["result"]["capabilities"]
    assert init["result"]["serverInfo"]["name"] == "netsync"
    assert await tool_api.handle_rpc({"jsonrpc": "2.0", "method": "notifications/initialized"}, actor) is None
    listed = await tool_api.handle_rpc({"jsonrpc": "2.0", "id": 2, "method": "tools/list"}, actor)
    assert {t["name"] for t in listed["result"]["tools"]} == {t.name for t in TOOLS}
    done = await tool_api.handle_rpc({"jsonrpc": "2.0", "id": 3, "method": "tools/call",
                                      "params": {"name": "netsync__find_devices", "arguments": {"query": "pve"}}}, actor)
    assert done["result"]["isError"] is False and done["result"]["structuredContent"] == {"count": 2}
    assert fake_hub[-1] == ("netsync__find_devices", {"query": "pve"}, "mcp")


async def test_mcp_errors_and_approvals(fake_hub):
    actor = Actor("token", "t")
    err = await tool_api.handle_rpc({"jsonrpc": "2.0", "id": 4, "method": "tools/call", "params": {"name": "netsync__boom"}}, actor)
    assert err["result"]["isError"] is True and "unknown tool" in err["result"]["content"][0]["text"]
    pending = await tool_api.handle_rpc({"jsonrpc": "2.0", "id": 5, "method": "tools/call",
                                         "params": {"name": "netsync__write_thing"}}, actor)
    assert pending["result"]["structuredContent"]["status"] == "pending_approval"
    assert (await tool_api.handle_rpc({"jsonrpc": "2.0", "id": 6, "method": "nope"}, actor))["error"]["code"] == -32601
    assert (await tool_api.handle_rpc({"id": 7, "method": "ping"}, actor))["error"]["code"] == -32600
    old = await tool_api.handle_rpc({"jsonrpc": "2.0", "id": 8, "method": "initialize",
                                     "params": {"protocolVersion": "1999-01-01"}}, actor)
    assert old["result"]["protocolVersion"] == tool_api.PROTOCOL_VERSIONS[0]


def test_token_actor_scopes():
    from types import SimpleNamespace

    a = tool_api.token_actor(SimpleNamespace(name="claude", scopes={"tools": ["netsync__*"], "write": False}))
    assert a.kind == "token" and a.tools == ["netsync__*"] and a.write is False
    assert tool_api.token_actor(SimpleNamespace(name="n8n", scopes={})).tools == ["netsync__*"]
