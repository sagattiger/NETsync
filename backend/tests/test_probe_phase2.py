"""dns, udp and tls checkers against local servers."""

import asyncio
import ssl
import sys
from pathlib import Path

import dns.message
import dns.rcode
import dns.rdatatype
import dns.rrset
import pytest
from pydantic import ValidationError

sys.path.insert(0, str(Path(__file__).parent))
from certutil import make_ca, make_cert, make_leaf, pem, write_pair

from netsync.api.probes import ProbeIn
from netsync.models import State
from netsync.probing.base import ProbeSpec, get_checker
from netsync.probing.checkers import tls as tls_mod
from netsync.probing.checkers.dns import answer_matches

# --------------------------------------------------------------------------- dns


class FakeDns(asyncio.DatagramProtocol):
    def __init__(self, records):
        self.records = records  # {(name, TYPE): [rdata text]}; a name with an empty dict entry exists

    def connection_made(self, transport):
        self.t = transport

    def datagram_received(self, data, addr):
        q = dns.message.from_wire(data)
        r = dns.message.make_response(q)
        qn = q.question[0]
        name, rtype = qn.name.to_text().rstrip(".").lower(), dns.rdatatype.to_text(qn.rdtype)
        if (name, rtype) in self.records:
            r.answer.append(dns.rrset.from_text(qn.name, 60, "IN", rtype, *self.records[(name, rtype)]))
        elif not any(n == name for n, _ in self.records):
            r.set_rcode(dns.rcode.NXDOMAIN)
        self.t.sendto(r.to_wire(), addr)


@pytest.fixture
async def dns_server():
    records = {
        ("example.test", "A"): ["192.0.2.10", "192.0.2.11"],
        ("example.test", "MX"): ["10 mail.example.test.", "20 backup.example.test."],
        ("example.test", "TXT"): ['"v=spf1 -all"'],
        ("example.test", "CAA"): ['0 issue "letsencrypt.org"'],
        ("_sip._tcp.example.test", "SRV"): ["10 5 5060 sip.example.test."],
        ("10.2.0.192.in-addr.arpa", "PTR"): ["host.example.test."],
        ("www.example.test", "CNAME"): ["example.test."],
    }
    loop = asyncio.get_running_loop()
    transport, _ = await loop.create_datagram_endpoint(lambda: FakeDns(records), local_addr=("127.0.0.1", 0))
    yield transport.get_extra_info("sockname")[1]
    transport.close()


def dspec(name, port, **cfg):
    body = ProbeIn(name="d", kind="dns", target=name, config={"resolver": "127.0.0.1", "resolver_port": port, **cfg})
    return ProbeSpec(kind="dns", target=body.target, timeout_s=2, config=body.config)


async def test_dns_records(dns_server):
    c = get_checker("dns")
    a = await c.check(dspec("example.test", dns_server))
    assert a.up and a.message == "2 A records" and a.metrics["dns_query_ms"] >= 0
    assert (await c.check(dspec("example.test", dns_server, expected=["192.0.2.11"]))).up
    assert (await c.check(dspec("example.test", dns_server, expected=["192.0.2.10", "192.0.2.11"], match="all"))).up
    bad = await c.check(dspec("example.test", dns_server, expected=["192.0.2.10", "203.0.113.1"], match="all"))
    assert not bad.up and bad.message == "answer mismatch"
    assert (await c.check(dspec("example.test", dns_server, expected=["192.0.2.10", "203.0.113.1"]))).up  # any
    assert (await c.check(dspec("example.test", dns_server, record_type="MX", expected=["mail.example.test"]))).up
    assert (await c.check(dspec("example.test", dns_server, record_type="TXT", expected=["v=spf1 -all"]))).up
    assert (await c.check(dspec("example.test", dns_server, record_type="CAA", expected=["letsencrypt.org"]))).up
    assert (await c.check(dspec("_sip._tcp.example.test", dns_server, record_type="SRV", expected=["sip.example.test"]))).up
    assert (await c.check(dspec("192.0.2.10", dns_server, record_type="PTR", expected=["host.example.test"]))).up
    assert (await c.check(dspec("www.example.test", dns_server, record_type="CNAME", expected=["example.test."]))).up


async def test_dns_failures(dns_server):
    c = get_checker("dns")
    nx = await c.check(dspec("missing.test", dns_server))
    assert not nx.up and nx.message == "NXDOMAIN"
    empty = await c.check(dspec("example.test", dns_server, record_type="AAAA"))
    assert not empty.up and empty.message == "no AAAA records"


def test_dns_validation():
    assert answer_matches(["10 mail.example.test"], ["MAIL.example.test."], "any")
    for bad in ({"record_type": "ANY"}, {"resolver": "dns.google"}, {"expected": ["x" * 600]}, {"resolver_port": 0}):
        with pytest.raises(ValidationError):
            ProbeIn(name="d", kind="dns", target="example.com", config=bad)
    with pytest.raises(ValidationError):
        ProbeIn(name="d", kind="dns", target="exa mple.com")


# --------------------------------------------------------------------------- udp


class Echo(asyncio.DatagramProtocol):
    def connection_made(self, transport):
        self.t = transport

    def datagram_received(self, data, addr):
        self.t.sendto(b"PONG " + data, addr)


@pytest.fixture
async def udp_echo():
    loop = asyncio.get_running_loop()
    transport, _ = await loop.create_datagram_endpoint(Echo, local_addr=("127.0.0.1", 0))
    yield transport.get_extra_info("sockname")[1]
    transport.close()


def uspec(port, timeout=1, **cfg):
    body = ProbeIn(name="u", kind="udp", target="127.0.0.1", port=port, config=cfg)
    return ProbeSpec(kind="udp", target="127.0.0.1", port=port, timeout_s=timeout, config=body.config)


async def test_udp_expect(udp_echo):
    c = get_checker("udp")
    ok = await c.check(uspec(udp_echo, payload="ping", expect="PONG ping"))
    assert ok.up and ok.message == "reply matched" and ok.response_ms is not None
    assert (await c.check(uspec(udp_echo, payload="ping", expect=r"^PONG \w+$", expect_mode="regex"))).up
    assert (await c.check(uspec(udp_echo, payload="de ad be ef", payload_hex=True, expect="deadbeef", expect_mode="hex"))).up
    bad = await c.check(uspec(udp_echo, payload="ping", expect="nope"))
    assert not bad.up and bad.message == "unexpected reply"
    assert (await c.check(uspec(udp_echo, payload="ping"))).up  # no expect: any reply / no error is up


@pytest.mark.skipif(sys.platform == "win32", reason="ICMP port unreachable is reported differently on Windows")
async def test_udp_closed_port():
    loop = asyncio.get_running_loop()
    t, _ = await loop.create_datagram_endpoint(asyncio.DatagramProtocol, local_addr=("127.0.0.1", 0))
    port = t.get_extra_info("sockname")[1]
    t.close()
    res = await get_checker("udp").check(uspec(port, payload="x", expect="y"))
    assert not res.up and res.message in ("port unreachable", "no reply")


def test_udp_validation():
    for bad in ({"payload": "zz", "payload_hex": True}, {"expect": "(", "expect_mode": "regex"}, {"expect": "0x1", "expect_mode": "hex"}):
        with pytest.raises(ValidationError):
            ProbeIn(name="u", kind="udp", target="127.0.0.1", port=53, config=bad)


# --------------------------------------------------------------------------- tls


@pytest.fixture
def ca(tmp_path, monkeypatch):
    ca_cert, ca_key = make_ca()
    path = tmp_path / "ca.pem"
    path.write_bytes(pem(ca_cert))
    monkeypatch.setattr(tls_mod, "CAFILE", str(path))
    return ca_cert, ca_key


async def tls_server(tmp_path, cert, key, starttls=False):
    ctx = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
    ctx.load_cert_chain(*write_pair(tmp_path, cert, key))

    async def plain(r, w):
        await asyncio.sleep(0.3)
        w.close()

    async def smtp(r, w):
        w.write(b"220 test ESMTP\r\n")
        await w.drain()
        await r.readline()
        w.write(b"250-test\r\n250 STARTTLS\r\n")
        await w.drain()
        await r.readline()
        w.write(b"220 go ahead\r\n")
        await w.drain()
        try:
            await w.start_tls(ctx)
            await asyncio.sleep(0.3)
        except Exception:  # noqa: BLE001 - the client may hang up after the handshake
            pass
        w.close()

    server = await asyncio.start_server(smtp if starttls else plain, "127.0.0.1", 0, ssl=None if starttls else ctx)
    return server, server.sockets[0].getsockname()[1]


def tspec(port, sni="localhost", **cfg):
    body = ProbeIn(name="t", kind="tls", target="127.0.0.1", port=port, config={"sni": sni, **cfg})
    return ProbeSpec(kind="tls", target="127.0.0.1", port=port, timeout_s=3, config=body.config)


async def test_tls_valid_chain(tmp_path, ca):
    cert, key = make_leaf(*ca, sans=("localhost",), days=60)
    server, port = await tls_server(tmp_path, cert, key)
    async with server:
        res = await get_checker("tls").check(tspec(port))
    assert res.up and res.message.startswith("certificate expires in")
    assert res.cert["chain_valid"] is True and res.cert["hostname_match"] is True and res.cert["tls_version"]
    assert res.cert["issuer"] == "NETsync Test CA" and 59 <= res.metrics["tls_days_left"] <= 60
    assert all(c.state in (None, State.OK) for c in res.checks)


async def test_tls_expiry_thresholds(tmp_path, ca):
    cert, key = make_leaf(*ca, sans=("localhost",), days=10)
    server, port = await tls_server(tmp_path, cert, key)
    async with server:
        res = await get_checker("tls").check(tspec(port, warn_days=21, crit_days=7))
        assert res.up and next(c for c in res.checks if c.name == "Certificate expiry").state == State.WARN
        res = await get_checker("tls").check(tspec(port, warn_days=30, crit_days=14))
        assert next(c for c in res.checks if c.name == "Certificate expiry").state == State.CRIT
        assert res.message == "certificate expires in 10 days" or res.message == "certificate expires in 9 days"


async def test_tls_hostname_mismatch_and_untrusted(tmp_path, ca):
    cert, key = make_leaf(*ca, sans=("localhost",), days=60)
    server, port = await tls_server(tmp_path, cert, key)
    async with server:
        res = await get_checker("tls").check(tspec(port, sni="other.test"))
    assert not res.up and res.message == "certificate hostname mismatch"
    assert res.cert["chain_valid"] is True and res.cert["hostname_match"] is False
    assert next(c for c in res.checks if c.name == "Certificate validity").state == State.CRIT

    self_signed, key2 = make_cert("localhost", ("localhost",), days=60)
    server, port = await tls_server(tmp_path, self_signed, key2)
    async with server:
        res = await get_checker("tls").check(tspec(port))
    assert not res.up and res.message == "certificate untrusted" and res.cert["chain_valid"] is False


async def test_tls_expired(tmp_path, ca):
    cert, key = make_leaf(*ca, sans=("localhost",), days=-2, not_before_days=30)
    server, port = await tls_server(tmp_path, cert, key)
    async with server:
        res = await get_checker("tls").check(tspec(port))
    assert not res.up and res.message == "certificate expired"
    assert next(c for c in res.checks if c.name == "Certificate expiry").state == State.CRIT


async def test_tls_starttls_smtp(tmp_path, ca):
    cert, key = make_leaf(*ca, sans=("localhost",), days=60)
    server, port = await tls_server(tmp_path, cert, key, starttls=True)
    async with server:
        res = await get_checker("tls").check(tspec(port, starttls="smtp"))
    assert res.up and res.cert["subject_cn"] == "localhost"


async def test_tls_connection_refused():
    s = await asyncio.start_server(lambda r, w: None, "127.0.0.1", 0)
    port = s.sockets[0].getsockname()[1]
    s.close()
    await s.wait_closed()
    res = await get_checker("tls").check(tspec(port))
    assert not res.up and res.message == "connection refused"


def test_cert_expiry_default_rule_levels():
    from netsync.plugins.base import CheckResult
    from netsync.rules.engine import RuleSet

    rs = RuleSet([])

    def state(days):
        return rs.evaluate(CheckResult("tls_days_left", "Certificate expiry", output="x", value=days), 1, set())[0]

    assert (state(60), state(20), state(6)) == (State.OK, State.WARN, State.CRIT)
