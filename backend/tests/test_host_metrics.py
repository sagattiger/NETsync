"""Host metrics: UCD-SNMP-MIB memory/CPU/counters, LM-SENSORS, DISKIO, CPU model, packet stats, presets."""

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from netsync.plugins.base import DeviceContext
from netsync.plugins.builtin.diskio import WHOLE_DISK
from netsync.plugins.builtin.host_resources import cpu_model
from netsync.plugins.builtin.interfaces import packet_metrics
from netsync.plugins.builtin.sensors import physical_cores, plan_sensors
from netsync.plugins.builtin.ucd import (
    OPTANE,
    UcdModule,
    base_disk,
    counter_delta,
    cpu_shares,
    memory_bytes,
    parse_disks_extend,
    swap_summary,
)
from netsync.presets import BY_ID, PRESETS, UNITS

# --------------------------------------------------------------------------- CPU model


@pytest.mark.parametrize(("descr", "model"), [
    ("GenuineIntel: Intel(R) Xeon(R) CPU E5-2697 v2 @ 2.70GHz", "Intel Xeon E5-2697 v2 @ 2.70GHz"),
    ("AuthenticAMD: AMD Ryzen 9 5950X 16-Core Processor", "AMD Ryzen 9 5950X"),
    ("GenuineIntel: Intel(R) Core(TM) i7-8700 CPU @ 3.20GHz", "Intel Core i7-8700 @ 3.20GHz"),
    ("", None), (None, None),
])
def test_cpu_model(descr, model):
    assert cpu_model(descr) == model


# --------------------------------------------------------------------------- memory and CPU split

def test_memory_bytes_matches_free():
    # pve002 sample (KB)
    m = memory_bytes({"mem_total": 65783464, "mem_free": 41164036, "mem_buffers": 321668, "mem_cached": 8165744,
                      "mem_shared": 903360, "mem_available": 48025464, "swap_total": 22452216, "swap_avail": 22447412})
    assert m["mem_total"] == 65783464 * 1024
    assert m["mem_used"] == (65783464 - 41164036 - 321668 - 8165744) * 1024  # ~15.4 GiB, like Observium
    assert m["swap_used"] == 4804 * 1024
    assert "swap_avail" not in m


def test_memory_bytes_partial_and_never_negative():
    assert memory_bytes({"mem_total": 100, "mem_free": 90, "mem_buffers": 20, "mem_cached": 10})["mem_used"] == 0
    assert memory_bytes({"mem_total": None}) == {}


def test_counter_delta_wraps_once():
    assert counter_delta(10, 5) == 5
    assert counter_delta(5, 2**32 - 5) == 10  # 32-bit wrap
    assert counter_delta(5, 2**30) is None  # a wrap would mean 3/4 of the range in one poll: a reset


def test_cpu_shares():
    prev = {"cpu_user": 100, "cpu_system": 100, "cpu_idle": 700, "cpu_wait": 0, "cpu_guest": 0}
    cur = {"cpu_user": 130, "cpu_system": 110, "cpu_idle": 760, "cpu_wait": 0, "cpu_guest": 20}
    s = cpu_shares(cur, prev)
    assert s["cpu_user"] == pytest.approx(30.0) and s["cpu_system"] == pytest.approx(10.0)
    assert s["cpu_idle"] == pytest.approx(60.0)
    assert s["cpu_guest"] == pytest.approx(20.0)  # shown, but not part of the 100 %
    assert cpu_shares(cur, cur) == {}


# --------------------------------------------------------------------------- disks, swap, Optane

EXTEND = """sda      Samsung SSD 860 EVO 500GB 465.8G
nvme0n1  INTEL MEMPEK1W016GA       13.4G
nvme1n1  INTEL SSDPEK1A118GA      109.8G
sdb                                 1.8T
---
Filename				Type		Size		Used		Priority
/dev/nvme1n1p1                          partition	22452216	4808		-2
/dev/dm-1                               partition	8388604	0		-3
"""


def test_parse_disks_extend_and_optane():
    disks, swaps = parse_disks_extend(EXTEND)
    assert disks["sda"] == {"model": "Samsung SSD 860 EVO 500GB", "size": "465.8G"}
    assert disks["sdb"] == {"model": None, "size": "1.8T"}
    summary = swap_summary(disks, swaps)
    assert summary[0] == {"device": "/dev/nvme1n1p1", "disk": "nvme1n1", "kind": "partition", "size_kb": 22452216,
                          "used_kb": 4808, "model": "INTEL SSDPEK1A118GA", "optane": True}
    assert summary[1]["disk"] == "dm-1" and summary[1]["optane"] is False and summary[1]["model"] is None
    assert parse_disks_extend("") == ({}, [])


@pytest.mark.parametrize("model", ["INTEL MEMPEK1W016GA", "INTEL MEMPEK1J032GA", "INTEL SSDPED1D280GA",
                                   "INTEL SSDPE21D960GA", "INTEL SSDPEK1A058GA", "Intel Optane SSD 900P"])
def test_optane_models(model):
    assert OPTANE.search(model)


@pytest.mark.parametrize("model", ["INTEL SSDPEKNW010T8", "Samsung SSD 970 EVO Plus 1TB", "WDC WD20EFRX-68EUZN0"])
def test_not_optane(model):
    assert not OPTANE.search(model)


def test_base_disk_and_whole_disks():
    assert [base_disk(d) for d in ("/dev/nvme0n1p1", "/dev/sda2", "/dev/vdb1", "/dev/mmcblk0p2", "/dev/dm-0")] == \
        ["nvme0n1", "sda", "vdb", "mmcblk0", "dm-0"]
    names = ["loop0", "sda", "sda1", "nvme0n1", "nvme0n1p1", "dm-3", "sdc", "vda", "mmcblk0"]
    assert [n for n in names if WHOLE_DISK.match(n)] == ["sda", "nvme0n1", "sdc", "vda", "mmcblk0"]


# --------------------------------------------------------------------------- sensors

def test_sensor_duplicates_and_groups():
    names = {"16": "Processor Fan", "17": "Other Fan", "18": "dell_smm-isa-00de:Other Fan"}
    assert [n for _, n, _ in plan_sensors("fan", names)] == ["Processor Fan", "Other Fan"]
    temps = {"1": "Package id 0", "2": "Core 0", "3": "Core 1", "14": "Composite", "26": "dell_smm-isa-00de:CPU",
             "25": "CPU"}
    planned = plan_sensors("temperature", temps)
    assert ("1", "Package id 0", "Processor") in planned and ("14", "Composite", "Board") in planned
    assert all(n != "dell_smm-isa-00de:CPU" for _, n, _ in planned)
    assert physical_cores(list(temps.values())) == 2


# --------------------------------------------------------------------------- ports

def test_packet_metrics():
    m = packet_metrics({"in_ucast": 100.0, "in_mcast": 5.0, "in_bcast": 5.0, "in_octets": 110_000.0,
                        "out_ucast": 50.0})
    assert m == {"in_ucast_pps": 100.0, "in_nucast_pps": 10.0, "in_pkt_size": 1000.0,
                 "out_ucast_pps": 50.0, "out_nucast_pps": 0.0}
    assert packet_metrics({}) == {}


# --------------------------------------------------------------------------- UCD poll end to end (fake agent)

class FakeSnmp:
    def __init__(self, values):
        self.values = values

    async def get(self, *oids):
        return {o: self.values.get(o) for o in oids}


@pytest.mark.asyncio
async def test_ucd_poll_rates_and_shares():
    base = {
        "1.3.6.1.4.1.2021.4.20.0": 1000, "1.3.6.1.4.1.2021.4.21.0": 400, "1.3.6.1.4.1.2021.4.25.0": 100,
        "1.3.6.1.4.1.2021.4.26.0": 200, "1.3.6.1.4.1.2021.4.18.0": 50, "1.3.6.1.4.1.2021.4.19.0": 40,
        "1.3.6.1.4.1.2021.10.1.3.1": b"0.63", "1.3.6.1.4.1.2021.10.1.3.2": b"0.42", "1.3.6.1.4.1.2021.10.1.3.3": b"0.38",
        "1.3.6.1.4.1.2021.11.50.0": 100, "1.3.6.1.4.1.2021.11.53.0": 900, "1.3.6.1.4.1.2021.11.60.0": 1000,
        "1.3.6.1.2.1.25.1.6.0": 620, "1.3.6.1.2.1.25.1.5.0": 0,
    }
    comp = SimpleNamespace(kind="system_stats", index="0", enabled=True, deleted=False,
                           values={"ts": 1000.0, "raw": {"cpu_user": 50, "cpu_idle": 850, "ctx_switches": 400}})
    ctx = DeviceContext(SimpleNamespace(), FakeSnmp(base), [comp], datetime.fromtimestamp(1060, UTC))
    res = await UcdModule().poll(ctx)
    m = {s.name: s.value for s in res.metrics}
    assert m["mem_total"] == 1000 * 1024 and m["mem_used"] == 300 * 1024 and m["swap_used"] == 10 * 1024
    assert m["load1"] == 0.63 and m["processes"] == 620 and m["users"] == 0
    assert m["cpu_user"] == pytest.approx(50.0) and m["cpu_idle"] == pytest.approx(50.0)
    assert m["ctx_switches"] == pytest.approx(10.0)  # 600 switches in 60 s
    assert res.values[("system_stats", "0")]["raw"]["cpu_user"] == 100


# --------------------------------------------------------------------------- presets

def test_new_presets_are_consistent():
    for p in PRESETS:
        assert p.unit in UNITS
        assert p.ruler is None or p.unit in ("bytes", "load", "pct")
    assert BY_ID["mem_detail"].stack and BY_ID["mem_detail"].ruler == "mem_total"
    assert BY_ID["load"].ruler == "cpu_count"
    assert BY_ID["temperature"].kind == "sensor" and BY_ID["disk_io"].kind == "disk"
    assert {"stack", "ruler"} <= BY_ID["cpu"].as_dict().keys()
