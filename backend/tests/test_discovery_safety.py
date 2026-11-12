"""Discovery must not wipe components on one short answer (e.g. snmpd just restarted)."""

from datetime import UTC, datetime
from types import SimpleNamespace

from netsync.plugins.base import DeviceContext
from netsync.plugins.builtin.host_resources import (
    HR_DEVICE_DESCR,
    HR_DEVICE_PROCESSOR,
    HR_DEVICE_TYPE,
    HR_PROCESSOR_LOAD,
    HostResourcesModule,
)
from netsync.poller.pipeline import count_miss


class FakeSnmp:
    def __init__(self, walks):
        self.walks = walks

    async def walk(self, oid):
        return self.walks.get(oid, {})

    async def table(self, cols):
        return {}


async def test_processors_found_while_load_table_is_still_empty():
    walks = {
        HR_PROCESSOR_LOAD: {},  # net-snmp right after a restart
        HR_DEVICE_TYPE: {"196608": HR_DEVICE_PROCESSOR, "196609": HR_DEVICE_PROCESSOR, "262145": "1.3.6.1.2.1.25.3.1.4"},
        HR_DEVICE_DESCR: {"196608": b"GenuineIntel: Intel(R) Xeon(R) CPU E5-2697 v2 @ 2.70GHz",
                          "196609": b"GenuineIntel: Intel(R) Xeon(R) CPU E5-2697 v2 @ 2.70GHz",
                          "262145": b"network interface lo"},
    }
    ctx = DeviceContext(SimpleNamespace(), FakeSnmp(walks), [], datetime.now(UTC))
    specs = [s for s in await HostResourcesModule().discover(ctx) if s.kind == "processor"]
    assert [(s.index, s.name, s.descr) for s in specs] == [
        ("196608", "CPU 0", "Intel Xeon E5-2697 v2 @ 2.70GHz"), ("196609", "CPU 1", "Intel Xeon E5-2697 v2 @ 2.70GHz")]


async def test_load_table_still_works_without_device_table():
    ctx = DeviceContext(SimpleNamespace(), FakeSnmp({HR_PROCESSOR_LOAD: {"1": 5, "2": 7}}), [], datetime.now(UTC))
    assert [s.index for s in await HostResourcesModule().discover(ctx) if s.kind == "processor"] == ["1", "2"]


def test_component_removed_only_after_two_misses():
    comp = SimpleNamespace(attrs={"model": "x"})
    assert count_miss(comp) is False and comp.attrs == {"model": "x", "missing": 1}
    assert count_miss(comp) is True
