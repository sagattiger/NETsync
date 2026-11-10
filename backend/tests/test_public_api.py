import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from netsync.api.dashboards import DashboardIn, _apply_public
from netsync.api.public import build_payload
from netsync.api.tokens import generate_token, hash_token, token_problem
from netsync.metrics_query import RANGES
from netsync.models import Role, State
from netsync.presets import PRESETS, UNITS

NOW = datetime.now(UTC)


# --------------------------------------------------------------------------- tokens

def test_token_format_and_hash():
    t = generate_token()
    assert t.startswith("nst_") and len(t) == 44
    assert generate_token() != t
    h = hash_token(t)
    assert len(h) == 64 and h != t and hash_token(t) == h


def test_token_validity():
    ok = SimpleNamespace(revoked=False, expires_at=None)
    assert token_problem(ok, NOW) is None
    assert token_problem(None, NOW) == "Invalid API token"
    assert token_problem(SimpleNamespace(revoked=True, expires_at=None), NOW) == "API token revoked"
    assert token_problem(SimpleNamespace(revoked=False, expires_at=NOW - timedelta(seconds=1)), NOW) == "API token expired"
    assert token_problem(SimpleNamespace(revoked=False, expires_at=NOW + timedelta(days=1)), NOW) is None


# --------------------------------------------------------------------------- ranges / presets

def test_ranges_map_to_buckets():
    assert RANGES["1h"] == (timedelta(hours=1), timedelta(minutes=1))
    assert RANGES["6h"] == (timedelta(hours=6), timedelta(minutes=2))
    assert RANGES["24h"] == (timedelta(hours=24), timedelta(minutes=5))
    assert RANGES["7d"] == (timedelta(days=7), timedelta(minutes=30))
    assert RANGES["30d"] == (timedelta(days=30), timedelta(hours=2))
    assert RANGES["1y"] == (timedelta(days=365), timedelta(days=1))


def test_presets_are_well_formed():
    ids = [p.id for p in PRESETS]
    assert len(ids) == len(set(ids))
    for p in PRESETS:
        assert p.unit in UNITS and p.metrics
        d = p.as_dict()
        assert {"id", "label", "group", "kind", "unit", "metrics", "area"} <= d.keys()
        assert all({"name", "label"} == m.keys() for m in d["metrics"])


# --------------------------------------------------------------------------- payload

def device(id, hostname, ip, status=State.OK, device_type="router"):
    return SimpleNamespace(id=id, hostname=hostname, ip=ip, status=status, uptime=3600, device_type=device_type,
                           sys_descr=f"Linux {hostname} 6.8.0", sys_name=hostname)


def service(id, device_id, name, state, output, component_id=None, acknowledged=False):
    return SimpleNamespace(id=id, device_id=device_id, name=name, state=state, output=output,
                           component_id=component_id, acknowledged=acknowledged, last_change=NOW)


@pytest.fixture
def fixture():
    devices = {
        1: device(1, "core-rtr1.internal.example", "10.0.0.1"),
        2: device(2, "db-secret.internal.example", "10.0.0.2", device_type="server"),
        3: device(3, "not-on-dashboard.internal", "10.0.0.3"),
    }
    services = [
        service(1, 1, "Interface ether1", State.OK, "up, in 3.2 Mbps from 10.0.0.1", component_id=10),
        service(2, 1, "CPU utilization", State.WARN, "85% on core-rtr1"),
        service(3, 2, "Memory", State.CRIT, "99% used on db-secret", acknowledged=True),
        service(4, 3, "Disk", State.CRIT, "full on not-on-dashboard"),  # other device: must not appear
    ]
    components = {10: SimpleNamespace(id=10, device_id=1, kind="port", name="ether1")}
    dash = SimpleNamespace(id=7, name="Internal name", public_name="Network status", description="Our network",
                           public=True, widgets=[
                               {"id": "w1", "type": "graph", "size": "l", "device_id": 1, "component_id": 10,
                                "preset": "port_traffic", "title": "core-rtr1 uplink"},
                               {"id": "w2", "type": "device", "size": "m", "device_id": 2, "title": "db"},
                               {"id": "w3", "type": "services", "size": "m", "device_id": 1, "public_title": "Core router"},
                               {"id": "w4", "type": "problems", "size": "m", "device_id": None},
                           ])
    series = {"w1": {"in_bps": [["t1", 100.0, 90.0, 110.0], ["t2", 200.0, 150.0, 250.0]], "out_bps": []}}
    return dash, devices, services, components, series


def test_payload_never_leaks_hostnames_ips_or_output(fixture):
    payload = build_payload(*fixture[:1], "24h", *fixture[1:])
    text = json.dumps(payload, default=str)
    for secret in ("core-rtr1", "db-secret", "not-on-dashboard", "10.0.0.", "internal.example", "Linux ",
                   "Mbps", "99% used", "85% on", "Internal name", "uplink"):
        assert secret not in text, secret
    assert payload["name"] == "Network status"


def test_public_title_is_used_verbatim(fixture):
    dash = fixture[0]
    dash.widgets[0]["public_title"] = "core-rtr1 · Uplink 1"  # an admin chose to show it
    payload = build_payload(dash, "24h", *fixture[1:])
    assert payload["widgets"][0]["title"] == "core-rtr1 · Uplink 1"
    assert payload["widgets"][2]["title"] == "Core router"


def test_graph_widget_shape(fixture):
    w = build_payload(fixture[0], "6h", *fixture[1:])["widgets"][0]
    assert w["title"] == "Interface traffic · ether1"
    assert w["unit"] == "bps" and w["area"] is True and w["state"] == "OK"
    assert [s["name"] for s in w["series"]] == ["in", "out"]
    assert w["last"] == {"in": 200.0, "out": None}


def test_device_and_summary(fixture):
    payload = build_payload(fixture[0], "24h", *fixture[1:])
    dev = payload["widgets"][1]
    assert dev["title"] == "Server" and dev["status"] == "up" and dev["state"] == "CRIT"
    assert dev["services"] == {"OK": 0, "WARN": 0, "CRIT": 1, "UNKNOWN": 0}
    assert payload["summary"]["state"] == "CRIT"
    assert payload["summary"]["devices"] == {"up": 2, "down": 0}
    assert payload["summary"]["services"] == {"OK": 1, "WARN": 1, "CRIT": 1, "UNKNOWN": 0}


def test_problems_widget_limited_to_dashboard_devices(fixture):
    probs = build_payload(fixture[0], "24h", *fixture[1:])["widgets"][3]
    assert [i["name"] for i in probs["items"]] == ["Memory", "CPU utilization"]  # worst first; "Disk" excluded
    assert probs["items"][0] == {"name": "Memory", "state": "CRIT", "since": NOW, "acknowledged": True}


def test_component_of_another_device_is_ignored(fixture):
    dash, devices, services, components, series = fixture
    dash.widgets[0]["device_id"] = 2  # component 10 belongs to device 1
    w = build_payload(dash, "24h", devices, services, components, series)["widgets"][0]
    assert w["title"] == "Interface traffic"


# --------------------------------------------------------------------------- publishing rights

def test_only_admins_can_publish():
    viewer = SimpleNamespace(role=Role.OPERATOR)
    admin = SimpleNamespace(role=Role.ADMIN)
    d = SimpleNamespace(public=False, public_name=None)
    with pytest.raises(HTTPException) as e:
        _apply_public(d, DashboardIn(name="x", public=True), viewer)
    assert e.value.status_code == 403
    _apply_public(d, DashboardIn(name="x", public=True, public_name="Status"), admin)
    assert d.public is True and d.public_name == "Status"
    # an editor that doesn't send the field keeps it public
    _apply_public(d, DashboardIn(name="x"), viewer)
    assert d.public is True
