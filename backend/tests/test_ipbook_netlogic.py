"""IP Book networks: membership, usage, grid and warnings (invented addresses only)."""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace as NS

from netsync.plugins.builtin.ipbook import netlogic

IPS = {"ip_mgmt", "ip_wan", "ip_lan", "other_ips"}
NOW = datetime(2026, 11, 26, tzinfo=UTC)


def net(i, cidr, hidden=False):
    return NS(id=i, cidr=cidr, hidden=hidden)


def row(i, runs_on=None, source="manual", missing=None, conflicts=None, **values):
    return NS(id=i, values=values, runs_on_id=runs_on, source=source, missing_since=missing,
              conflicts=conflicts or {}, sensitive=False)


def kinds(found, key, ident):
    return sorted(w["kind"] for w in found[key].get(ident, []))


def test_learnable_network():
    assert netlogic.learnable_network("192.0.2.7/24") == "192.0.2.0/24"
    for bad in ("127.0.0.1/8", "169.254.1.1/16", "224.0.0.5/24", "10.0.0.1/32", "10.0.0.1/8", "2001:db8::1/64", "10.0.0.1"):
        assert netlogic.learnable_network(bad) is None, bad


def test_row_ips_reads_several_values():
    r = row(1, ip_lan="10.0.1.5, 10.0.1.6", ip_mgmt="10.0.0.5", other_ips=["10.0.2.7"], hostname="10.0.0.9")
    assert sorted(netlogic.row_ips(r, IPS)) == [("ip_lan", "10.0.1.5"), ("ip_lan", "10.0.1.6"),
                                                ("ip_mgmt", "10.0.0.5"), ("other_ips", "10.0.2.7")]


def test_row_in_two_overlapping_networks():
    big, small = net(1, "10.0.0.0/16"), net(2, "10.0.1.0/24")
    r = row(7, ip_lan="10.0.1.5")
    assert [(x.id, keys) for x, keys in netlogic.rows_in_network(big, [r], IPS)] == [(7, ["ip_lan"])]
    assert [x.id for x, _ in netlogic.rows_in_network(small, [r], IPS)] == [7]
    found = netlogic.warnings([big, small], [r], IPS, {}, {}, NOW)
    overlap = [w for w in found["networks"][1] if w["kind"] == "overlap"]
    assert len(overlap) == 1 and sorted(overlap[0]["networks"]) == [1, 2]


def test_shared_ip_rules():
    a = row(1, ip_lan="10.0.0.5")
    b, c = row(2, runs_on=1, ip_lan="10.0.0.5"), row(3, runs_on=1, ip_lan="10.0.0.5")
    nets = [net(1, "10.0.0.0/24")]
    assert netlogic.warnings(nets, [a, b, c], IPS, {}, {}, NOW)["rows"] == {}
    d = row(4, ip_lan="10.0.0.5")
    found = netlogic.warnings(nets, [a, b, c, d], IPS, {}, {}, NOW)
    dup_rows = {i for i, ws in found["rows"].items() if any(w["kind"] == "duplicate" for w in ws)}
    assert dup_rows == {1, 4}
    n1, n2 = row(5, nat=True, ip_wan="198.51.100.9"), row(6, nat=True, ip_wan="198.51.100.9")
    assert netlogic.warnings(nets, [n1, n2], IPS, {}, {}, NOW)["rows"] == {}
    l1, l2 = row(8, nat=True, ip_lan="10.0.0.20"), row(9, nat=True, ip_lan="10.0.0.20")
    assert kinds(netlogic.warnings(nets, [l1, l2], IPS, {}, {}, NOW), "rows", 8) == ["duplicate"]


def test_ip_on_a_different_discovered_device():
    r = row(1, ip_lan="10.0.0.5")
    found = netlogic.warnings([net(1, "10.0.0.0/24")], [r], IPS, {"10.0.0.5": 42}, {1: 41}, NOW)
    assert kinds(found, "rows", 1) == ["device_conflict"]
    assert netlogic.warnings([net(1, "10.0.0.0/24")], [r], IPS, {"10.0.0.5": 42}, {1: 42}, NOW)["rows"] == {}


def test_outside_only_for_private():
    pub, priv = row(1, ip_wan="198.51.100.9"), row(2, ip_lan="10.9.9.9")
    found = netlogic.warnings([net(1, "10.0.0.0/24")], [pub, priv], IPS, {}, {}, NOW)
    assert 1 not in found["rows"] and kinds(found, "rows", 2) == ["outside"]


def test_usage_and_full():
    n = net(1, "192.0.2.0/29")
    used = {f"192.0.2.{i}" for i in range(1, 7)}
    assert netlogic.usage(n.cidr, used) == {"size": 6, "used": 6, "free": 0, "pct": 100}
    rows = [row(i, ip_lan=ip) for i, ip in enumerate(sorted(used), start=1)]
    assert "full" in kinds(netlogic.warnings([n], rows, IPS, {}, {}, NOW), "networks", 1)
    assert len(netlogic.grid(n.cidr, {"192.0.2.1": "used", "192.0.2.2": "down"})) == 6
    assert netlogic.grid(n.cidr, {"192.0.2.1": "used"})[:3] == ["used", "free", "free"]
    assert netlogic.grid("10.0.0.0/16", {}) is None
    assert netlogic.usage("10.0.0.5/32", {"10.0.0.5"})["size"] == 1


def test_missing_after_7_days():
    old = row(1, source="learned", missing=NOW - timedelta(days=8), ip_lan="10.0.0.5")
    new = row(2, source="learned", missing=NOW - timedelta(days=6), ip_lan="10.0.0.6")
    found = netlogic.warnings([net(1, "10.0.0.0/24")], [old, new], IPS, {}, {}, NOW)
    assert kinds(found, "rows", 1) == ["missing"] and 2 not in found["rows"]


def test_unresolved_conflict_warns():
    r = row(1, conflicts={"ip_lan": {"manual": "10.0.0.5", "discovered": "10.0.0.6"}}, ip_lan="10.0.0.5")
    assert kinds(netlogic.warnings([net(1, "10.0.0.0/24")], [r], IPS, {}, {}, NOW), "rows", 1) == ["conflict"]


def test_warnings_stay_fast_with_thousands_of_rows():
    import time

    nets = [net(i, f"10.{i}.0.0/24") for i in range(1, 61)]
    rows = [row(i, ip_lan=f"10.{1 + i % 60}.0.{1 + i % 250}", ip_mgmt=f"10.200.{i // 250}.{i % 250}") for i in range(3000)]
    t = time.perf_counter()
    netlogic.warnings(nets, rows, IPS, {}, {}, NOW)
    assert time.perf_counter() - t < 1.0


def test_hidden_network_silences_its_addresses():
    hidden = net(2, "172.17.0.0/16", hidden=True)
    a, b = row(1, other_ips=["172.17.0.1"]), row(2, other_ips=["172.17.0.1"])
    found = netlogic.warnings([net(1, "10.0.0.0/24"), hidden], [a, b], IPS, {}, {}, NOW)
    assert found["rows"] == {}
    assert netlogic.in_hidden("172.17.0.1", [hidden]) and not netlogic.in_hidden("10.0.0.5", [hidden])
