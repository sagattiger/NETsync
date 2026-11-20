"""CrowdSec plugin with fake LAPI answers: parsing, tracking, the HTTP client (normal, empty, timeout, 403, unexpected
format), checks, and the public widget allow-list. The fake answers follow GET /v1/decisions as documented in
CrowdSec's localapi_swagger.yaml (bouncer API key)."""

import json
from datetime import UTC, datetime
from types import SimpleNamespace

import httpx
import pytest

from netsync.api.dashboards import Widget, dump_widget
from netsync.api.public import build_payload
from netsync.models import State
from netsync.plugins.builtin.crowdsec import logic, service, summary

KEY = "fakebouncerkey0123456789abcdef"


def dec(i, value, origin, scenario, type_="ban", **kw):
    return {"id": i, "uuid": f"u{i}", "origin": origin, "type": type_, "scope": "Range" if "/" in value else "Ip",
            "value": value, "duration": "3h59m12.4s", "until": "2026-11-20T03:00:00Z", "scenario": scenario, **kw}


LAPI = [
    dec(101, "203.0.113.7", "crowdsec", "crowdsecurity/http-probing"),
    dec(102, "203.0.113.8", "crowdsec", "crowdsecurity/http-probing"),
    dec(103, "198.51.100.20", "crowdsec", "crowdsecurity/ssh-bf"),
    dec(104, "2001:db8:abcd:12::5", "cscli", "manual 'ban' from 'localhost'"),
    dec(105, "192.0.2.0/24", "crowdsec", "crowdsecurity/http-sensitive-files"),
    dec(106, "198.51.100.30", "crowdsec", "crowdsecurity/http-probing", type_="captcha"),
    dec(107, "198.51.100.40", "crowdsec", "crowdsecurity/ssh-bf", simulated=True),
    dec(5001, "203.0.113.7", "CAPI", "crowdsecurity/http-probing"),  # also local: counted once in total
    dec(5002, "45.0.0.1", "CAPI", "crowdsecurity/ssh-bf"),
    dec(5003, "45.0.0.2", "lists:firehol_cruzit_web_attacks", "lists:firehol_cruzit_web_attacks"),
]
IP_LIKE = ("203.0.113", "198.51.100", "192.0.2", "2001:db8", "45.0.0")


# --------------------------------------------------------------------------------------------- parsing


def test_aggregate_counts():
    a = logic.aggregate(LAPI)
    assert (a["local"], a["community"], a["total"], a["other"], a["simulated"]) == (5, 3, 7, 1, 1)
    assert a["by_origin"] == {"crowdsec": 4, "cscli": 1, "capi": 2, "lists": 1}
    assert next(iter(a["scenarios"])) == "crowdsecurity/http-probing" and a["scenarios"]["manual"] == 1
    assert a["recent"][0] == {"id": 105, "ip": "192.0.2.x/24", "scenario": "crowdsecurity/http-sensitive-files",
                              "origin": "crowdsec"}


@pytest.mark.parametrize("answer", [None, []])
def test_empty_answers(answer):
    a = logic.aggregate(answer)
    assert (a["local"], a["community"], a["total"]) == (0, 0, 0)


@pytest.mark.parametrize("answer", [{"message": "access forbidden"}, "<html>", 42])
def test_unexpected_formats_rejected(answer):
    with pytest.raises(logic.BadAnswer):
        logic.aggregate(answer)


def test_broken_items_skipped_and_mask():
    assert logic.aggregate([{"id": 1}, "junk", {"value": ["x"]}, {"value": True}])["total"] == 0
    assert logic.mask("203.0.113.7") == "203.0.113.x"
    assert logic.mask("2001:db8:abcd:12::5") == "2001:db8:abcd::x"
    assert logic.mask("192.0.2.0/24") == "192.0.2.x/24"
    assert logic.mask("BR") == "x" and logic.mask("") == "x"
    assert logic.scenario_key("bad<script>") == "badscript" and logic.scenario_key("") == "manual"


def test_track_new_bans_and_db_reset():
    st, new = logic.track(None, [101, 105], 1000)
    assert new is None and st["max_id"] == 105 and st["since"] == 1000  # first read: starting point only
    st, new = logic.track(st, [101, 105, 108, 109], 1300)
    assert new == 2 and st["new_total"] == 2
    st, new = logic.track(st, [101, 105, 108, 109], 1600)
    assert new == 0 and st["new_total"] == 2
    st, new = logic.track(st, [50], 1900)  # CrowdSec database reset: ids start over
    st, new = logic.track(st, [50, 51], 2200)
    assert new == 1 and st["new_total"] == 3


def test_daily_new_from_running_count():
    assert logic.daily_new([None, (0, 4), (4, 9), None, (9, 9)], None) == [None, 4, 5, None, 0]
    assert logic.daily_new([(10, 12)], 7) == [5]  # counts from the last value before the window


# --------------------------------------------------------------------------------------------- HTTP client


def transport(handler):
    return httpx.MockTransport(handler)


async def test_fetch_normal_sends_key_header_without_redirects():
    seen = {}

    def handler(req):
        seen["url"], seen["key"] = str(req.url), req.headers.get("x-api-key")
        return httpx.Response(200, json=LAPI)

    r = await service.fetch("http://lapi.test:8080/", KEY, 5, transport=transport(handler))
    assert r["ok"] and r["status"] == 200 and len(r["json"]) == len(LAPI)
    assert seen == {"url": "http://lapi.test:8080/v1/decisions", "key": KEY}


async def test_fetch_null_answer():
    r = await service.fetch("http://lapi.test", KEY, transport=transport(lambda req: httpx.Response(200, text="null")))
    assert r["ok"] and r["json"] is None


@pytest.mark.parametrize(("code", "msg"), [(403, "HTTP 403 (bouncer key refused)"), (401, "HTTP 401 (bouncer key refused)"),
                                           (404, "HTTP 404 (is this a CrowdSec LAPI address?)"), (500, "HTTP 500"),
                                           (302, "HTTP 302")])
async def test_fetch_http_errors(code, msg):
    r = await service.fetch("http://lapi.test", KEY,
                            transport=transport(lambda req: httpx.Response(code, json={"message": KEY})))
    assert not r["ok"] and r["message"] == msg and KEY not in json.dumps(r)


async def test_fetch_timeout_and_refused():
    def slow(req):
        raise httpx.ReadTimeout("timed out", request=req)

    def refused(req):
        raise httpx.ConnectError("refused", request=req)

    assert (await service.fetch("http://lapi.test", KEY, transport=transport(slow)))["message"] == "timeout"
    r = await service.fetch("http://lapi.test", KEY, transport=transport(refused))
    assert not r["ok"] and r["message"] and KEY not in r["message"]


async def test_fetch_invalid_json():
    r = await service.fetch("http://lapi.test", KEY, transport=transport(lambda req: httpx.Response(200, text="<html>")))
    assert not r["ok"] and r["message"] == "invalid JSON response"


# --------------------------------------------------------------------------------------------- checks


def ok(answer):
    return {"ok": True, "status": 200, "json": answer, "message": "", "ms": 12.0}


def test_evaluate_first_read_then_new_bans_with_warning():
    e1 = service.evaluate({}, ok(LAPI), 1000, warn_new=2)
    assert e1["ok"] and [c.name for c in e1["checks"]] == ["LAPI"]  # no "New bans" on the first read
    assert e1["metrics"]["cs_local"] == 5 and "cs_new" not in e1["metrics"] and e1["metrics"]["cs_new_total"] == 0
    more = LAPI + [dec(110, "203.0.113.50", "crowdsec", "crowdsecurity/ssh-bf"),
                   dec(111, "203.0.113.51", "crowdsec", "crowdsecurity/ssh-bf")]
    e2 = service.evaluate(e1["state"], ok(more), 1300, warn_new=2)
    new = next(c for c in e2["checks"] if c.name == "New bans")
    assert new.value == 2 and new.state == State.WARN and e2["metrics"]["cs_new"] == 2
    e3 = service.evaluate(e2["state"], ok(more), 1600, warn_new=0)
    assert next(c for c in e3["checks"] if c.name == "New bans").state == State.OK


@pytest.mark.parametrize("res", [
    {"ok": False, "status": 403, "json": None, "message": "HTTP 403 (bouncer key refused)", "ms": 3.0},
    {"ok": False, "status": None, "json": None, "message": "timeout", "ms": None},
    ok({"message": "boom"}),
])
def test_evaluate_failure_is_crit_and_keeps_numbers(res):
    good = service.evaluate({}, ok(LAPI), 1000)
    bad = service.evaluate(good["state"], res, 1300)
    assert not bad["ok"] and bad["metrics"] == {} and bad["scenarios"] is None
    assert [(c.name, c.state) for c in bad["checks"]] == [("LAPI", State.CRIT)]
    assert bad["state"]["stats"]["local"] == 5 and bad["state"]["ok_at"] == 1000  # last good numbers kept


# --------------------------------------------------------------------------------------------- public widget


def test_widget_validation_and_storage():
    w = Widget(id="cs1", type="crowdsec", public_title="Threat protection", crowdsec_ids=[1, 2], limit=3)
    d = dump_widget(w)
    assert d["type"] == "crowdsec" and d["crowdsec_ids"] == [1, 2] and d["limit"] == 3
    assert "crowdsec_ids" not in dump_widget(Widget(id="cs2", type="crowdsec"))


def test_public_widget_has_no_addresses_names_or_urls():
    st = service.evaluate({}, ok(LAPI), 1000)["state"]
    src = SimpleNamespace(state=st, device_id=9, last_ok=datetime.now(UTC), name="crowdsec-lxc.internal",
                          url="http://10.1.2.3:8080")
    data = {**summary.EMPTY, "status": "ok", "state": "OK", "updated_at": src.last_ok, "active": 5, "community": 3,
            "total": 7, "new_24h": 4, "new_7d": 30, "days": [["2026-11-19", 4]],
            "scenarios": logic.merge_scenarios([st["stats"]["scenarios"]])}
    dash = SimpleNamespace(id=1, name="x", public_name="Status", description=None,
                           widgets=[{"id": "cs1", "type": "crowdsec", "size": "m", "public_title": "Proteção"}])
    payload = build_payload(dash, "24h", {}, [], {}, {}, crowdsec={"cs1": data})
    w = payload["widgets"][0]
    assert w["type"] == "crowdsec" and w["title"] == "Proteção" and w["active"] == 5 and w["status"] == "ok"
    assert w["scenarios"][0] == {"key": "crowdsecurity/http-probing", "value": 2}
    assert set(w) == {"id", "type", "size", "title", "state", "status", "updated_at", "since", "active", "community",
                      "total", "new_24h", "new_7d", "days", "scenarios"}
    text = json.dumps(payload, default=str)
    assert not any(x in text for x in IP_LIKE) and "10.1.2.3" not in text and "internal" not in text
    assert payload["summary"]["devices"] == {"up": 0, "down": 0}


def test_public_widget_without_data():
    dash = SimpleNamespace(id=1, name="x", public_name=None, description=None,
                           widgets=[{"id": "cs1", "type": "crowdsec", "size": "s"}])
    w = build_payload(dash, "24h", {}, [], {}, {})["widgets"][0]
    assert w["status"] == "none" and w["active"] == 0 and w["new_24h"] is None and w["title"] == "Threat protection"
