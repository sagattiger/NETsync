"""IP book network scan: every address of a scanned book is pinged; live ones show up with their DNS name."""
from datetime import UTC, datetime
from types import SimpleNamespace

from netsync.plugins.builtin.ipbook import addrlogic, health, service
from netsync.plugins.builtin.ipbook.api import book_fields

NOW = datetime(2026, 11, 27, tzinfo=UTC)


def book(**kw):
    base = {"id": 1, "kind": "ip", "cidr": "10.0.0.0/29", "gateway": "10.0.0.6", "scan": True, "alert_when_down": False,
            "title": "t"}
    return SimpleNamespace(**{**base, **kw})


def test_scan_targets_cover_usable_addresses_not_pinged_already():
    got = service.scan_targets({1: book()}, already={"a1:10.0.0.2"})
    assert got == [("a1:10.0.0.1", "10.0.0.1"), ("a1:10.0.0.3", "10.0.0.3"), ("a1:10.0.0.4", "10.0.0.4"),
                   ("a1:10.0.0.5", "10.0.0.5"), ("a1:10.0.0.6", "10.0.0.6")]


def test_books_without_scan_and_service_books_are_not_scanned():
    assert service.scan_targets({1: book(scan=False), 2: book(id=2, kind="service", cidr=None)}, already=set()) == []


def test_scan_state_keeps_only_addresses_that_answer():
    up = service.scan_state(None, True, 1.5, NOW)
    assert up["state"] == "up" and up["rtt"] == 1.5
    assert service.scan_state(None, False, None, NOW) is None
    # a live address that stops answering stays until it misses 3 rounds, then it is gone (not "down")
    s = up
    for _ in range(2):
        s = service.scan_state(s, False, None, NOW)
        assert s is not None
    assert service.scan_state(s, False, None, NOW) is None


def test_dns_name_is_carried_to_the_next_round():
    prev = {"state": "up", "misses": 0, "name": "nas.example.test", "name_at": NOW.isoformat()}
    new = health.next_state(prev, True, 1.0, NOW)
    assert service.keep_name(prev, new)["name"] == "nas.example.test"
    assert service.keep_name(None, new) == new


def test_names_needed_for_live_addresses_without_a_fresh_name():
    states = {"a1:10.0.0.1": {"state": "up"}, "a1:10.0.0.2": {"state": "up", "name": "x", "name_at": NOW.isoformat()},
              "a1:10.0.0.3": {"state": "down"}}
    assert service.names_needed(states, NOW) == {"a1:10.0.0.1": "10.0.0.1"}


def test_an_address_that_answers_without_data_is_live_and_counts_as_used():
    rows = addrlogic.address_rows("10.0.0.0/29", None, {}, {"10.0.0.3": {"state": "up", "rtt": 1}})
    by = {r["ip"]: r["status"] for r in rows}
    assert by["10.0.0.3"] == "live" and by["10.0.0.4"] == "available"
    assert addrlogic.counts(rows)["used"] == 1


def test_rows_carry_the_device_behind_an_address():
    addr = SimpleNamespace(values={"addr_hostname": "pve1"}, reserved=False, source="learned", alert_when_down=None,
                           updated_at=None, updated_by="discovery", device_id=7)
    dev = {"id": 7, "os": "proxmox", "vendor": None, "sys_descr": None, "device_type": "server", "virtualization": None}
    rows = addrlogic.address_rows("10.0.0.0/30", None, {"10.0.0.1": addr}, {}, devices={7: dev})
    assert rows[1]["device"] == dev and rows[2]["device"] is None


def test_new_ip_books_are_scanned_unless_switched_off():
    assert book_fields("ip", {"cidr": "10.0.0.0/24"})["scan"] is True
    assert book_fields("ip", {"cidr": "10.0.0.0/24", "scan": False})["scan"] is False


def test_an_address_without_a_dns_name_is_not_looked_up_again_every_round():
    prev = {"state": "up", "misses": 0, "name": None, "name_at": NOW.isoformat()}
    kept = service.keep_name(prev, health.next_state(prev, True, 1.0, NOW))
    assert service.names_needed({"a1:10.0.0.9": kept}, NOW) == {}
