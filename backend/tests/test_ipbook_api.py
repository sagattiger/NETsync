"""IP Book API helpers: what a role gets back for a network, and the column delete guard (invented data only)."""

import json
from datetime import UTC, datetime
from types import SimpleNamespace as NS

import pytest

from netsync.plugins.builtin.ipbook import api
from netsync.plugins.builtin.ipbook.columns import BUILTIN
from netsync.plugins.builtin.ipbook.values import seal

KEY = "test-secret-key"
NOW = datetime(2026, 11, 26, tzinfo=UTC)
COLS = [*BUILTIN, {"key": "c_token", "label": "API token", "type": "secret"}]


def row(i, sensitive=False, **values):
    return NS(id=i, values=values, secrets_enc=seal({"web_pass": f"pw-{i}-secret"}, KEY), sensitive=sensitive,
              source="manual", alert_when_down=None, runs_on_id=None, device_id=None, conflicts={},
              missing_since=None, manual_keys=[])


NET = NS(id=1, cidr="10.0.0.0/24", title="Servers", description=None, icon=None, vlan="10", gateway="10.0.0.1",
         dns=None, alert_when_down=False, source="manual", hidden=False)


def view(is_admin, rows, health=None):
    return api.network_view(NET, [NET], rows, COLS, is_admin, health or {}, {}, {}, NOW, KEY)


def test_non_admin_view_hides_sensitive_rows_and_secrets():
    public = row(1, hostname="app01.example.test", ip_lan="10.0.0.5")
    secret = row(2, sensitive=True, hostname="vault01.example.test", ip_lan="10.0.0.5")
    v = view(False, [public, secret])
    dumped = json.dumps(v, default=str)
    assert "vault01" not in dumped and "pw-1-secret" not in dumped and "pw-2-secret" not in dumped
    assert [r["id"] for r in v["rows"]] == [1]
    # the duplicate with the restricted row is still shown, without naming it
    dup = [w for w in v["rows"][0]["warnings"] if w["kind"] == "duplicate"]
    assert dup and dup[0]["rows"] == [1] and "restricted" in dup[0]["text"]


def test_admin_view_has_everything_but_secret_values():
    v = view(True, [row(1, hostname="app01.example.test", ip_lan="10.0.0.5"),
                    row(2, sensitive=True, hostname="vault01.example.test", ip_lan="10.0.0.6")])
    assert [r["id"] for r in v["rows"]] == [1, 2]
    assert v["rows"][0]["secrets"]["web_pass"] == {"set": True}
    assert "pw-1-secret" not in json.dumps(v, default=str)
    assert v["rows"][0]["match_keys"] == ["ip_lan"]


def test_view_has_usage_grid_and_health():
    health = {"1:10.0.0.5": {"state": "up", "rtt": 1.5, "at": "x"}, "2:10.0.0.6": {"state": "down", "rtt": None, "at": "x"}}
    v = view(True, [row(1, ip_lan="10.0.0.5"), row(2, ip_lan="10.0.0.6")], health)
    assert v["usage"]["used"] == 2 and v["grid"][4] == "used" and v["grid"][5] == "down"
    assert v["rows"][0]["health"] == {"10.0.0.5": {"state": "up", "rtt": 1.5, "at": "x"}}


def test_can_see():
    assert api.can_see(row(1), "viewer") and api.can_see(row(1, sensitive=True), "admin")
    assert not api.can_see(row(1, sensitive=True), "operator")


def test_delete_column_check():
    rows = [row(1, c_note="x"), row(2), row(3, c_note="y")]
    assert api.delete_column_check(NS(key="c_note", builtin=False), rows) == 2
    with pytest.raises(ValueError):
        api.delete_column_check(NS(key="hostname", builtin=True), rows)


def test_custom_column_key():
    assert api.custom_key("OOB address!", {"c_oob_address"}) == "c_oob_address_2"
    assert api.custom_key("Rack", set()) == "c_rack"


def test_new_import_columns_get_server_keys():
    existing = [{"key": "c_vpn_password", "type": "text"}, {"key": "hostname", "type": "text"}]
    mapping, specs = api.resolve_new_columns(
        ["hostname", "c_vpn_password", "c_vpn_password"],
        {"c_vpn_password": {"label": "VPN Password", "type": "secret"}}, existing)
    # the client's key is taken by a text column: the secret gets a fresh key, never the plain-text one
    assert mapping[1] == "c_vpn_password_2" and specs["c_vpn_password_2"]["type"] == "secret"
    assert mapping[0] == "hostname" and mapping[2] == "c_vpn_password_2"
    m2, s2 = api.resolve_new_columns(["c_a", None], {"c_a": {"label": "x" * 300, "type": "nope"}}, [])
    assert len(m2[0]) <= 64 and s2[m2[0]]["type"] == "text" and len(s2[m2[0]]["label"]) <= 128


def test_book_fields():
    ip = api.book_fields("ip", {"title": " Servers ", "cidr": "192.0.2.9/24", "gateway": "192.0.2.1"})
    assert ip["cidr"] == "192.0.2.0/24" and ip["title"] == "Servers" and ip["gateway"] == "192.0.2.1"
    assert api.book_fields("ip", {"title": "", "cidr": "192.0.2.0/24"})["title"] == "192.0.2.0/24"
    svc = api.book_fields("service", {"title": "Stack A", "cidr": "10.0.0.0/8"})
    assert svc["cidr"] is None and svc["title"] == "Stack A"
    for kind, body in [("ip", {"title": "x"}), ("ip", {"cidr": "10.0.0.0/16"}), ("ip", {"cidr": "10.0.0.0/24", "gateway": "10.0.1.1"}),
                       ("service", {"title": " "}), ("other", {"title": "x"})]:
        with pytest.raises(ValueError):
            api.book_fields(kind, body)


def test_ip_book_view():
    book = NS(id=4, kind="ip", title="Servers", heading="RANGE IP Example", description=None, icon=None,
              cidr="192.0.2.0/30", vlan="10", gateway="192.0.2.1", dns=None, alert_when_down=False, position=0)
    addr = NS(ip="192.0.2.2", values={"addr_hostname": "app01.example.test"}, reserved=False, source="learned",
              alert_when_down=None, updated_at=NOW, updated_by="discovery", id=1)
    v = api.ip_book_view(book, {"192.0.2.2": addr}, {"a4:192.0.2.2": {"state": "up", "rtt": 1.0}})
    assert v["book"]["heading"] == "RANGE IP Example" and v["counts"] == {"size": 2, "used": 2, "available": 0, "reserved": 0}
    assert [(r["ip"], r["status"]) for r in v["addresses"]] == [
        ("192.0.2.0", "subnet"), ("192.0.2.1", "gateway"), ("192.0.2.2", "used"), ("192.0.2.3", "broadcast")]
    assert v["addresses"][2]["health"] == {"state": "up", "rtt": 1.0}
