from datetime import UTC, datetime

from netsync.plugins.base import DeviceContext
from netsync.plugins.builtin.host_resources import (
    TYPE_FIXED_DISK,
    TYPE_RAM,
    HostResourcesModule,
)


class FakeSnmp:
    def __init__(self, storage: dict):
        self.storage = storage

    async def walk(self, oid):
        return {}  # no processors

    async def table(self, columns):
        return self.storage


async def test_bind_mounts_are_skipped():
    snmp = FakeSnmp({
        "1": {"type": TYPE_RAM, "descr": b"Physical memory", "units": 1024, "size": 8000, "used": 2000},
        "36": {"type": TYPE_FIXED_DISK, "descr": b"/", "units": 4096, "size": 7000, "used": 1200},
        "50": {"type": TYPE_FIXED_DISK, "descr": b"/srv/jail/a/home/a", "units": 4096, "size": 7000, "used": 1200},
        "53": {"type": TYPE_FIXED_DISK, "descr": b"/boot", "units": 4096, "size": 220, "used": 30},
        "60": {"type": TYPE_FIXED_DISK, "descr": b"/run/user/1000", "units": 4096, "size": 100, "used": 1},
    })
    ctx = DeviceContext(device=None, snmp=snmp, components=[], now=datetime.now(UTC))
    specs = await HostResourcesModule().discover(ctx)
    names = {(s.kind, s.name) for s in specs}
    assert names == {("mempool", "Memory"), ("storage", "/"), ("storage", "/boot")}
