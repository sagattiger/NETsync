from types import SimpleNamespace

from netsync.plugins.builtin.system import device_addresses


class FakeSnmp:
    def __init__(self, host, table):
        self.host, self.table = host, table

    async def walk(self, oid):
        return self.table


async def test_collects_interface_addresses_and_polled_ip():
    snmp = FakeSnmp("10.128.100.201", {"10.128.100.254": "10.128.100.254", "127.0.0.1": "127.0.0.1",
                                        "192.168.88.1": "192.168.88.1"})
    addrs = await device_addresses(SimpleNamespace(snmp=snmp))
    assert addrs == ["10.128.100.201", "10.128.100.254", "192.168.88.1"]


async def test_survives_missing_ip_mib():
    class NoMib(FakeSnmp):
        async def walk(self, oid):
            raise RuntimeError("timeout")

    assert await device_addresses(SimpleNamespace(snmp=NoMib("10.0.0.1", {}))) == ["10.0.0.1"]
