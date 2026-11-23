"""Proxmox host <- guest links from the host's SNMP process table (samples from real Proxmox VE 9 hosts)."""

import pytest
from pydantic import ValidationError

from netsync.api.schemas import DeviceUpdate
from netsync.plugins.builtin.proxmox import match_host, parse_guests

NAMES = {"1": "lxc-start", "2": "kvm", "3": "kvm-pit/3449", "4": "lxc-start", "5": "dtach", "6": "kvm", "7": "lxcfs"}
PARAMS = {
    "1": "-F -n 100",
    "2": "-id 203 -name vm203-infra.example.net -no-shutdown -chardev socket,id=qmp,path=/var/run/qemu-server/203.qmp",
    "3": "", "4": "-F -n 1001",
    "5": "-A /var/run/dtach/vzctlconsole112 -r winch -z lxc-console -n 112 -e -1",
    "6": "-id 3000 -name vm3000.cloud.example.net,debug-threads=on -no-shutdown", "7": "/var/lib/lxcfs",
}


def test_parse_guests():
    assert parse_guests(NAMES, PARAMS) == [
        {"type": "lxc", "vmid": 100, "name": None},
        {"type": "qemu", "vmid": 203, "name": "vm203-infra.example.net"},
        {"type": "lxc", "vmid": 1001, "name": None},
        {"type": "qemu", "vmid": 3000, "name": "vm3000.cloud.example.net"},
    ]


GUESTS = [(4, g) for g in parse_guests(NAMES, PARAMS)] + [(37, {"type": "lxc", "vmid": 105, "name": None}),
                                                           (37, {"type": "qemu", "vmid": 206, "name": "vm206-infra.example.net"})]


def test_vm_matched_by_name():
    assert match_host(["vm203-infra.example.net", "vm203-infra"], "vm", GUESTS)[0] == 4
    assert match_host(["VM206-INFRA.example.net", None], None, GUESTS)[1]["vmid"] == 206  # VM not detected yet: by name


def test_container_matched_by_id_in_its_name():
    host, guest = match_host(["lxc100-infra.example.net", "lxc100-infra"], "lxc", GUESTS)
    assert (host, guest["vmid"]) == (4, 100)
    assert match_host(["lxc105-infra.example.net"], "lxc", GUESTS)[0] == 37
    assert match_host(["lxc1001.example.net"], "lxc", GUESTS)[1]["vmid"] == 1001  # 1001, not 100


def test_no_guess():
    assert match_host(["sw-105.example.net"], None, GUESTS) is None  # not a detected container
    assert match_host(["lxc999.example.net"], "lxc", GUESTS) is None
    twice = GUESTS + [(37, {"type": "lxc", "vmid": 100, "name": None})]
    assert match_host(["lxc100-infra"], "lxc", twice) is None  # two hosts run a CT 100: don't pick one
    assert match_host([None, ""], "lxc", GUESTS) is None


def test_device_update_fields():
    u = DeviceUpdate(app_url=" https://observium.example.net/ ", app_port=8080, location="  Rack 2,  DC  ", contact="")
    assert (u.app_url, u.app_port, u.location, u.contact) == ("https://observium.example.net/", 8080, "Rack 2, DC", None)
    for bad in ("ftp://x", "javascript:alert(1)", "https://user:pw@x.example", "https://x.example/a b"):
        with pytest.raises(ValidationError):
            DeviceUpdate(app_url=bad)
    with pytest.raises(ValidationError):
        DeviceUpdate(app_port=70000)
