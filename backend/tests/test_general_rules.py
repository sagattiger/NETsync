"""Settings → General: discovery ignore rules, IP address types, autodiscovery blocks."""

import pytest

from netsync.general import (
    DEFAULTS, blocked_hostname, blocked_platform, ignored, ip_type, keep_address, regex, validate, with_domain,
)
from netsync.plugins.base import ComponentSpec


def port(name, descr="", alias=None, if_type=6):
    return ComponentSpec("port", "1", name, descr=alias, attrs={"if_descr": descr, "if_type": if_type})


def test_regex_with_slashes_and_flags():
    assert regex("/^ng[0-9]+$/i").search("NG12")
    assert not regex("/^lp0/").search("LP0")
    assert regex("^bare$").search("bare")


@pytest.mark.parametrize("name,descr,alias,if_type,ignore", [
    ("ng3", "", None, 6, True),                        # regex, case-insensitive
    ("eth0", "eth0", None, 6, False),
    ("ovs-system", "ovs-system", None, 6, True),       # contains
    ("Gi0/1", "GigabitEthernet0/1", "Transit: ISP", 6, False),
    ("Vo0", "Voice", None, 103, True),                 # ifType voiceEncap
    ("x", "<invalid>", None, 6, True),                 # regex on ifDescr
])
def test_port_rules(name, descr, alias, if_type, ignore):
    assert ignored(port(name, descr, alias, if_type), DEFAULTS) is ignore


def test_port_alias_regex():
    cfg = {**DEFAULTS, "ports_ignore_alias_regex": "/^Transit:/"}
    assert ignored(port("Gi0/1", alias="Transit: ISP"), cfg)
    assert not ignored(port("Gi0/2", alias="Uplink"), cfg)


def test_storage_rules():
    def st(name, kind="fixed"):
        return ComponentSpec("storage", "1", name, attrs={"storage_type": kind})

    assert ignored(st("/run"), DEFAULTS)                       # exact
    assert not ignored(st("/run/user/1000"), DEFAULTS)         # exact means exact
    assert ignored(st("/var/procfs-x"), DEFAULTS)              # contains
    assert ignored(st("/media/usb", "removable"), DEFAULTS)
    assert ignored(st("/mnt/dvd", "optical"), DEFAULTS)
    assert not ignored(st("/mnt/nfs", "network"), DEFAULTS)
    assert ignored(st("/mnt/nfs", "network"), {**DEFAULTS, "storage_ignore_network": True})
    assert ignored(st("/backup"), {**DEFAULTS, "storage_ignore_regex": "/^\\/back/"})


def test_processor_and_sensor_rules():
    cpu = ComponentSpec("processor", "1", "CPU 0", descr="Cached Processor")
    assert not ignored(cpu, DEFAULTS)
    assert ignored(cpu, {**DEFAULTS, "processor_ignore_exact": "Cached Processor"})
    assert ignored(cpu, {**DEFAULTS, "processor_ignore_string": "cache"})
    assert ignored(ComponentSpec("sensor", "1", "C6K Clock FRU 2"), DEFAULTS)
    assert not ignored(ComponentSpec("sensor", "1", "Core 0"), DEFAULTS)
    assert ignored(ComponentSpec("sensor", "1", "Outside Temperature"), {**DEFAULTS, "sensor_ignore_string": "outside"})


@pytest.mark.parametrize("addr,kind", [
    ("0.0.0.0", "unspecified"), ("127.0.0.1/8", "loopback"), ("::1", "loopback"), ("10.1.2.3/24", "private"),
    ("100.64.1.1", "cgnat"), ("169.254.1.1", "link-local"), ("fe80::1/64", "link-local"), ("224.0.0.5", "multicast"),
    ("192.0.2.10", "documentation"), ("2001:db8::1", "documentation"), ("198.18.0.1", "benchmarking"),
    ("::ffff:10.0.0.1", "ipv4-mapped"), ("64:ff9b::a00:1", "ipv4-embedded"), ("2002:c000:204::1", "6to4"),
    ("2001:0:4136::1", "teredo"), ("8.8.8.255/24", "broadcast"), ("8.8.8.8/24", "global"),
    ("2606:4700::/64", "anycast"), ("2606:4700::1111", "global"), ("240.0.0.1", "reserved"), ("fd00::1", "private"),
])
def test_ip_types(addr, kind):
    assert ip_type(addr) == kind


def test_keep_address_uses_the_ignore_list():
    assert not keep_address("fe80::1/64", DEFAULTS)
    assert keep_address("10.0.0.1/24", DEFAULTS)
    assert not keep_address("10.0.0.1/24", {**DEFAULTS, "ip_ignore_types": ["private"]})


def test_autodiscovery_blocks_and_domain():
    assert blocked_platform("Cisco IP Phone CP-7945G", DEFAULTS)
    assert blocked_platform("Not received", DEFAULTS)
    assert not blocked_platform("Linux pve001 6.8.12", DEFAULTS)
    cfg = {**DEFAULTS, "autodiscovery_block_hostname": "BadHost.example.com", "autodiscovery_block_hostname_regex": "/^lab-/"}
    assert blocked_hostname("badhost.example.com", cfg) and blocked_hostname("lab-sw1", cfg)
    assert not blocked_hostname("core-sw1", cfg)
    cfg = {**DEFAULTS, "autodiscovery_domain": "example.com"}
    assert with_domain("sw01", cfg) == "sw01.example.com"
    assert with_domain("sw01.lan", cfg) == "sw01.lan"
    assert with_domain("10.0.0.1", cfg) == "10.0.0.1"


def test_validate_rejects_bad_regex_and_domain():
    validate({**DEFAULTS})
    for bad in ({"ports_ignore_regex": "/([a-/"}, {"autodiscovery_domain": "bad domain"}, {"public_url": "netsync.lan"}):
        with pytest.raises(ValueError):
            validate({**DEFAULTS, **bad})
    validate({**DEFAULTS, "public_url": "https://netsync.example.com", "autodiscovery_networks": "10.128.0.0/20"})


def test_multi_field_coercion():
    from netsync.general import plugin
    from netsync.plugins.settings import coerce

    out = coerce(plugin, {"ip_ignore_types": ["loopback", "private"]}, {})
    assert out["ip_ignore_types"] == ["loopback", "private"]
    with pytest.raises(ValueError):
        coerce(plugin, {"ip_ignore_types": ["nope"]}, {})
    assert coerce(plugin, {"snmp_timeout": "2.5"}, {})["snmp_timeout"] == 2.5


def test_branding_logo_for_each_theme():
    png = "data:image/png;base64,iVBORw0KGgo="
    assert DEFAULTS["logo_dark"] == ""
    validate({**DEFAULTS, "logo": png, "logo_dark": png})
    for bad in ("https://example.com/logo.png", "data:text/html;base64,PGI+", "data:image/png;base64," + "A" * 400_000):
        with pytest.raises(ValueError, match=r"Logo \(dark theme\)"):
            validate({**DEFAULTS, "logo_dark": bad})
