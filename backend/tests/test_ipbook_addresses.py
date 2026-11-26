"""IP books: one row per address like the owner's sheet, its status, size limit and what discovery fills (invented data)."""

from datetime import UTC, datetime
from types import SimpleNamespace as NS

import pytest

from netsync.plugins.builtin.ipbook import addrlogic, columns

NOW = datetime(2026, 11, 26, tzinfo=UTC)


def test_ip_book_columns_match_the_sheet():
    assert [c["label"] for c in columns.IP_BUILTIN] == [
        "Hostname", "Internal ID", "Device", "Location", "Interface Name", "Mac-Address", "ISP Customer",
        "End Customer", "Private IP", "Last Mile Provider", "Info."]
    assert all(c["key"].startswith("addr_") for c in columns.IP_BUILTIN)
    assert not {c["key"] for c in columns.IP_BUILTIN} & {c["key"] for c in columns.BUILTIN}  # keys are unique
    assert {c["key"]: c["type"] for c in columns.IP_BUILTIN}["addr_private_ip"] == "ip"


def test_book_cidr_limits():
    assert addrlogic.book_cidr(" 192.0.2.7/24 ") == "192.0.2.0/24"
    assert addrlogic.book_cidr("10.0.0.0/20") == "10.0.0.0/20"
    for bad in ("10.0.0.0/19", "10.0.0.0/8", "not a network", "2001:db8::/64"):
        with pytest.raises(ValueError):
            addrlogic.book_cidr(bad)
    assert addrlogic.book_cidr("2001:db8::/116") == "2001:db8::/116"  # 4096 addresses is fine


def stored(ip, values=None, reserved=False, source="manual"):
    return NS(ip=ip, values=values or {}, reserved=reserved, source=source, alert_when_down=None,
              updated_at=NOW, updated_by="admin", id=1)


def test_address_rows_like_the_sheet():
    rows = addrlogic.address_rows(
        "192.0.2.0/29", "192.0.2.1",
        {"192.0.2.3": stored("192.0.2.3", {"addr_hostname": "app01.example.test"}, source="learned"),
         "192.0.2.4": stored("192.0.2.4", reserved=True),
         "192.0.2.5": stored("192.0.2.5", {"addr_info": "printer"})},
        {"192.0.2.5": {"state": "down"}, "192.0.2.3": {"state": "up", "rtt": 1.0}})
    assert [(r["ip"], r["status"]) for r in rows] == [
        ("192.0.2.0", "subnet"), ("192.0.2.1", "gateway"), ("192.0.2.2", "available"), ("192.0.2.3", "used"),
        ("192.0.2.4", "reserved"), ("192.0.2.5", "down"), ("192.0.2.6", "available"), ("192.0.2.7", "broadcast")]
    assert rows[3]["values"] == {"addr_hostname": "app01.example.test"} and rows[3]["learned"] is True
    assert rows[3]["health"] == {"state": "up", "rtt": 1.0} and rows[2]["values"] == {}
    assert addrlogic.counts(rows) == {"size": 6, "used": 3, "available": 2, "reserved": 1}


def test_point_to_point_has_no_subnet_rows():
    assert [r["status"] for r in addrlogic.address_rows("192.0.2.0/31", None, {}, {})] == ["available", "available"]


def test_learned_address_values():
    dev = NS(hostname="app01.example.test", sys_name="app01", hardware="Proxmox LXC", vendor="Linux")
    assert addrlogic.learned_address_values(dev, "eth0", "bc:24:11:00:00:01") == {
        "addr_hostname": "app01.example.test", "addr_device": "Proxmox LXC", "addr_interface": "eth0",
        "addr_mac": "bc:24:11:00:00:01"}
    bare = NS(hostname="sw01.example.test", sys_name=None, hardware=None, vendor="MikroTik")
    assert addrlogic.learned_address_values(bare, None, None) == {"addr_hostname": "sw01.example.test", "addr_device": "MikroTik"}


def test_books_for_ip():
    books = [NS(id=1, cidr="10.0.0.0/24"), NS(id=2, cidr="10.0.1.0/24"), NS(id=3, cidr=None)]
    assert [b.id for b in addrlogic.books_for("10.0.1.9", books)] == [2]
    assert addrlogic.books_for("198.51.100.1", books) == []
