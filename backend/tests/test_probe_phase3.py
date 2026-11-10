"""json assertions and push heartbeats."""

from datetime import UTC, datetime, timedelta

import httpx
import pytest
from pydantic import ValidationError

from netsync.api.probes import ProbeIn
from netsync.probing.base import ProbeSpec, get_checker
from netsync.probing.checkers.json_api import MISSING, JsonChecker, evaluate, parse_path, resolve
from netsync.probing.checkers.push import hash_push_token, new_push_token, overdue

DOC = {"data": {"items": [{"status": "ok", "n": 3}, {"status": "degraded"}], "count": 2, "flag": True,
                "tags": ["a", "b"], "x.y": "dotted", "none": None}, "version": "1.2.3"}


def test_parse_and_resolve_paths():
    assert parse_path("data.items[0].status") == ["data", "items", 0, "status"]
    assert parse_path("$.data.count") == ["data", "count"]
    assert parse_path('data["x.y"]') == ["data", "x.y"]
    assert resolve(DOC, parse_path("data.items[1].status")) == "degraded"
    assert resolve(DOC, parse_path('data["x.y"]')) == "dotted"
    assert resolve(DOC, parse_path("data.items[5]")) is MISSING
    assert resolve(DOC, parse_path("data.none")) is None
    for bad in ("data..x", "data[x]", "data.[0]", "a b"):
        with pytest.raises(ValueError):
            parse_path(bad)


@pytest.mark.parametrize("path,op,value,ok", [
    ("data.items[0].status", "==", "ok", True),
    ("data.items[0].status", "==", '"ok"', True),
    ("data.items[0].status", "!=", "ok", False),
    ("data.count", "==", "2", True),
    ("data.count", ">=", "2", True),
    ("data.count", "<", "2", False),
    ("data.items[0].n", ">", "2.5", True),
    ("data.flag", "==", "true", True),
    ("data.flag", "==", "false", False),
    ("data.tags", "contains", "b", True),
    ("data.tags", "not contains", "c", True),
    ("version", "contains", "1.2", True),
    ("version", "regex", r"^1\.\d+\.\d+$", True),
    ("data.items", "exists", None, True),
    ("data.missing", "not exists", None, True),
    ("data.missing", "==", "x", False),
    ("data.none", "==", "null", True),
    ("version", ">", "1", False),  # not a number
])
def test_operators(path, op, value, ok):
    assert evaluate(resolve(DOC, parse_path(path)), op, value) is ok


def jspec(url="https://api.test/status", **config):
    body = ProbeIn(name="j", kind="json", target=url, config=config)
    return ProbeSpec(kind="json", target=body.target, timeout_s=5, config=body.config)


def checker(payload, status=200):
    c = JsonChecker()
    c.transport = httpx.MockTransport(lambda req: httpx.Response(status, json=payload) if not isinstance(payload, bytes)
                                      else httpx.Response(status, content=payload))
    return c


async def test_json_assertions_pass_and_fail():
    ok = await checker(DOC).check(jspec(assertions=[
        {"path": "data.items[0].status", "op": "==", "value": "ok"}, {"path": "data.count", "op": ">=", "value": "1"}]))
    assert ok.up and ok.message == "HTTP 200, 2 assertions passed"
    assert [a["ok"] for a in ok.details["assertions"]] == [True, True]
    bad = await checker(DOC).check(jspec(assertions=[
        {"path": "data.count", "op": "==", "value": "2"},
        {"path": "data.items[1].status", "op": "==", "value": "ok"},
        {"path": "version", "op": "regex", "value": "^2"}]))
    assert not bad.up and bad.message == "assertion failed: data.items[1].status == ok (+1 more)"
    assert [a["ok"] for a in bad.details["assertions"]] == [True, False, False]
    assert bad.details["assertions"][1]["actual"] == '"degraded"' and bad.metrics["assertions_failed"] == 2


async def test_json_invalid_and_http_errors():
    res = await checker(b"<html>not json</html>").check(jspec(assertions=[{"path": "a", "op": "exists"}]))
    assert not res.up and res.message == "invalid JSON response"
    res = await checker(DOC, 500).check(jspec(assertions=[{"path": "data", "op": "exists"}]))
    assert not res.up and res.message == "HTTP 500"


def test_json_assertion_validation():
    for bad in ([{"path": "a b", "op": "=="}], [{"path": "a", "op": "~="}], [{"path": "a", "op": "=="}],
                [{"path": "a", "op": "regex", "value": "("}], [{"path": "a", "op": "exists"}] * 21):
        with pytest.raises(ValidationError):
            ProbeIn(name="j", kind="json", target="https://x.test", config={"assertions": bad})


# --------------------------------------------------------------------------- push

def test_push_token():
    t = new_push_token()
    assert t.startswith("nsp_") and len(t) > 30 and new_push_token() != t
    assert len(hash_push_token(t)) == 64 and hash_push_token(t) != t


def test_overdue():
    now = datetime.now(UTC)
    assert not overdue(now - timedelta(seconds=80), 60, 30, now)
    assert overdue(now - timedelta(seconds=91), 60, 30, now)
    assert not overdue(None, 60, 30, now, since=now - timedelta(seconds=30))  # new monitor: wait a full round
    assert overdue(None, 60, 30, now, since=now - timedelta(seconds=200))
    assert not overdue(None, 60, 30, now)


async def test_push_checker():
    c = get_checker("push")
    now = datetime.now(UTC)
    fresh = ProbeSpec(kind="push", target="", interval_s=60, config={"grace_s": 30}, last_push_at=now)
    assert await c.check(fresh) is None
    late = ProbeSpec(kind="push", target="", interval_s=60, config={"grace_s": 30},
                     last_push_at=now - timedelta(minutes=5))
    res = await c.check(late)
    assert not res.up and res.message == "no push received"


def test_push_probe_has_no_target():
    p = ProbeIn(name="backup job", kind="push", target="ignored", interval_s=3600)
    assert p.target == "" and p.config == {"grace_s": 30}
