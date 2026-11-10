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
