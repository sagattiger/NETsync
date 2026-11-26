"""IP Book values: column types, editing with secrets, what each role sees, search (invented data only)."""

import json
from types import SimpleNamespace as NS

import pytest

from netsync.plugins.builtin.ipbook import values
from netsync.plugins.builtin.ipbook.columns import BUILTIN

COLS = [*BUILTIN, {"key": "c_oob", "label": "OOB IP", "type": "ip"},
        {"key": "c_tier", "label": "Tier", "type": "choice", "options": ["gold", "silver"]},
        {"key": "c_token", "label": "API token", "type": "secret"}]
BY = {c["key"]: c for c in COLS}
KEY = "test-secret-key"


def clean(key, raw):
    return values.clean_value(BY[key], raw)


def test_clean_values():
    assert clean("ip_lan", " 10.0.0.5 ") == "10.0.0.5"
    assert clean("ip_lan", "10.0.0.5, 2001:db8::5") == "10.0.0.5, 2001:db8::5"
    assert clean("urls_public", "https://app01.example.test/ http://app01.example.test:8080") == [
        "https://app01.example.test/", "http://app01.example.test:8080"]
    assert clean("http_port", "8080") == 8080 and clean("vmid", "112") == 112
    assert clean("nat", "S") is True and clean("ssl", "Não") is False and clean("ha", "yes") is True
    assert clean("type", "LXC") == "LXC" and clean("c_tier", "gold") == "gold"
    assert clean("hostname", "  ") is None and clean("description", "a\nb") == "a\nb"
    assert clean("service", {"name": " Nextcloud ", "logo": "di:nextcloud"}) == {"name": "Nextcloud", "logo": "di:nextcloud"}
    for key, bad in [("ip_lan", "10.0.0.300"), ("urls_public", "javascript:alert(1)"), ("urls_public", "app01.example.test"),
                     ("http_port", "70000"), ("vmid", "abc"), ("type", "KVM"), ("nat", "maybe"),
                     ("service", {"name": "x", "logo": "javascript:alert(1)"})]:
        with pytest.raises(ValueError):
            clean(key, bad)


def test_secret_kept_when_sent_empty():
    vals, secrets, manual = values.apply_edit({"web_user": "old"}, {"web_pass": "x1"}, COLS,
                                              {"web_pass": "", "web_user": "admin"}, set())
    assert secrets == {"web_pass": "x1"} and vals == {"web_user": "admin"} and manual == {"web_user"}


def test_secret_cleared_with_none_and_replaced():
    _, secrets, manual = values.apply_edit({}, {"web_pass": "x1", "db_pass": "d1"}, COLS,
                                           {"web_pass": None, "db_pass": "d2"}, set())
    assert secrets == {"db_pass": "d2"} and manual == {"web_pass", "db_pass"}


def test_edit_rejects_unknown_columns_and_bad_values():
    with pytest.raises(ValueError):
        values.apply_edit({}, {}, COLS, {"nope": "x"}, set())
    with pytest.raises(ValueError, match="https port"):
        values.apply_edit({}, {}, COLS, {"https_port": "0"}, set())


def row(sensitive=False):
    return NS(id=5, values={"hostname": "app01.example.test", "ip_lan": "10.0.0.5", "c_tier": "gold"},
              secrets_enc=values.seal({"web_pass": "hunter2-x", "c_token": "tok-123456"}, KEY), sensitive=sensitive,
              source="manual", alert_when_down=None, runs_on_id=None, device_id=None, conflicts={},
              missing_since=None, manual_keys=["hostname"])


def test_non_admin_never_sees_sensitive_or_secrets():
    assert values.public_row(row(sensitive=True), COLS, is_admin=False, secret_key=KEY) is None
    viewer = values.public_row(row(), COLS, is_admin=False, secret_key=KEY)
    admin = values.public_row(row(sensitive=True), COLS, is_admin=True, secret_key=KEY)
    for view in (viewer, admin):
        dumped = json.dumps(view)
        assert "hunter2-x" not in dumped and "tok-123456" not in dumped
    assert admin["secrets"] == {"web_pass": {"set": True}, "c_token": {"set": True}, "os_pass": {"set": False},
                                "db_pass": {"set": False}, "enable_secret": {"set": False}}
    assert viewer["secrets"]["web_pass"] == {"set": True} and viewer["values"]["hostname"] == "app01.example.test"


def test_reveal_returns_one_secret():
    assert values.reveal(row(), "web_pass", KEY) == "hunter2-x"
    assert values.reveal(row(), "os_pass", KEY) is None


def test_search():
    r = values.public_row(row(), COLS, is_admin=True, secret_key=KEY)
    ips = {"ip_mgmt", "ip_wan", "ip_lan", "c_oob", "other_ips"}
    assert values.search_matches(r, "APP01", ips)
    assert values.search_matches(r, "10.0.0.", ips) and values.search_matches(r, "10.0.0.0/24", ips)
    assert values.search_matches(r, "gold", ips)
    assert not values.search_matches(r, "10.0.1.0/24", ips)
    assert not values.search_matches(r, "hunter2", ips)
