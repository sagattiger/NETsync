"""IP Book learning: which addresses discovery reports for a device, and that values a person set always win."""

from types import SimpleNamespace as NS

from netsync.plugins.builtin.ipbook import learn


def test_addresses_of_device():
    dev = NS(ip="10.0.0.5")
    ports = [("eth1", "bc:24:11:00:00:02", ["10.0.1.5/24"]), ("eth0", "bc:24:11:00:00:01", ["10.0.0.5/24"]),
             ("lo", None, ["127.0.0.1/8"]), ("docker0", "02:42:00:00:00:01", ["172.17.0.1/16"])]
    assert learn.addresses_of(dev, ports) == {
        "172.17.0.1": ("docker0", "02:42:00:00:00:01"), "10.0.0.5": ("eth0", "bc:24:11:00:00:01"),
        "10.0.1.5": ("eth1", "bc:24:11:00:00:02")}
    assert learn.addresses_of(NS(ip="10.0.9.9"), []) == {"10.0.9.9": (None, None)}


def test_manual_wins():
    new, conflicts = learn.merge_learned({"addr_hostname": "mine", "addr_mac": "old"}, {"addr_hostname"},
                                         {"addr_hostname": "app01.example.test", "addr_mac": "new"}, False)
    assert new == {"addr_hostname": "mine", "addr_mac": "new"} and conflicts == {}


def test_learned_key_that_disappears_is_removed_unless_manual():
    new, _ = learn.merge_learned({"addr_interface": "eth0", "addr_info": "x"}, {"addr_info"}, {"addr_hostname": "a"},
                                 False, previous={"addr_interface": "eth0", "addr_info": "y"})
    assert new == {"addr_info": "x", "addr_hostname": "a"}


def test_conflict_only_after_import():
    _, none = learn.merge_learned({"ip_lan": "10.0.1.99"}, {"ip_lan"}, {"ip_lan": "10.0.1.5"}, False)
    _, some = learn.merge_learned({"ip_lan": "10.0.1.99"}, {"ip_lan"}, {"ip_lan": "10.0.1.5"}, True)
    assert none == {} and some == {"ip_lan": {"manual": "10.0.1.99", "discovered": "10.0.1.5"}}
