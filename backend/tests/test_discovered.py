"""Settings → Discovery "pick what to ignore": grouping what was found, and rules that really match it."""

from types import SimpleNamespace as C

from netsync.discovered import digit_pattern, exact_rule, pattern_rule, port_prefix, summarize
from netsync.general import DEFAULTS, ignored, regex


def comp(kind, name, device_id=1, **attrs):
    return C(kind=kind, name=name, descr=None, attrs=attrs, device_id=device_id)


def test_port_prefixes():
    assert port_prefix("veth101i0") == "veth" and port_prefix("vethea12f") == "veth"
    assert port_prefix("br-3f2a9c") == "br-" and port_prefix("tap104i0") == "tap"
    assert port_prefix("fwln101i0") == "fwln" and port_prefix("vmbr0") == "vmbr"
    assert port_prefix("Gi0/1") == "Gi" and port_prefix("lo") is None and port_prefix("BRD-SRV") is None


def test_rules_match_what_they_describe():
    assert regex(pattern_rule(digit_pattern("CPU 12"))).search("CPU 3")
    assert not regex(pattern_rule(digit_pattern("CPU 12"))).search("CPU Package")
    assert regex(exact_rule("/mnt/pve/usb01-nfs")).search("/mnt/pve/usb01-nfs")
    assert not regex(exact_rule("eth0")).search("eth01")


def test_summarize_groups_and_marks_ignored():
    rows = [comp("port", "veth101i0", 1, if_type=6), comp("port", "veth102i0", 2, if_type=6),
            comp("port", "eth0", 1, if_type=6), comp("port", "vlan10", 1, if_type=135),
            comp("storage", "/tmp", 1), comp("storage", "/", 1), comp("processor", "CPU 0", 1), comp("processor", "CPU 1", 1),
            comp("sensor", "Core 0", 1)]
    cfg = {**DEFAULTS, "ports_ignore_regex": "/^veth/"}
    out = summarize(rows, cfg, {1: "pve001", 2: "pve002"})
    pats = {g["key"]: g for g in out["port"]["patterns"]}
    assert pats["veth"]["count"] == 2 and pats["veth"]["device_count"] == 2 and pats["veth"]["all_ignored"]
    assert pats["veth"]["rule"] == "/^veth/" and pats["veth"]["field"] == "ports_ignore_regex"
    assert pats["veth"]["device_names"] == ["pve001", "pve002"] and "LXC" in pats["veth"]["hint"]
    assert not pats["eth"]["all_ignored"]
    types = {g["key"]: g for g in out["port"]["types"]}
    assert types["ethernetCsmacd"]["count"] == 3 and types["l2vlan"]["rule"] == "l2vlan"
    assert {g["label"] for g in out["processor"]["patterns"]} == {"CPU N"}
    assert out["sensor"]["patterns"] == []  # one sensor: no pattern worth offering
    names = {g["key"]: g for g in out["storage"]["names"]}
    assert names["/tmp"]["field"] == "storage_ignore_exact" and names["/tmp"]["rule"] == "/tmp"
    # the rule the picker adds really ignores the component
    cfg2 = {**DEFAULTS, "storage_ignore_exact": "/tmp", "processor_ignore_regex": pattern_rule("CPU #")}
    assert ignored(rows[4], cfg2) and not ignored(rows[5], cfg2) and ignored(rows[6], cfg2)


class FakeSession:
    def __init__(self, rows):
        self.rows, self.executed, self.committed = rows, [], False

    async def scalars(self, _q):
        return [r for r in self.rows if not r.deleted]

    async def execute(self, q):
        self.executed.append(q)

    async def commit(self):
        self.committed = True


def test_saving_rules_removes_what_they_ignore_right_away():
    import asyncio

    from netsync.general import remove_ignored

    rows = [comp("port", "veth101i0"), comp("port", "eth0"), comp("storage", "/tmp")]
    for i, r in enumerate(rows):
        r.id, r.deleted = i + 1, False
    s = FakeSession(rows)
    note = asyncio.run(remove_ignored(s, {**DEFAULTS, "ports_ignore_regex": "/^veth/", "storage_ignore_exact": "/tmp"}))
    assert [r.deleted for r in rows] == [True, False, True] and s.committed and len(s.executed) == 1
    assert note == "Removed 2 ignored entities now."
    assert asyncio.run(remove_ignored(FakeSession([rows[1]]), DEFAULTS)) is None
