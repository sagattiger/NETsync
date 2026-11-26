"""IP Book: the built-in columns are exactly the spec's list, and its virtual device stays out of polling."""

from netsync.models import VIRTUAL_DEVICE_TYPES
from netsync.plugins.builtin.ipbook import columns

SPEC_KEYS = [
    "service", "hypervisor", "type", "os", "vmid", "ha", "hostname", "ip_mgmt", "ip_wan", "nat", "ip_lan",
    "fqdn_internal", "fqdn_public", "urls_public", "ssl", "urls_internal", "http_port", "https_port", "web_user",
    "web_pass", "os_user", "os_pass", "db_pass", "enable_secret", "aaa", "telnet_port", "ssh_port", "winbox",
    "description",
]


def test_builtin_columns_match_spec():
    by_key = {c["key"]: c for c in columns.BUILTIN}
    assert [c["key"] for c in columns.BUILTIN] == SPEC_KEYS
    assert len(by_key) == len(SPEC_KEYS)
    assert {k for k, c in by_key.items() if c["type"] == "secret"} == {"web_pass", "os_pass", "db_pass", "enable_secret"}
    assert {k for k, c in by_key.items() if c["type"] == "ip"} == {"ip_mgmt", "ip_wan", "ip_lan"}
    assert by_key["type"]["type"] == "choice" and by_key["type"]["options"] == ["Device", "VM", "LXC", "Docker"]
    assert all(c["type"] in columns.TYPES for c in columns.BUILTIN)
    assert [c["position"] for c in columns.BUILTIN] == list(range(len(SPEC_KEYS)))


def test_ip_keys_include_custom_ip_columns():
    cols = [*columns.BUILTIN, {"key": "c_oob", "type": "ip"}, {"key": "c_note", "type": "text"}]
    assert columns.ip_keys(cols) == {"ip_mgmt", "ip_wan", "ip_lan", "c_oob", "other_ips"}
    assert columns.secret_keys(cols) == {"web_pass", "os_pass", "db_pass", "enable_secret"}


def test_ipbook_is_virtual():
    assert "ipbook" in VIRTUAL_DEVICE_TYPES
