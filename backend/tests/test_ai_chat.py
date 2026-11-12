"""AI coworker chat: think filter, history, tool loop (Ollama and the database are faked)."""

import asyncio
import itertools

import pytest

from netsync.models import ChatMessage
from netsync.plugins.builtin.ai import chat, ollama
from netsync.tools.base import Actor


def test_think_filter_drops_reasoning_across_chunks():
    f = ollama.ThinkFilter()
    out = "".join(f.feed(p) for p in ["Hel", "lo <thi", "nk>secret ", "stuff</th", "ink> world", " <"]) + f.flush()
    assert out == "Hello world <"
    f = ollama.ThinkFilter()
    assert f.feed("<think>never closed") + f.flush() == ""


def test_history_keeps_last_turns_and_shrinks_old_tool_results():
    rows = []
    for i in range(6):
        rows.append(ChatMessage(role="user", content=f"q{i}"))
        rows.append(ChatMessage(role="tool", tool="netsync__list_problems", arguments={"limit": 1},
                                result={"status": "done", "result": {"x": "y" * 5000}}))
        rows.append(ChatMessage(role="assistant", content=f"a{i}"))
    msgs = chat.history_messages(rows)
    users = [m["content"] for m in msgs if m["role"] == "user"]
    assert users == ["q2", "q3", "q4", "q5"]
    tool = next(m for m in msgs if m["role"] == "tool")
    assert len(tool["content"]) <= chat.OLD_TOOL_CHARS + 10 and tool["tool_name"] == "netsync__list_problems"
    assert chat.for_model({"status": "pending", "call_id": 3, "message": "m"})["status"] == "waiting for approval"
    assert chat.for_model({"status": "error", "error": "nope"}) == {"error": "nope"}


def test_parse_args_and_title():
    assert chat.parse_args('{"device": "a"}') == {"device": "a"}
    assert chat.parse_args("not json") == {} and chat.parse_args(None) == {}
    assert chat.title_of("  how   many\nalerts ") == "how many alerts"
    assert len(chat.title_of("x" * 200)) == 78


def test_system_prompt_has_rules_page_and_site_context():
    from datetime import UTC, datetime

    p = chat.system_prompt({"language": "Portuguese", "extra_instructions": "Proxmox cluster"},
                           datetime(2026, 11, 12, 10, 0, tzinfo=UTC))
    assert "call a tool first" in p and "Portuguese" in p and "Proxmox cluster" in p and "2026-11-12" in p
    assert "10:00" not in p  # the time goes with the question, the prompt stays cacheable


def test_chat_tool_specs_are_short():
    import json

    from netsync.tools.builtin import TOOLS

    specs = [chat.tool_spec(t) for t in TOOLS]
    assert len(json.dumps(specs)) < 3500  # was ~4700 with the full wording
    ms = next(s["function"] for s in specs if s["function"]["name"] == "netsync__metric_summary")
    assert ms["parameters"]["required"] == ["device", "graph"] and "mem_usage" in ms["parameters"]["properties"]["graph"]["description"]
    assert "maximum" not in json.dumps(specs) and "default" not in json.dumps(specs)


class FakeSession:
    ids = itertools.count(100)
    stored: list = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def scalars(self, _q):
        return [ChatMessage(role="user", content="How often did Ping fail on pve002?")]

    async def get(self, *_a):
        return None

    def add(self, obj):
        obj.id = next(self.ids)
        self.stored.append(obj)

    async def commit(self):
        pass


@pytest.fixture
def fake(monkeypatch):
    FakeSession.stored = []
    monkeypatch.setattr(chat, "SessionLocal", FakeSession)

    async def no_note(*_a):
        return None, None

    monkeypatch.setattr(chat, "page_note", no_note)

    class T:
        def __init__(self, name):
            self.name, self.description, self.input_schema = name, "d", {"type": "object", "properties": {}}

    async def visible(_actor):
        return [T("netsync__alert_history"), T("netsync__call_result")]

    calls = []

    async def call(name, args, actor, origin, reason=None):
        calls.append((name, args, origin))
        return {"status": "done", "call_id": 7, "result": {"times": 3, "total_minutes": 192}, "error": None}

    monkeypatch.setattr(chat.hub, "visible_tools", visible)
    monkeypatch.setattr(chat.hub, "call", call)
    return calls


def run_turn(monkeypatch, replies):
    seen = []

    async def stream(cfg, messages, tools=None, model=None):
        seen.append((list(messages), tools))
        for chunk in replies[len(seen) - 1]:
            yield chunk

    monkeypatch.setattr(chat.ollama, "chat_stream", stream)
    turn = chat.Turn({"model": "qwen3.5:0.8b"}, Actor("user", "alice"), 1, "How often did Ping fail?", None)

    async def go():
        await turn.run()
        out = []
        while (ev := turn.queue.get_nowait()) is not None:
            out.append(ev)
        return out

    return asyncio.run(go()), seen


def test_turn_calls_tool_then_streams_answer(monkeypatch, fake):
    call = {"function": {"name": "netsync__alert_history", "arguments": {"device": "pve002", "service": "Ping"}}}
    events, seen = run_turn(monkeypatch, [
        [{"message": {"content": "", "tool_calls": [call]}, "done": True}],
        [{"message": {"content": "Ping failed 3 times, "}}, {"message": {"content": "192 minutes in total."}, "done": True}],
    ])
    assert fake == [("netsync__alert_history", {"device": "pve002", "service": "Ping"}, "chat")]
    kinds = [e["type"] for e in events]
    assert kinds == ["tool", "tool_result", "delta", "delta", "done"]
    # the tool list given to the model leaves out call_result; the tool answer goes back as a tool message
    assert [t["function"]["name"] for t in seen[0][1]] == ["netsync__alert_history"]
    assert seen[1][0][-1]["role"] == "tool" and '"times":3' in seen[1][0][-1]["content"]
    assert seen[0][0][1]["content"].startswith("[") and "How often" in seen[0][0][1]["content"]
    answer = [m for m in FakeSession.stored if m.role == "assistant"][0]
    assert answer.content == "Ping failed 3 times, 192 minutes in total." and answer.model == "qwen3.5:0.8b"
    assert [m.role for m in FakeSession.stored] == ["tool", "assistant"]


def test_turn_stops_repeated_calls_and_unknown_tools(monkeypatch, fake):
    same = {"function": {"name": "netsync__alert_history", "arguments": '{"device": "a"}'}}
    bogus = {"function": {"name": "ssh__run", "arguments": {}}}
    events, seen = run_turn(monkeypatch, [
        [{"message": {"tool_calls": [same]}}],
        [{"message": {"tool_calls": [same, bogus]}}],
        [{"message": {"content": "done"}}],
    ])
    assert len(fake) == 1  # the repeat and the unknown tool never reach the hub
    errors = [e["result"]["error"] for e in events if e["type"] == "tool_result" and e["result"]["error"]]
    assert any("unknown tool" in e for e in errors)
    assert any("already called" in m["content"] for m in seen[2][0] if m["role"] == "tool")


def test_guard_device_replaces_or_drops_invented_hostnames():
    s_opt = {"properties": {"device": {}, "limit": {}}}
    s_req = {"properties": {"device": {}}, "required": ["device"]}
    said = "how often did ping fail on pve002 last week?"
    assert chat.guard_device({"device": "pve002.qsync.net"}, s_opt, said, None)["device"] == "pve002.qsync.net"
    assert chat.guard_device({"device": "homepage", "limit": 5}, s_opt, said, None) == {"limit": 5}
    assert chat.guard_device({"device": "homepage"}, s_req, said, "rou002.qsync.net") == {"device": "rou002.qsync.net"}
    assert chat.guard_device({"device": "homepage"}, s_req, said, None) == {"device": "homepage"}  # the tool reports it
    assert chat.guard_device({"device": "12"}, s_req, said, None) == {"device": "12"}
    assert chat.guard_device({"text": "x"}, {"properties": {"text": {}}}, said, None) == {"text": "x"}


def test_events_ping_while_the_model_is_quiet():
    async def go():
        turn = chat.Turn({"model": "m"}, Actor("user", "a"), 1, "q", None)
        it = chat.events(turn, keepalive=0.01)
        first = await it.__anext__()
        turn.emit({"type": "delta", "text": "x"})
        turn.queue.put_nowait(None)
        return first, [e async for e in it]

    first, rest = asyncio.run(go())
    assert first == {"type": "ping"} and rest[-1] == {"type": "delta", "text": "x"}


def test_last_round_offers_no_tools_and_errors_are_reported(monkeypatch, fake):
    loop = {"function": {"name": "netsync__alert_history", "arguments": {}}}
    replies = [[{"message": {"tool_calls": [{"function": {**loop["function"], "arguments": {"days": i}}}]}}]
               for i in range(chat.MAX_ROUNDS - 1)] + [[{"message": {"content": "ok"}}]]
    _, seen = run_turn(monkeypatch, replies)
    assert seen[-1][1] is None and all(s[1] for s in seen[:-1])

    async def broken(*_a, **_k):
        raise ollama.OllamaError("Cannot reach Ollama")
        yield  # pragma: no cover

    monkeypatch.setattr(chat.ollama, "chat_stream", broken)
    turn = chat.Turn({"model": "m"}, Actor("user", "alice"), 1, "q", None)
    asyncio.run(turn.run())
    evs = [turn.queue.get_nowait() for _ in range(3)]
    assert evs[0] == {"type": "error", "error": "Cannot reach Ollama"} and evs[1]["type"] == "done" and evs[2] is None
    assert FakeSession.stored[-1].content.startswith("⚠ Cannot reach Ollama")
