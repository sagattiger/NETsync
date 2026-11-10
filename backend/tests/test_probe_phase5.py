"""Uptime Kuma backup mapping (tests/fixtures/kuma_backup.json)."""

import json
from pathlib import Path

import pytest

from netsync.api.probes import ProbeIn
from netsync.probing.kuma import map_backup

BACKUP = json.loads((Path(__file__).parent / "fixtures" / "kuma_backup.json").read_text())


@pytest.fixture
def mapped():
    return map_backup(BACKUP)


def by_name(mapped):
    out = {}
    for i in mapped["create"]:
        out.setdefault(i["payload"]["name"], i)  # first one wins, like the API (duplicates are skipped there)
    return out


def test_supported_monitors_are_mapped(mapped):
    items = by_name(mapped)
    web = items["Website"]["payload"]
    assert web["kind"] == "http" and web["target"] == "https://www.example.com/"
    assert web["config"]["accepted_codes"] == "200-299,301" and web["config"]["max_redirects"] == 10
    assert web["retries"] == 3 and web["retry_interval_s"] == 30 and web["interval_s"] == 60
    assert web["timeout_s"] == 48 and web["tags"] == ["web", "env:prod"] and web["description"] == "Public site"
    assert web["secrets"] == {"headers": {"X-Api-Key": "SECRET-HEADER"}}
    assert any("certificate expiry" in w for w in items["Website"]["warnings"])

    kw = items["Status keyword"]["payload"]
    assert kw["config"]["keyword"] == "Operational" and not kw["config"]["keyword_absent"] and kw["retries"] == 1
    assert kw["config"]["auth"] == "basic" and kw["secrets"]["password"] == "SECRET-BASIC"
    neg = items["No errors"]["payload"]
    assert neg["config"]["keyword_absent"] is True and neg["enabled"] is False

    api = items["API health"]["payload"]
    assert api["kind"] == "json" and api["config"]["method"] == "POST" and api["config"]["body_type"] == "json"
    assert api["config"]["assertions"] == [{"path": "data.status", "op": "==", "value": "ok"}]
    jsonata = items["API JSONata"]
    assert "assertions" not in jsonata["payload"]["config"] and any("JSONata" in w for w in jsonata["warnings"])

    assert (items["SSH"]["payload"]["kind"], items["SSH"]["payload"]["port"]) == ("tcp", 22)
    assert items["Telnet closed"]["payload"]["upside_down"] is True
    gw = items["Gateway"]
    assert gw["payload"]["kind"] == "icmp" and gw["payload"]["interval_s"] == 20 and gw["payload"]["retries"] == 4
    assert any("interval 10s" in w for w in gw["warnings"])
    mx = items["MX record"]["payload"]
    assert mx["kind"] == "dns" and mx["config"] == {"record_type": "MX", "resolver": "1.1.1.1", "resolver_port": 53}
    push = items["Nightly backup"]
    assert push["payload"]["kind"] == "push" and push["payload"]["interval_s"] == 3600
    assert any("new push URL" in w for w in push["warnings"])


def test_unsupported_types_are_skipped_with_a_reason(mapped):
    skipped = {s["name"]: s["reason"] for s in mapped["skipped"]}
    assert "group" in skipped["Containers"] and "docker" in skipped["Redis container"]


def test_notifications_listed_without_secrets(mapped):
    assert mapped["notifications"] == [{"name": "Ops Telegram", "type": "telegram"}, {"name": "Mail", "type": "smtp"}]
    text = json.dumps(mapped["notifications"])
    assert "SECRET" not in text


def test_payloads_validate_like_the_api(mapped):
    ok, bad = [], []
    for item in mapped["create"]:
        try:
            ok.append(ProbeIn(**item["payload"]).name)
        except Exception:  # noqa: BLE001
            bad.append(item["payload"]["name"])
    assert bad == ["Broken URL"]  # ftp:// is not allowed -> the API reports it as skipped
    assert "API health" in ok and "Nightly backup" in ok


def test_not_a_backup():
    for bad in ({}, {"monitorList": "x"}, [], "text"):
        with pytest.raises(ValueError):
            map_backup(bad)


async def test_api_plan_skips_duplicates_and_invalid():
    from netsync.api.probes import _kuma_plan, _public_plan

    class FakeSession:
        async def scalars(self, q):
            return ["SSH"]  # already exists in NETsync

    create, skipped, notifications = await _kuma_plan(FakeSession(), BACKUP)
    names = [c["name"] for c in create]
    reasons = {s["name"]: s["reason"] for s in skipped}
    assert names.count("Website") == 1 and "SSH" not in names
    assert reasons["SSH"] == "a probe with this name already exists"
    assert "Website" in reasons and "only http:// and https://" in reasons["Broken URL"]
    assert len(notifications) == 2 and all("_body" not in c for c in _public_plan(create))
