"""UI kit widgets (kpi, gauge, rings, donut, bars) and the graph style: model validation and public payloads."""

import json
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from netsync.api.dashboards import Widget, dump_widget
from netsync.api.public import build_payload, dashboard_devices, probe_ids, spark, threshold_state
from netsync.models import State

NOW = datetime.now(UTC)
SECRETS = ("edge.internal", "10.0.0.", "dns.google", "8.8.4.4", "secret output", "pve-host.lan")


def W(**kw):
    return Widget(**{"id": "x", "title": "", "size": "m", "device_id": None, "component_id": None, "preset": None, **kw})


# --------------------------------------------------------------------------- model

def test_new_widget_types_validate_and_store_only_set_fields():
    k = dump_widget(W(type="kpi", device_id=1, preset="cpu", caption="CPU now"))
    assert k["type"] == "kpi" and k["caption"] == "CPU now" and "min" not in k and "items" not in k
    g = dump_widget(W(type="gauge", device_id=1, preset="cpu", min=0, max=100, warn=80, crit=90))
    assert g["min"] == 0 and g["max"] == 100 and g["warn"] == 80  # 0 is kept, not dropped as "unset"
    r = dump_widget(W(type="rings", items=[{"preset": "cpu", "device_id": 1, "label": "  pve  001 "}]))
    assert r["items"] == [{"label": "pve 001", "device_id": 1, "preset": "cpu"}]
    d = dump_widget(W(type="donut", count="problems"))
    assert d["count"] == "problems"
    b = dump_widget(W(type="bars", device_id=1, preset="port_traffic", metric="in", limit=3))
    assert b["limit"] == 3 and b["metric"] == "in"
    assert dump_widget(W(type="graph", device_id=1, preset="cpu", style="spike"))["style"] == "spike"


@pytest.mark.parametrize("bad", [
    {"type": "gauge", "min": 10, "max": 10},
    {"type": "gauge", "max": -1},
    {"type": "rings"},
    {"type": "rings", "items": [{"preset": "cpu"}] * 5},
    {"type": "rings", "items": [{"preset": "cpu", "color": "red"}]},
    {"type": "bars", "limit": 0},
    {"type": "bars", "limit": 11},
    {"type": "bars", "probe_ids": list(range(11))},
    {"type": "graph", "style": "neon"},
    {"type": "kpi", "stat": "median"},
    {"type": "kpi", "window": "1y"},
    {"type": "kpi", "caption": "x" * 65},
    {"type": "donut", "count": "devices"},
    {"type": "pie"},
])
def test_new_widget_fields_rejected(bad):
    with pytest.raises(ValidationError):
        W(**bad)


def test_thresholds_and_spark():
    assert threshold_state(None, 80, 90) == "UNKNOWN"
    assert [threshold_state(v, 80, 90) for v in (10, 80, 95)] == ["OK", "WARN", "CRIT"]
    assert [threshold_state(v, 99.9, 99) for v in (100, 99.5, 98)] == ["OK", "WARN", "CRIT"]  # lower is worse
    assert threshold_state(50, None, None) == "OK"
    pts = [["t", float(i), 0, 0] for i in range(100)] + [["t", None, None, None]]
    s = spark(pts, 24)
    assert len(s) == 24 and s[0] == 0.0 and s[-1] == 99.0
    assert spark([["t", 1.23456, 0, 0]]) == [1.235]


# --------------------------------------------------------------------------- payload

def svc(id, device_id, name, state, component_id=None):
    return SimpleNamespace(id=id, device_id=device_id, name=name, state=state, output="secret output",
                           component_id=component_id, acknowledged=False, last_change=NOW, perf={})


@pytest.fixture
def kit():
    devices = {1: SimpleNamespace(id=1, hostname="edge.internal", ip="10.0.0.1", status=State.OK, uptime=1,
                                  device_type="router"),
               2: SimpleNamespace(id=2, hostname="pve-host.lan", ip="10.0.0.2", status=State.OK, uptime=1,
                                  device_type="server")}
    probes = {5: SimpleNamespace(id=5, device_id=50, name="Google", target="dns.google", kind="icmp"),
              6: SimpleNamespace(id=6, device_id=60, name="8.8.4.4", target="8.8.4.4", kind="icmp")}
    services = [
        svc(1, 1, "CPU utilization", State.OK), svc(2, 1, "Interface ether1", State.WARN, component_id=10),
        svc(3, 2, "Memory", State.CRIT), svc(4, 50, "Ping RTT", State.OK), svc(5, 60, "Ping RTT", State.UNKNOWN),
    ]
    components = {10: SimpleNamespace(id=10, device_id=1, kind="port", name="ether1"),
                  11: SimpleNamespace(id=11, device_id=1, kind="port", name="sfp1"),
                  12: SimpleNamespace(id=12, device_id=2, kind="port", name="vmbr0"),
                  20: SimpleNamespace(id=20, device_id=2, kind="mempool", name="Physical memory")}
    dash = SimpleNamespace(id=1, name="x", public_name="Status", description=None, public=True, widgets=[
        {"id": "k", "type": "kpi", "size": "s", "device_id": 1, "component_id": None, "preset": "cpu", "title": "edge cpu"},
        {"id": "ku", "type": "kpi", "size": "s", "device_id": None, "component_id": None, "preset": None,
         "probe_id": 5, "stat": "uptime", "window": "30d", "title": ""},
        {"id": "g", "type": "gauge", "size": "s", "device_id": 1, "component_id": None, "preset": "cpu",
         "warn": 80, "crit": 90, "title": ""},
        {"id": "r", "type": "rings", "size": "m", "device_id": None, "component_id": None, "preset": None, "title": "",
         "items": [{"preset": "cpu", "device_id": 1, "label": "pve001"},
                   {"preset": "memory", "device_id": 2, "component_id": 20},
                   {"preset": "probe_loss", "probe_id": 6},
                   {"preset": "cpu", "device_id": 2}]},
        {"id": "d", "type": "donut", "size": "s", "device_id": None, "component_id": None, "preset": None, "title": ""},
        {"id": "dp", "type": "donut", "size": "s", "device_id": None, "component_id": None, "preset": None,
         "count": "problems", "title": ""},
        {"id": "b", "type": "bars", "size": "s", "device_id": 1, "component_id": None, "preset": "port_traffic",
         "limit": 2, "title": ""},
        {"id": "bp", "type": "bars", "size": "s", "device_id": None, "component_id": None, "preset": "probe_latency",
         "probe_ids": [5, 6], "title": ""},
        {"id": "gr", "type": "graph", "size": "m", "device_id": 1, "component_id": 10, "preset": "port_traffic",
         "style": "range", "title": ""},
    ])
    series = {
        "k": {"cpu_util": [["t1", 10.0, 5.0, 20.0], ["t2", 42.5, 40.0, 45.0], ["t3", None, None, None]]},
        "ku": {"up_pct": [["t1", 100.0, 100.0, 100.0], ["t2", 99.0, 99.0, 99.0]]},
        "g": {"cpu_util": [["t1", 95.0, 90.0, 99.0]]},
        "r:0": {"cpu_util": [["t1", 74.0, 70.0, 80.0]]},
        "r:1": {"used_pct": [["t1", 140.0, 0, 0]]},  # out of range: clamped to 100
        "r:2": {"ping_loss": [["t1", -3.0, 0, 0]]},  # clamped to 0
        "gr": {"in_bps": [], "out_bps": []},
    }
    bars = {
        "b": [("component", 10, 84.0), ("component", 11, 120.0), ("component", 12, 999.0), ("component", 99, 5.0)],
        "bp": [("probe", 5, 12.5), ("probe", 6, 30.0)],
    }
    ups = {5: {"uptime": {"24h": 100.0, "7d": 99.95, "30d": 99.98}}}
    return dash, devices, services, components, series, probes, ups, bars


def build(kit, only=None):
    dash, devices, services, components, series, probes, ups, bars = kit
    return build_payload(dash, "24h", devices, services, components, series, probes, only, ups, {}, bars)


def by_id(payload):
    return {w["id"]: w for w in payload["widgets"]}


def test_new_types_count_towards_devices_and_probes(kit):
    widgets = kit[0].widgets
    assert dashboard_devices(widgets) == {1, 2}
    assert probe_ids(widgets) == {5, 6}


def test_kpi_payload(kit):
    w = by_id(build(kit))
    k = w["k"]
    assert k["type"] == "kpi" and k["value"] == 42.5 and k["unit"] == "pct"
    assert k["caption"] == "CPU utilization" and k["spark"] == [10.0, 42.5]
    assert k["state"] == "WARN"  # like a device-level graph: worst of the device's services
    assert k["title"] == "CPU utilization"  # the internal title (with the hostname) is never used
    ku = w["ku"]
    assert ku["value"] == 99.98 and ku["unit"] == "pct" and ku["caption"] == "last 30 days"
    assert ku["title"] == "Uptime · Google" and ku["spark"] == [100.0, 99.0]


def test_gauge_payload(kit):
    g = by_id(build(kit))["g"]
    assert {k: g[k] for k in ("value", "unit", "min", "max", "warn", "crit", "state")} == {
        "value": 95.0, "unit": "pct", "min": 0.0, "max": 100.0, "warn": 80, "crit": 90, "state": "CRIT"}


def test_rings_payload_clamps_and_labels(kit):
    r = by_id(build(kit))["r"]
    assert r["items"] == [
        {"label": "pve001", "value": 74.0},
        {"label": "Physical memory", "value": 100.0},
        {"label": "Ping packet loss", "value": 0.0},  # probe named after its IP: generic label
        {"label": "CPU utilization", "value": None},
    ]


def test_donut_payload(kit):
    w = by_id(build(kit))
    d = w["d"]  # all services of the dashboard's devices and probes
    assert d["items"] == [{"label": "ok", "value": 2, "state": "OK"}, {"label": "warning", "value": 1, "state": "WARN"},
                          {"label": "critical", "value": 1, "state": "CRIT"},
                          {"label": "unknown", "value": 1, "state": "UNKNOWN"}]
    assert d["center"] == 5 and d["caption"] == "services" and d["state"] == "CRIT"
    dp = w["dp"]
    assert [i["state"] for i in dp["items"]] == ["WARN", "CRIT", "UNKNOWN"] and dp["center"] == 3
    assert dp["caption"] == "open" and dp["title"] == "Problems"


def test_bars_payload_sorted_limited_and_own_components_only(kit):
    w = by_id(build(kit))
    b = w["b"]
    assert b["unit"] == "bps" and b["title"] == "Interface traffic"
    assert b["items"] == [{"label": "sfp1", "value": 120.0}, {"label": "ether1", "value": 84.0}]  # vmbr0: other device
    bp = w["bp"]
    assert bp["items"] == [{"label": "Probe 2", "value": 30.0}, {"label": "Google", "value": 12.5}]


def test_graph_style_is_public(kit):
    assert by_id(build(kit))["gr"]["style"] == "range"


def test_new_widgets_never_leak_private_fields(kit):
    text = json.dumps(build(kit), default=str)
    for secret in SECRETS:
        assert secret not in text, secret
    for w in build(kit)["widgets"]:
        assert not {"device_id", "component_id", "probe_id", "probe_ids", "items_src", "target", "hostname"} & w.keys()


def test_single_new_widget(kit):
    payload = build(kit, only="g")
    assert [w["id"] for w in payload["widgets"]] == ["g"]
