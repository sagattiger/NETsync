"""Presets, the uptime widget and probe fields in the public API (never targets, URLs or raw errors)."""

import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from netsync.api.dashboards import Widget, dump_widget
from netsync.api.public import build_payload, public_message
from netsync.models import State
from netsync.presets import BY_ID, UNITS

NOW = datetime.now(UTC)


def test_new_presets():
    for pid, unit in (("probe_response", "ms"), ("probe_uptime", "pct"), ("tls_days_left", "count"),
                      ("dns_query", "ms"), ("http_status", "count")):
        p = BY_ID[pid]
        assert p.unit == unit and p.unit in UNITS and p.source == "probe"
    assert BY_ID["http_status"].area is False
    assert BY_ID["probe_uptime"].bucket("30d") == timedelta(days=1)
    assert BY_ID["probe_uptime"].bucket("24h") is None and BY_ID["probe_response"].bucket("30d") is None


def test_uptime_widget_type_validates():
    w = Widget(id="u", type="uptime", probe_id=3, public_title="Website", logo="di:google", cols=12, compact=True)
    d = dump_widget(w)
    assert d["type"] == "uptime" and d["probe_id"] == 3 and d["compact"] is True


def test_public_message_allow_list():
    secret = ("https://internal.example/health", "internal.example")
    assert public_message("HTTP 503", State.CRIT) == "HTTP 503"
    assert public_message("HTTP 200, keyword found", State.OK) == "HTTP 200, keyword found"
    assert public_message("timeout (retry 1/3)", State.UNKNOWN) == "timeout"
    assert public_message("certificate expires in 5 days", State.OK) == "certificate expires in 5 days"
    assert public_message("connection refused (expected down)", State.OK) == "connection refused"
    assert public_message("assertion failed: data.secret == hunter2", State.CRIT) == "assertion failed"
    assert public_message("backup of db-prod-01 failed: disk full", State.CRIT) == "down"  # custom push msg
    assert public_message("disk full on 10.0.0.5", State.OK) == "up"
    assert public_message("12.3 ms, 5% loss", State.OK) == "12.3 ms, 5% loss"
    assert public_message(None, State.UNKNOWN) == "pending"
    assert public_message("internal.example timeout", State.CRIT, secret) == "down"


def probe(id, device_id, name, kind, target, **kw):
    return SimpleNamespace(id=id, device_id=device_id, name=name, kind=kind, target=target, last_run=NOW,
                           last_state=kw.get("state", State.OK), last_message=kw.get("msg", "HTTP 200"),
                           cert=kw.get("cert"))


def svc(id, device_id, name, state):
    return SimpleNamespace(id=id, device_id=device_id, name=name, state=state, output="https://internal.example/x",
                           component_id=None, acknowledged=False, last_change=NOW, perf={})


def payload(only=None):
    probes = {
        1: probe(1, 10, "Website", "http", "https://internal.example/health",
                 cert={"days_left": 42.7, "not_after": "2027-01-01"}),
        2: probe(2, 20, "internal.example", "tcp", "internal.example", msg="connection refused", state=State.CRIT),
    }
    services = [svc(1, 10, "Status", State.OK), svc(2, 10, "Certificate expiry", State.OK),
                svc(3, 20, "Status", State.CRIT)]
    dash = SimpleNamespace(id=1, name="x", public_name="Status", description=None, public=True, widgets=[
        {"id": "resp", "type": "graph", "size": "m", "device_id": None, "component_id": None,
         "preset": "probe_response", "probe_id": 1, "title": ""},
        {"id": "up", "type": "uptime", "size": "l", "probe_id": 1, "public_title": "Our website", "logo": "di:nginx",
         "cols": 12, "compact": True, "title": "", "device_id": None, "component_id": None, "preset": None},
        {"id": "up2", "type": "uptime", "size": "l", "probe_id": 2, "title": "", "device_id": None,
         "component_id": None, "preset": None},
        {"id": "p", "type": "problems", "size": "m", "device_id": None},
    ])
    ups = {1: {"uptime": {"24h": 99.98, "7d": 99.9, "30d": 99.95, "1y": 99.5}},
           2: {"uptime": {"24h": 50.0, "7d": None, "30d": None, "1y": None}}}
    beats = {1: [(NOW - timedelta(minutes=i), State.OK if i % 7 else State.CRIT, 120.0 + i) for i in range(150, 0, -1)],
             2: [(NOW, State.CRIT, None)]}
    series = {"resp": {"response_ms": [["t1", 120.0, 100.0, 140.0]]}}
    return build_payload(dash, "24h", {}, services, {}, series, probes, only, ups, beats)


def test_probe_graph_widget_fields():
    w = payload()["widgets"][0]
    assert w["source"] == "probe" and w["kind"] == "http" and w["unit"] == "ms"
    assert w["uptime"] == {"24h": 99.98, "7d": 99.9, "30d": 99.95} and w["cert_days_left"] == 42
    assert w["title"] == "Response time · Website" and w["series"][0]["name"] == "Website"
    assert w["message"] == "HTTP 200" and w["last"] == {"Website": 120.0}


def test_uptime_widget_shape():
    p = payload()
    w = p["widgets"][1]
    assert w["type"] == "uptime" and w["title"] == "Our website" and w["kind"] == "http" and w["state"] == "OK"
    assert w["uptime"] == {"24h": 99.98, "7d": 99.9, "30d": 99.95}
    assert len(w["beats"]) == 100 and w["beats"][-1][1] in ("OK", "CRIT") and w["beats"][-1][2] == 121.0
    assert w["beats"][0][0] < w["beats"][-1][0]  # oldest first
    assert w["logo"]["src"].endswith("/svg/nginx.svg") and w["cols"] == 12 and w["compact"] is True
    w2 = p["widgets"][2]
    assert w2["title"] == "Uptime" and w2["state"] == "CRIT" and w2["message"] == "connection refused"
    assert w2["uptime"] == {"24h": 50.0, "7d": None, "30d": None} and w2["beats"] == [[NOW, "CRIT", None]]
    assert p["summary"]["state"] == "CRIT"


def test_public_payload_never_contains_targets_or_urls():
    text = json.dumps(payload(), default=str)
    for secret in ("internal.example", "https://", "/health"):
        assert secret not in text.replace("https://cdn.jsdelivr.net", ""), secret


def test_single_uptime_widget():
    p = payload(only="up")
    assert [w["id"] for w in p["widgets"]] == ["up"]
