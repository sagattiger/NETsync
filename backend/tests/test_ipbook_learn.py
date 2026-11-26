"""IP Book learning: what discovery puts in a learned row, and that values a person set always win."""

from types import SimpleNamespace as NS

from netsync.plugins.builtin.ipbook import learn


def device(**kw):
    base = {"id": 7, "hostname": "app01.example.test", "app_name": None, "app_logo": None, "virtualization": None, "guest_id": None,
                "os": "linux", "ip": "10.0.0.5", "app_url": None, "app_port": None}
    return NS(**{**base, **kw})


def test_learned_values_lxc():
    dev = device(app_name="Nextcloud", app_logo="di:nextcloud", virtualization="lxc", guest_id=112,
                 app_url="https://cloud.example.test/", app_port=443)
    hyp = NS(id=3, hostname="pve01.example.test")
    v = learn.learned_values(dev, hyp, ["10.0.0.5/24", "10.0.1.5/24", "10.0.2.5/24"])
    assert v["hostname"] == "app01.example.test" and v["type"] == "LXC" and v["vmid"] == 112
    assert v["service"] == {"name": "Nextcloud", "logo": "di:nextcloud"}
    assert v["hypervisor"] == {"id": 3, "name": "pve01.example.test"}
    assert v["ip_mgmt"] == "10.0.0.5" and v["ip_lan"] == "10.0.1.5" and v["other_ips"] == ["10.0.2.5"]
    assert v["urls_internal"] == ["https://cloud.example.test/"] and v["https_port"] == 443 and "http_port" not in v
    assert v["os"] == "linux"


def test_learned_values_plain_device():
    v = learn.learned_values(device(virtualization="vm", app_url="http://app01.example.test:8080", app_port=8080), None, [])
    assert v["type"] == "VM" and v["http_port"] == 8080 and "hypervisor" not in v and "ip_lan" not in v
    assert "service" not in v and "other_ips" not in v
    assert learn.learned_values(device(), None, ["10.0.0.5/24"])["type"] == "Device"


def test_manual_wins():
    new, conflicts = learn.merge_learned({"ip_lan": "10.0.1.99", "hostname": "old"}, {"ip_lan"},
                                         {"ip_lan": "10.0.1.5", "hostname": "app01.example.test", "vmid": 112}, False)
    assert new == {"ip_lan": "10.0.1.99", "hostname": "app01.example.test", "vmid": 112} and conflicts == {}


def test_learned_key_that_disappears_is_removed_unless_manual():
    new, _ = learn.merge_learned({"vmid": 112, "ip_lan": "10.0.1.99"}, {"ip_lan"}, {"hostname": "a"}, False,
                                 previous={"vmid": 112, "ip_lan": "10.0.1.5"})
    assert new == {"ip_lan": "10.0.1.99", "hostname": "a"}


def test_conflict_only_after_import():
    _, none = learn.merge_learned({"ip_lan": "10.0.1.99"}, {"ip_lan"}, {"ip_lan": "10.0.1.5"}, False)
    _, some = learn.merge_learned({"ip_lan": "10.0.1.99"}, {"ip_lan"}, {"ip_lan": "10.0.1.5"}, True)
    assert none == {} and some == {"ip_lan": {"manual": "10.0.1.99", "discovered": "10.0.1.5"}}
    _, same = learn.merge_learned({"ip_lan": "10.0.1.5"}, {"ip_lan"}, {"ip_lan": "10.0.1.5"}, True)
    assert same == {}
