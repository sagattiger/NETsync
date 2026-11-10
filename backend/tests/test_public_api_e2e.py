"""End-to-end checks of the public API against a running NETsync.

Opt-in: set NETSYNC_E2E_URL (e.g. http://localhost:8000/api) and NETSYNC_E2E_ADMIN_JWT.
Creates its own token and dashboards and removes them afterwards.
"""

import os
import time
from datetime import UTC, datetime, timedelta

import httpx
import pytest

URL = os.environ.get("NETSYNC_E2E_URL")
JWT = os.environ.get("NETSYNC_E2E_ADMIN_JWT")
pytestmark = pytest.mark.skipif(not (URL and JWT), reason="set NETSYNC_E2E_URL and NETSYNC_E2E_ADMIN_JWT")


@pytest.fixture
def admin():
    with httpx.Client(base_url=URL, headers={"Authorization": f"Bearer {JWT}"}, timeout=30) as c:
        yield c


@pytest.fixture
def setup(admin):
    token = admin.post("/tokens", json={"name": "e2e test"}).json()
    pub = admin.post("/dashboards", json={"name": "e2e public", "public": True, "public_name": "E2E status",
                                          "widgets": []}).json()
    priv = admin.post("/dashboards", json={"name": "e2e private", "widgets": []}).json()
    yield token, pub, priv
    admin.delete(f"/dashboards/{pub['id']}")
    admin.delete(f"/dashboards/{priv['id']}")
    admin.delete(f"/tokens/{token['id']}")


def public(token: str):
    return httpx.Client(base_url=URL, headers={"Authorization": f"Bearer {token}"}, timeout=30)


def test_token_reads_public_dashboards_only(setup):
    token, pub, priv = setup
    with public(token["token"]) as c:
        r = c.get("/public/dashboards")
        assert r.status_code == 200 and r.headers["cache-control"] == "public, max-age=30"
        ids = [d["id"] for d in r.json()]
        assert pub["id"] in ids and priv["id"] not in ids
        assert c.get(f"/public/dashboards/{pub['id']}?range=1h").json()["name"] == "E2E status"
        assert c.get(f"/public/dashboards/{priv['id']}").status_code == 404
        assert c.get("/public/dashboards/999999").status_code == 404


def test_token_is_rejected_by_the_normal_api(setup):
    token, _, _ = setup
    with public(token["token"]) as c:
        for path in ("/devices", "/syslog", "/users", "/auth/me", "/problems", "/dashboards"):
            assert c.get(path).status_code == 401, path


def test_jwt_is_not_a_public_token(admin):
    assert admin.get("/public/dashboards").status_code == 401


def test_revoked_token_gets_401(admin, setup):
    token, _, _ = setup
    admin.delete(f"/tokens/{token['id']}")
    with public(token["token"]) as c:
        assert c.get("/public/dashboards").status_code == 401


def test_expired_token_gets_401(admin):
    expires = (datetime.now(UTC) + timedelta(seconds=2)).isoformat()
    token = admin.post("/tokens", json={"name": "e2e expiring", "expires_at": expires}).json()
    try:
        with public(token["token"]) as c:
            assert c.get("/public/dashboards").status_code == 200
            time.sleep(3)
            assert c.get("/public/dashboards").status_code == 401
    finally:
        admin.delete(f"/tokens/{token['id']}")


def test_full_token_is_only_returned_on_creation(admin, setup):
    token, _, _ = setup
    listed = next(t for t in admin.get("/tokens").json() if t["id"] == token["id"])
    assert "token" not in listed and listed["prefix"] == token["token"][:8]


# --------------------------------------------------------------------------- probes and single widgets

@pytest.fixture
def probe(admin):
    p = admin.post("/probes", json={"name": "e2e loopback", "target": "127.0.0.1", "interval_s": 30, "count": 2})
    assert p.status_code == 200, p.text
    p = p.json()
    yield p
    admin.delete(f"/probes/{p['id']}")


def test_probe_validation_rejects_bad_targets(admin):
    for bad in ("http://x", "a b", ";rm"):
        assert admin.post("/probes", json={"name": "bad", "target": bad}).status_code == 422, bad


def test_probe_metrics_stored_and_returned(admin, probe):
    deadline = time.time() + 45
    data = {}
    while time.time() < deadline:
        data = admin.get(f"/probes/{probe['id']}/metrics?range=1h").json()
        if data.get("ping_avg"):
            break
        time.sleep(3)
    assert data["ping_avg"] and data["ping_loss"], data
    t, avg, mn, mx = data["ping_avg"][-1]
    assert avg is not None and mn <= avg <= mx
    got = admin.get(f"/probes/{probe['id']}").json()
    assert got["rtt_ms"] is not None and {"Ping RTT", "Ping loss", "Status"} <= {s["name"] for s in got["services"]}
    # probes are not listed as SNMP devices
    assert probe["device_id"] not in [d["id"] for d in admin.get("/devices").json()]


def test_public_probe_widget_and_single_widget_endpoint(admin, setup, probe):
    token, pub, priv = setup
    widgets = [{"id": "g", "type": "graph", "size": "s", "preset": "probe_latency", "probe_id": probe["id"],
                "title": "", "public_title": "Ping to loopback", "labels": {"avg": "Loop"}, "logo": "di:google",
                "cols": 4, "compact": True}]
    r = admin.put(f"/dashboards/{pub['id']}", json={"name": "e2e public", "widgets": widgets})
    assert r.status_code == 200, r.text
    with public(token["token"]) as c:
        r = c.get(f"/public/dashboards/{pub['id']}/widgets/g?range=1h")
        assert r.status_code == 200 and r.headers["cache-control"] == "public, max-age=30"
        w = r.json()
        assert w["source"] == "probe" and w["title"] == "Ping to loopback" and w["cols"] == 4 and w["compact"] is True
        assert w["series"][0]["key"] == "avg" and w["series"][0]["name"] == "Loop" and "Loop" in w["last"]
        assert w["logo"]["src"].startswith("https://cdn.jsdelivr.net/") and "127.0.0.1" not in r.text
        assert c.get(f"/public/dashboards/{pub['id']}/widgets/nope").status_code == 404
        assert c.get(f"/public/dashboards/{priv['id']}/widgets/g").status_code == 404


# --------------------------------------------------------------------------- push monitors (no login)

def test_push_endpoint(admin):
    created = admin.post("/probes", json={"name": "e2e push", "kind": "push", "interval_s": 60})
    assert created.status_code == 200, created.text
    p = created.json()
    try:
        token, url = p["push_token"], p["push_url"]
        assert token.startswith("nsp_") and url.endswith(f"/api/push/{token}")
        assert "push_token" not in admin.get(f"/probes/{p['id']}").json()  # shown once
        with httpx.Client(base_url=URL, timeout=30) as anon:  # no Authorization header at all
            assert anon.get(f"/push/{token}?status=up&msg=backup%20ok&ping=12.5").json() == {"ok": True}
            assert anon.post(f"/push/{token}?status=down&msg=disk%20full").status_code == 200
            assert anon.get("/push/nsp_invalidtoken").status_code == 404
            assert anon.get("/push/not-a-token").status_code == 404
            assert anon.get("/push/").status_code in (404, 405)
            beats = admin.get(f"/probes/{p['id']}/heartbeats").json()
            assert [b["message"] for b in beats[-2:]] == ["backup ok", "disk full"]
            assert beats[-2]["response_ms"] == 12.5 and beats[-1]["state"] == 2
            # regenerate: the old URL stops working
            new = admin.post(f"/probes/{p['id']}/push-token").json()
            assert anon.get(f"/push/{token}").status_code == 404
            assert anon.get(f"/push/{new['push_token']}").status_code == 200
            admin.post(f"/probes/{p['id']}/pause")
            assert anon.get(f"/push/{new['push_token']}").status_code == 404  # paused
    finally:
        admin.delete(f"/probes/{p['id']}")


def test_probe_secrets_never_returned(admin):
    body = {"name": "e2e secret", "kind": "http", "target": "https://example.invalid/", "enabled": False,
            "config": {"auth": "basic", "auth_user": "bob"},
            "secrets": {"password": "s3cr3t-pw", "headers": {"X-Api-Key": "key-123"}}}
    p = admin.post("/probes", json=body)
    assert p.status_code == 200, p.text
    p = p.json()
    try:
        for r in (p, admin.get(f"/probes/{p['id']}").json(), admin.get("/probes").json()):
            text = str(r)
            assert "s3cr3t-pw" not in text and "key-123" not in text
        got = admin.get(f"/probes/{p['id']}").json()
        assert got["secrets"] == {"has_password": True, "has_headers": True, "header_names": ["X-Api-Key"]}
        # PUT without secrets keeps them
        body.pop("secrets")
        assert admin.put(f"/probes/{p['id']}", json=body).json()["secrets"]["has_password"] is True
    finally:
        admin.delete(f"/probes/{p['id']}")


# --------------------------------------------------------------------------- Uptime Kuma import

def test_kuma_import_preview_and_import(admin):
    import json
    from pathlib import Path

    backup = json.loads((Path(__file__).parent / "fixtures" / "kuma_backup.json").read_text())
    for m in backup["monitorList"]:
        m["name"] = f"e2e kuma {m['name']}"
        m["active"] = False  # don't actually poll example.com from the test
    preview = admin.post("/probes/import/kuma/preview", json=backup)
    assert preview.status_code == 200, preview.text
    plan = preview.json()
    assert "SECRET" not in preview.text  # neither notification secrets nor monitor credentials are echoed
    assert {s["name"] for s in plan["skipped"]} >= {"e2e kuma Containers", "e2e kuma Broken URL"}
    names = [c["name"] for c in plan["create"]]
    assert "e2e kuma API health" in names and "e2e kuma Nightly backup" in names
    created = admin.post("/probes/import/kuma", json={"backup": backup, "names": ["e2e kuma API health",
                                                                                 "e2e kuma Nightly backup"]})
    assert created.status_code == 200, created.text
    try:
        got = {c["name"]: c for c in created.json()["created"]}
        assert set(got) == {"e2e kuma API health", "e2e kuma Nightly backup"}
        assert got["e2e kuma Nightly backup"]["push_url"].startswith("http")
        api_probe = admin.get(f"/probes/{got['e2e kuma API health']['id']}").json()
        assert api_probe["kind"] == "json" and api_probe["config"]["assertions"][0]["path"] == "data.status"
        again = admin.post("/probes/import/kuma/preview", json=backup).json()
        assert "e2e kuma API health" not in [c["name"] for c in again["create"]]  # now a duplicate
    finally:
        for c in created.json()["created"]:
            admin.delete(f"/probes/{c['id']}")
