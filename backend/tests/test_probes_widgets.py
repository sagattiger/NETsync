import json
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from netsync.api.dashboards import DashboardIn, Widget, dump_widget
from netsync.api.icons import build_index, logo_src, search
from netsync.api.probes import ProbeIn
from netsync.api.public import build_payload, merge_band
from netsync.models import State
from netsync.presets import BY_ID
from netsync.probes import probe_results, validate_target

NOW = datetime.now(UTC)


# --------------------------------------------------------------------------- probe targets

@pytest.mark.parametrize("target,expected", [
    ("8.8.8.8", "8.8.8.8"),
    ("2001:4860:4860::8888", "2001:4860:4860::8888"),
    ("google.com", "google.com"),
    ("Dns.Google.", "dns.google"),
    ("localhost", "localhost"),
    ("  1.1.1.1 ", "1.1.1.1"),
])
def test_target_accepts_ips_and_hostnames(target, expected):
    assert validate_target(target) == expected


@pytest.mark.parametrize("target", [
    "http://x", "a b", ";rm", "x;rm -rf /", "$(id)", "`id`", "google.com:443", "host/path", "-bad.com",
    "bad-.com", "999.1.1.1", "", "a" * 64 + ".com", "x..com", "1.2.3", "user@host", "*.example.com",
])
def test_target_rejects_everything_else(target):
    with pytest.raises(ValueError):
        validate_target(target)


def test_probe_in_validates_target_interval_and_count():
    assert ProbeIn(name=" Google ", target="google.com").name == "Google"
    p = ProbeIn(name="g", target="8.8.8.8")
    assert (p.interval_s, p.count, p.kind, p.enabled) == (60, 5, "icmp", True)
    for bad in ({"target": "http://x"}, {"interval_s": 10}, {"interval_s": 3601}, {"count": 0}, {"kind": "smtp"}):
        with pytest.raises(ValidationError):
            ProbeIn(**{"name": "g", "target": "8.8.8.8", **bad})


def host(alive=True, loss=0.0, avg=20.0):
    return SimpleNamespace(is_alive=alive, packet_loss=loss, min_rtt=avg - 5, avg_rtt=avg, max_rtt=avg + 5, jitter=1.5)


def test_probe_results_metrics_and_checks():
    metrics, checks, alive = probe_results("8.8.8.8", host(loss=0.2))
    assert alive
    assert {m.name: m.value for m in metrics} == {"ping_loss": 20.0, "ping_min": 15.0, "ping_avg": 20.0,
                                                  "ping_max": 25.0, "ping_jitter": 1.5}
    assert [(c.check, c.name, c.value) for c in checks] == [("ping_rtt", "Ping RTT", 20.0), ("ping_loss", "Ping loss", 20.0)]
    metrics, checks, alive = probe_results("8.8.8.8", host(alive=False, loss=1.0))
    assert not alive and [m.name for m in metrics] == ["ping_loss"]
    assert all(c.state == State.CRIT for c in checks)


def test_probe_presets():
    lat, loss = BY_ID["probe_latency"], BY_ID["probe_loss"]
    assert lat.source == loss.source == "probe"
    assert lat.unit == "ms" and [m.label for m in lat.metrics] == ["avg"]
    assert loss.unit == "pct"
    assert BY_ID["port_traffic"].source == "device"


# --------------------------------------------------------------------------- widget appearance

def W(**kw):
    return Widget(**{"id": "w1", "type": "graph", "preset": "port_traffic", **kw})


def test_widget_appearance_fields_valid():
    w = W(colors=["#00abfa", "#F58A07", "#fff"], labels={"in": "Rx", "out": " Tx "}, logo="di:google",
          cols=8, height="tall", compact=True)
    assert w.colors == ["#00ABFA", "#F58A07", "#FFF"] and w.labels == {"in": "Rx", "out": "Tx"}
    assert W(logo="https://example.com/logo.svg").logo == "https://example.com/logo.svg"
    assert W(logo="di:home-assistant.png").logo == "di:home-assistant.png"
    assert W(logo="").logo is None


@pytest.mark.parametrize("bad", [
    {"colors": ["red"]}, {"colors": ["#12345"]}, {"colors": ["#GGG"]}, {"colors": ["#fff"] * 7},
    {"labels": {"in": "x" * 17}}, {"labels": {"<b>": "x"}},
    {"logo": "javascript:alert(1)"}, {"logo": "http://example.com/x.svg"}, {"logo": "data:image/svg+xml,<svg>"},
    {"logo": "https://exa mple.com/x.svg"}, {"logo": "https://a.com/x.svg\"onerror=x"}, {"logo": "di:Google"},
    {"logo": "di:../../etc"}, {"logo": "//example.com/x.svg"}, {"logo": "https://user:pw@example.com/x.svg"},
    {"cols": 5}, {"cols": 13}, {"height": "huge"},
])
def test_widget_appearance_fields_rejected(bad):
    with pytest.raises(ValidationError):
        W(**bad)


def test_old_widgets_serialize_unchanged():
    old = {"id": "w1", "type": "graph", "title": "", "size": "m", "device_id": 1, "component_id": 10,
           "preset": "port_traffic", "public_title": None}
    assert dump_widget(Widget(**old)) == old
    body = DashboardIn(name="x", widgets=[old])
    assert [dump_widget(w) for w in body.widgets] == [old]
    new = dump_widget(W(cols=6, compact=True, colors=["#000"], probe_id=None))
    assert new["cols"] == 6 and new["compact"] is True and new["colors"] == ["#000"] and "probe_id" not in new


def test_logo_src():
    assert logo_src("di:google") == "https://cdn.jsdelivr.net/gh/homarr-labs/dashboard-icons/svg/google.svg"
    assert logo_src("di:google.webp") == "https://cdn.jsdelivr.net/gh/homarr-labs/dashboard-icons/webp/google.webp"
    assert logo_src("https://x.example/a.png") == "https://x.example/a.png"


def test_icon_index_and_search():
    tree = {"svg": ["google.svg", "google-drive.svg", "cloudflare.svg"], "png": ["google.png", "only-png.png"],
            "webp": ["google.webp"]}
    meta = {"cloudflare": {"aliases": ["cf"]}, "only-png": {"base": "png"}}
    icons = build_index(tree, meta)
    by = {i["slug"]: i for i in icons}
    assert by["google"]["formats"] == ["svg", "png", "webp"] and by["google"]["logo"] == "di:google"
    assert by["only-png"]["logo"] == "di:only-png.png"
    assert [i["slug"] for i in search(icons, "goo", 10)] == ["google", "google-drive"]
    assert [i["slug"] for i in search(icons, "cf", 10)] == ["cloudflare"]
    assert all(W(logo=i["logo"]).logo for i in icons)  # every index entry is a valid widget logo


# --------------------------------------------------------------------------- public payload

def svc(id, device_id, name, state, value=None, component_id=None):
    return SimpleNamespace(id=id, device_id=device_id, name=name, state=state, output="8.8.8.8 secret output",
                           component_id=component_id, acknowledged=False, last_change=NOW,
                           perf={"value": value} if value is not None else {})


@pytest.fixture
def probe_dash():
    devices = {1: SimpleNamespace(id=1, hostname="edge.internal", ip="10.0.0.1", status=State.OK, uptime=1,
                                  device_type="router")}
    probe = SimpleNamespace(id=5, device_id=50, name="Google", target="dns.google", kind="icmp")
    named_by_ip = SimpleNamespace(id=6, device_id=60, name="8.8.4.4", target="8.8.4.4", kind="icmp")
    services = [
        svc(1, 1, "Interface ether1", State.OK, component_id=10),
        svc(2, 50, "Ping RTT", State.OK, 80.4), svc(3, 50, "Ping loss", State.OK, 0.0),
        svc(4, 60, "Ping RTT", State.WARN, 150.0), svc(5, 60, "Ping loss", State.WARN, 20.0),
    ]
    components = {10: SimpleNamespace(id=10, device_id=1, kind="port", name="ether1")}
    dash = SimpleNamespace(id=1, name="x", public_name="Status", description=None, public=True, widgets=[
        {"id": "up", "type": "graph", "size": "m", "device_id": 1, "component_id": 10, "preset": "port_traffic",
         "title": "", "public_title": "Uplink traffic", "colors": ["#00ABFA", "#F58A07"],
         "labels": {"in": "Rx", "out": "Tx"}, "logo": "di:mikrotik", "cols": 6, "height": "compact", "compact": True},
        {"id": "g", "type": "graph", "size": "s", "device_id": None, "component_id": None, "preset": "probe_latency",
         "probe_id": 5, "title": "", "public_title": "Ping to Google", "logo": "di:google"},
        {"id": "ip", "type": "graph", "size": "s", "device_id": None, "component_id": None, "preset": "probe_latency",
         "probe_id": 6, "title": ""},
        {"id": "loss", "type": "graph", "size": "s", "device_id": None, "component_id": None, "preset": "probe_loss",
         "probe_id": 5, "title": ""},
        {"id": "p", "type": "problems", "size": "m", "device_id": None},
    ])
    series = {
        "up": {"in_bps": [["t1", 1.0, 1.0, 1.0]], "out_bps": [["t1", 2.0, 2.0, 2.0]]},
        "g": {"ping_avg": [["t1", 80.0, 79.0, 81.0], ["t2", 80.4, 80.0, 81.0]],
              "ping_min": [["t1", 70.0, 60.0, 75.0], ["t2", 71.0, 65.0, 72.0]],
              "ping_max": [["t1", 90.0, 85.0, 120.0], ["t2", 95.0, 90.0, 99.0]]},
        "loss": {"ping_loss": [["t1", 0.0, 0.0, 0.0]]},
    }
    probes = {5: probe, 6: named_by_ip}
    return dash, devices, services, components, series, probes


def test_public_payload_has_appearance_fields(probe_dash):
    w = build_payload(probe_dash[0], "24h", *probe_dash[1:])["widgets"][0]
    assert w["cols"] == 6 and w["height"] == "compact" and w["compact"] is True
    assert w["colors"] == ["#00ABFA", "#F58A07"]
    assert w["logo"] == {"src": "https://cdn.jsdelivr.net/gh/homarr-labs/dashboard-icons/svg/mikrotik.svg", "alt": "Mikrotik"}
    assert [(s["key"], s["name"]) for s in w["series"]] == [("in", "Rx"), ("out", "Tx")]
    assert w["last"] == {"Rx": 1.0, "Tx": 2.0} and w["title"] == "Uplink traffic"


def test_public_probe_widget(probe_dash):
    payload = build_payload(probe_dash[0], "24h", *probe_dash[1:])
    g = payload["widgets"][1]
    assert g["source"] == "probe" and g["unit"] == "ms" and g["state"] == "OK" and g["title"] == "Ping to Google"
    assert g["series"] == [{"key": "avg", "name": "Google",
                            "points": [["t1", 80.0, 60.0, 120.0], ["t2", 80.4, 65.0, 99.0]]}]
    assert g["last"] == {"Google": 80.4} and g["loss_pct"] == 0.0
    assert "colors" not in g and g["logo"]["alt"] == "Google"
    loss = payload["widgets"][3]
    assert loss["unit"] == "pct" and loss["title"] == "Ping · Google" and loss["series"][0]["name"] == "Google"
    # problems include the probes used by the dashboard
    assert [i["name"] for i in payload["widgets"][4]["items"]] == ["Ping RTT", "Ping loss"]
    assert payload["summary"]["state"] == "WARN" and payload["summary"]["devices"] == {"up": 1, "down": 0}


def test_public_payload_never_contains_probe_target(probe_dash):
    payload = build_payload(probe_dash[0], "24h", *probe_dash[1:])
    text = json.dumps(payload, default=str)
    for secret in ("dns.google", "8.8.4.4", "secret output", "edge.internal", "10.0.0.1"):
        assert secret not in text, secret
    ip = payload["widgets"][2]  # probe named after its own IP: generic title and series name
    assert ip["title"] == "Ping latency" and ip["series"][0]["name"] == "avg" and ip["state"] == "WARN"


def test_single_widget_build(probe_dash):
    payload = build_payload(probe_dash[0], "24h", *probe_dash[1:], only="g")
    assert [w["id"] for w in payload["widgets"]] == ["g"]
    assert build_payload(probe_dash[0], "24h", *probe_dash[1:], only="nope")["widgets"] == []


def test_old_payload_shape_unchanged_without_new_fields(probe_dash):
    dash = probe_dash[0]
    dash.widgets = [{"id": "w", "type": "graph", "size": "m", "device_id": 1, "component_id": 10,
                     "preset": "port_traffic", "title": ""}]
    w = build_payload(dash, "24h", *probe_dash[1:])["widgets"][0]
    assert set(w) == {"id", "type", "size", "title", "state", "unit", "area", "series", "last"}
    assert [s["name"] for s in w["series"]] == ["in", "out"]


def test_merge_band():
    assert merge_band({"ping_avg": [["t", 5.0, 4.0, 6.0]], "ping_min": [], "ping_max": []}) == [["t", 5.0, 4.0, 6.0]]
