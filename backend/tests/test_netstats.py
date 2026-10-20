from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from pytest import approx

from netsync.plugins.base import DeviceContext
from netsync.plugins.builtin.netstats import COUNTERS, GAUGES, NetstatsModule


class FakeSnmp:
    def __init__(self, values: dict):
        self.values = values

    async def get(self, *oids):
        return {o: self.values.get(o) for o in oids}


def snmp_with(**named):
    oids = {**GAUGES, **COUNTERS}
    return FakeSnmp({oids[k]: v for k, v in named.items()})


def component(values=None):
    return SimpleNamespace(kind="netstat", index="0", enabled=True, deleted=False, values=values or {})


async def test_discover_only_when_tcp_mib_answers():
    ctx = DeviceContext(None, snmp_with(), [], datetime.now(UTC))
    assert await NetstatsModule().discover(ctx) == []
    ctx = DeviceContext(None, snmp_with(tcp_estab=3), [], datetime.now(UTC))
    assert [s.kind for s in await NetstatsModule().discover(ctx)] == ["netstat"]


async def test_rates_and_checks_over_two_polls():
    mod = NetstatsModule()
    t0 = datetime.now(UTC)
    first = await mod.poll(DeviceContext(None, snmp_with(tcp_estab=5, tcp_out_segs=1000, tcp_retrans_segs=10,
                                                         udp_in_errors=0), [component()], t0))
    assert first.checks == []  # no rates on the first poll
    stored = first.values[("netstat", "0")]

    second = await mod.poll(DeviceContext(None, snmp_with(tcp_estab=7, tcp_out_segs=11000, tcp_retrans_segs=1010,
                                                          udp_in_errors=600), [component(stored)], t0 + timedelta(seconds=100)))
    metrics = {m.name: m.value for m in second.metrics}
    assert metrics["tcp_estab"] == 7
    assert metrics["tcp_out_segs"] == approx(100)  # (11000-1000)/100s
    assert metrics["tcp_retrans_pct"] == approx(10)  # 10 of 100 segs/s retransmitted
    checks = {c.check: c for c in second.checks}
    assert checks["tcp_retrans"].value == approx(10)
    assert checks["udp_errors"].value == approx(6)


async def test_retransmit_rate_not_judged_on_idle_host():
    mod = NetstatsModule()
    t0 = datetime.now(UTC)
    stored = {"ts": t0.timestamp(), "tcp_out_segs": 1000, "tcp_retrans_segs": 0}
    # 80 segments in 100 s (0.8/s), 50 of them retransmits = 62.5% but meaningless
    res = await mod.poll(DeviceContext(None, snmp_with(tcp_estab=2, tcp_out_segs=1080, tcp_retrans_segs=50),
                                       [component(stored)], t0 + timedelta(seconds=100)))
    tcp = next(c for c in res.checks if c.check == "tcp_retrans")
    assert tcp.value is None
    assert "low traffic" in tcp.output


async def test_counter_wrap_is_skipped():
    mod = NetstatsModule()
    t0 = datetime.now(UTC)
    stored = {"ts": t0.timestamp(), "tcp_out_segs": 5000}
    res = await mod.poll(DeviceContext(None, snmp_with(tcp_estab=1, tcp_out_segs=10), [component(stored)],
                                       t0 + timedelta(seconds=60)))
    assert "tcp_out_segs" not in {m.name for m in res.metrics}
