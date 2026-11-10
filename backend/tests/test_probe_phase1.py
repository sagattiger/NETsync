"""Probe framework, runner behaviour, secrets, tcp and http checkers (against local servers)."""

import asyncio
import json
import ssl
import sys
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from pydantic import ValidationError

sys.path.insert(0, str(Path(__file__).parent))
from certutil import der, make_cert, write_pair

from netsync.api.probes import ProbeIn, probe_out
from netsync.models import State
from netsync.probing.base import REGISTRY, ProbeSpec, Result, get_checker
from netsync.probing.certs import cert_checks, cert_info, hostname_matches
from netsync.probing.checkers.http import MAX_BODY, HttpChecker, parse_codes, validate_url
from netsync.probing.runner import decide, next_delay, should_resend, uptime_pct
from netsync.probing.secrets import MASK, decrypt, describe, encrypt, merge


def spec(kind, target, port=None, timeout=3, **config):
    return ProbeSpec(kind=kind, target=target, port=port, timeout_s=timeout, config=config)


# --------------------------------------------------------------------------- registry / validation

def test_registry_has_phase1_kinds():
    assert {"icmp", "tcp", "http"} <= set(REGISTRY)
    with pytest.raises(ValueError):
        get_checker("smtp")


def test_probe_in_validation():
    p = ProbeIn(name="web", kind="http", target="https://example.com/health", config={"accepted_codes": "200-299,301"})
    assert p.port is None and p.config["method"] == "GET" and p.config["accepted_codes"] == "200-299,301"
    t = ProbeIn(name="ssh", kind="tcp", target="Example.COM", port=22)
    assert t.target == "example.com" and t.port == 22
    for bad in (
        {"kind": "tcp", "target": "example.com"},  # no port
        {"kind": "tcp", "target": "example.com", "port": 70000},
        {"kind": "tcp", "target": "a b", "port": 22},
        {"kind": "http", "target": "ftp://example.com"},
        {"kind": "http", "target": "javascript:alert(1)"},
        {"kind": "http", "target": "https://user:pw@example.com/"},
        {"kind": "http", "target": "https://example.com", "config": {"accepted_codes": "abc"}},
        {"kind": "http", "target": "https://example.com", "config": {"max_redirects": 11}},
        {"kind": "http", "target": "https://example.com", "config": {"unknown": 1}},
        {"kind": "http", "target": "https://example.com", "secrets": {"headers": {"X-A": "a\r\nInjected: 1"}}},
        {"kind": "http", "target": "https://example.com", "secrets": {"nope": "x"}},
        {"kind": "icmp", "target": "8.8.8.8", "interval_s": 10},
        {"kind": "icmp", "target": "8.8.8.8", "interval_s": 3601},
        {"kind": "smtp", "target": "example.com"},
    ):
        with pytest.raises(ValidationError):
            ProbeIn(name="x", **bad)
    assert ProbeIn(name="x", target="8.8.8.8", interval_s=20, timeout_s=60).timeout_s == 19  # timeout < interval


def test_url_scheme_allow_list():
    assert validate_url("http://10.0.0.1:8080/x?y=1") == "http://10.0.0.1:8080/x?y=1"
    for bad in ("file:///etc/passwd", "gopher://x", "https://", "https://exa mple.com", "//example.com"):
        with pytest.raises(ValueError):
            validate_url(bad)


def test_status_code_ranges():
    assert parse_codes("200-299, 301") == [(200, 299), (301, 301)]
    for bad in ("", "99", "200-100", "600", "2xx"):
        with pytest.raises(ValueError):
            parse_codes(bad)


# --------------------------------------------------------------------------- runner behaviour

def test_retries_before_down():
    down = Result(False, None, State.CRIT, "timeout")
    st, fails, msg, pending = decide(down, False, 3, 0)
    assert (st, fails, pending) == (State.UNKNOWN, 1, True) and "retry 1/3" in msg
    st, fails, _, pending = decide(down, False, 3, 1)
    assert (st, fails, pending) == (State.UNKNOWN, 2, True)
    st, fails, msg, pending = decide(down, False, 3, 2)
    assert (st, fails, msg, pending) == (State.CRIT, 3, "timeout", False)
    st, fails, _, _ = decide(Result(True, 5.0), False, 3, 3)
    assert (st, fails) == (State.OK, 0)
    assert decide(down, False, 1, 0)[0] == State.CRIT  # default: the first failure is DOWN


def test_upside_down():
    st, _, msg, _ = decide(Result(False, None, State.CRIT, "connection refused"), True, 1, 0)
    assert st == State.OK and msg == "connection refused (expected down)"
    st, _, msg, _ = decide(Result(True, 3.0, State.OK, "connected"), True, 1, 0)
    assert st == State.CRIT and "should be down" in msg


def test_warn_result_stays_warn():
    assert decide(Result(True, 5.0, State.WARN, "slow"), False, 1, 0)[0] == State.WARN


def test_next_delay_jitter_and_retry_interval():
    vals = [next_delay(60, 20, False) for _ in range(200)]
    assert all(57 <= v <= 63 for v in vals) and len(set(vals)) > 50
    assert all(19 <= next_delay(60, 20, True) <= 21 for _ in range(50))
    assert all(57 <= next_delay(60, None, True) <= 63 for _ in range(50))


def test_resend_while_down():
    assert [n for n in range(1, 12) if should_resend(State.CRIT, n, 1, 3)] == [4, 7, 10]
    assert not should_resend(State.CRIT, 5, 1, 0)
    assert not should_resend(State.OK, 4, 1, 3)


def test_uptime_pct():
    assert uptime_pct(0, 0) is None and uptime_pct(None, None) is None
    assert uptime_pct(1000, 999) == 99.9
    # maintenance beats are excluded from total by the aggregate: 10 beats, 4 in maintenance, 1 down -> 5/6
    beats = [("up", False)] * 5 + [("down", False)] + [("down", True)] * 4
    total = sum(1 for _, m in beats if not m)
    up = sum(1 for s, m in beats if not m and s == "up")
    assert uptime_pct(total, up) == round(500 / 6, 3)


# --------------------------------------------------------------------------- secrets

def test_secrets_encrypted_and_never_returned():
    data = {"password": "hunter2", "headers": {"X-Api-Key": "abc123"}}
    token = encrypt(data, "k1")
    assert "hunter2" not in token and "abc123" not in token
    assert decrypt(token, "k1") == data
    assert decrypt(token, "other-key") == {}
    assert encrypt({}, "k1") is None and decrypt(None) == {}
    assert describe(data) == {"has_password": True, "has_headers": True, "header_names": ["X-Api-Key"]}
    assert merge(data, None) == data
    assert merge(data, {"password": MASK}) == data  # masked value = keep
    assert merge(data, {"password": ""}) == {"headers": {"X-Api-Key": "abc123"}}  # empty = clear
    assert merge(data, {"token": "t"})["token"] == "t"


def test_probe_out_has_no_secret_values():
    p = SimpleNamespace(
        id=1, name="api", kind="http", target="https://example.com", port=None, interval_s=60, timeout_s=10,
        retries=1, retry_interval_s=None, upside_down=False, resend_every=0, count=5, enabled=True, tags=[],
        description=None, config={"auth": "basic", "auth_user": "bob"}, created_at=None, last_run=None,
        next_run=None, last_error=None, last_state=0, last_message="HTTP 200", last_response_ms=12.0, fail_count=0,
        cert=None, push_token_hash=None, secrets_enc=encrypt({"password": "s3cr3t", "headers": {"Cookie": "sid=xyz"}}))
    d = SimpleNamespace(id=9, groups=[])
    text = json.dumps(probe_out(p, d), default=str)
    assert "s3cr3t" not in text and "sid=xyz" not in text
    assert '"has_password": true' in text and "Cookie" in text


# --------------------------------------------------------------------------- tcp

async def _server(handler, ssl_ctx=None):
    server = await asyncio.start_server(handler, "127.0.0.1", 0, ssl=ssl_ctx)
    return server, server.sockets[0].getsockname()[1]


async def test_tcp_up_and_refused():
    async def handler(r, w):
        w.close()

    server, port = await _server(handler)
    async with server:
        res = await get_checker("tcp").check(spec("tcp", "127.0.0.1", port))
        assert res.up and res.response_ms is not None and res.metrics["connect_ms"] >= 0
    res = await get_checker("tcp").check(spec("tcp", "127.0.0.1", port))
    assert not res.up and res.message == "connection refused"


async def test_tcp_banner_and_send_expect():
    async def smtp(r, w):
        w.write(b"220 mail.example ESMTP\r\n")
        await w.drain()
        line = await r.readline()
        if line.startswith(b"PING"):
            w.write(b"PONG\r\n")
            await w.drain()
        w.close()

    server, port = await _server(smtp)
    async with server:
        tcp = get_checker("tcp")
        assert (await tcp.check(spec("tcp", "127.0.0.1", port, expect="220"))).up
        assert (await tcp.check(spec("tcp", "127.0.0.1", port, expect=r"^220 \S+ ESMTP", expect_regex=True))).up
        bad = await tcp.check(spec("tcp", "127.0.0.1", port, timeout=1, expect="554"))
        assert not bad.up and bad.message == "unexpected response"
        echo = await tcp.check(spec("tcp", "127.0.0.1", port, send="PING\\r\\n", expect="PONG"))
        assert echo.up


async def test_tcp_tls_records_certificate(tmp_path):
    cert, key = make_cert("localhost", ("localhost",), days=5)
    ctx = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
    ctx.load_cert_chain(*write_pair(tmp_path, cert, key))

    async def handler(r, w):
        await asyncio.sleep(0.2)
        w.close()

    server, port = await _server(handler, ctx)
    async with server:
        tcp = get_checker("tcp")
        strict = await tcp.check(spec("tcp", "127.0.0.1", port, tls=True))
        assert not strict.up and strict.message == "TLS certificate invalid"
        res = await tcp.check(spec("tcp", "127.0.0.1", port, tls=True, ignore_tls=True))
        assert res.up and res.cert["subject_cn"] == "localhost" and res.cert["self_signed"]
        assert res.cert["hostname_match"] is False  # connected to 127.0.0.1, cert is for localhost
        assert 4 <= res.metrics["tls_days_left"] <= 5
        expiry = next(c for c in res.checks if c.name == "Certificate expiry")
        assert expiry.value is not None  # no per-probe thresholds: rules decide (default 21/7)


# --------------------------------------------------------------------------- certificates

def test_cert_thresholds_and_validity():
    cert, _ = make_cert("www.example.com", ("www.example.com", "*.cdn.example.com"), days=10)
    info = cert_info(der(cert), "www.example.com", True)
    assert info["hostname_match"] and info["sans"] == ["www.example.com", "*.cdn.example.com"]
    exp, valid = cert_checks(info, warn_days=21, crit_days=7)
    assert exp.state == State.WARN and valid.state == State.OK
    exp, _ = cert_checks(info, warn_days=30, crit_days=14)
    assert exp.state == State.CRIT
    exp, _ = cert_checks(info, warn_days=5, crit_days=2)
    assert exp.state == State.OK
    mismatch = cert_info(der(cert), "evil.example.org", None)
    assert cert_checks(mismatch)[1].state == State.CRIT
    untrusted = cert_info(der(cert), "www.example.com", False)
    assert "untrusted" in cert_checks(untrusted)[1].output
    expired, _ = make_cert("old", ("old",), days=-1, not_before_days=30)
    assert cert_checks(cert_info(der(expired), "old", True))[0].state == State.CRIT


def test_hostname_matching():
    assert hostname_matches("a.example.com", ["*.example.com"], [])
    assert not hostname_matches("b.a.example.com", ["*.example.com"], [])
    assert not hostname_matches("example.com", ["*.example.com"], [])
    assert hostname_matches("10.0.0.1", [], ["10.0.0.1"])


# --------------------------------------------------------------------------- http

def http_checker(handler) -> HttpChecker:
    c = HttpChecker()
    c.transport = httpx.MockTransport(handler)
    return c


def hspec(url="https://svc.test/health", **config):
    return ProbeSpec(kind="http", target=url, timeout_s=5, config=ProbeIn(
        name="x", kind="http", target=url, config=config).config)


async def test_http_status_codes():
    codes = iter([200, 503, 301])
    c = http_checker(lambda req: httpx.Response(next(codes), text="ok"))
    ok = await c.check(hspec())
    assert ok.up and ok.message == "HTTP 200" and ok.metrics["status_code"] == 200 and ok.metrics["ttfb_ms"] >= 0
    bad = await c.check(hspec())
    assert not bad.up and bad.message == "HTTP 503"
    assert (await c.check(hspec(accepted_codes="200-299,301", follow_redirects=False))).up


async def test_http_keyword():
    c = http_checker(lambda req: httpx.Response(200, text="<h1>All Systems Operational</h1>"))
    assert (await c.check(hspec(keyword="Operational"))).up
    miss = await c.check(hspec(keyword="operational"))
    assert not miss.up and miss.message == "keyword not found"
    assert (await c.check(hspec(keyword="operational", keyword_case_insensitive=True))).up
    absent = await c.check(hspec(keyword="Operational", keyword_absent=True))
    assert not absent.up and absent.message == "keyword found"
    assert (await c.check(hspec(keyword="Outage", keyword_absent=True))).up


async def test_http_response_size_cap():
    big = b"x" * (3 * MAX_BODY)
    c = http_checker(lambda req: httpx.Response(200, content=big))
    res = await c.check(hspec())
    assert res.up and res.metrics["body_bytes"] == MAX_BODY


async def test_http_redirect_cap():
    c = http_checker(lambda req: httpx.Response(302, headers={"Location": "https://svc.test/loop"}))
    res = await c.check(hspec(max_redirects=3))
    assert not res.up and res.message == "too many redirects"


async def test_http_auth_and_body():
    seen = {}

    def handler(req: httpx.Request):
        seen.update(auth=req.headers.get("authorization"), key=req.headers.get("x-api-key"),
                    ctype=req.headers.get("content-type"), body=req.content, method=req.method,
                    custom=req.headers.get("x-token"))
        return httpx.Response(200)

    c = http_checker(handler)
    s = hspec(auth="basic", auth_user="bob", method="POST", body='{"a": 1}', body_type="json")
    s.secrets = {"password": "pw", "headers": {"X-Api-Key": "k"}}
    assert (await c.check(s)).up
    assert seen["auth"].startswith("Basic ") and seen["key"] == "k" and seen["ctype"] == "application/json"
    assert seen["body"] == b'{"a": 1}' and seen["method"] == "POST"
    s = hspec(auth="bearer")
    s.secrets = {"token": "tok"}
    await c.check(s)
    assert seen["auth"] == "Bearer tok"
    s = hspec(auth="header", auth_header_name="X-Token")
    s.secrets = {"header_value": "v"}
    await c.check(s)
    assert seen["custom"] == "v"


async def test_http_secret_body():
    seen = {}
    c = http_checker(lambda req: seen.update(body=req.content) or httpx.Response(200))
    s = hspec(method="POST", body="ignored", body_secret=True)
    assert s.config["body"] is None  # never stored in the plain config
    s.secrets = {"body": "user=a&pass=b"}
    await c.check(s)
    assert seen["body"] == b"user=a&pass=b"


async def test_http_connection_errors():
    def boom(req):
        raise httpx.ConnectTimeout("timed out", request=req)

    assert (await http_checker(boom).check(hspec())).message == "timeout"

    def refused(req):
        raise httpx.ConnectError("refused", request=req)

    res = await http_checker(refused).check(hspec())
    assert not res.up and "https://svc.test" not in res.message


async def test_http_against_real_local_server():
    async def handler(r, w):
        await r.readuntil(b"\r\n\r\n")
        w.write(b"HTTP/1.1 200 OK\r\nContent-Length: 5\r\nConnection: close\r\n\r\nhello")
        await w.drain()
        w.close()

    server, port = await _server(handler)
    async with server:
        res = await HttpChecker().check(hspec(f"http://127.0.0.1:{port}/", keyword="hello"))
        assert res.up and res.metrics["body_bytes"] == 5

