"""Workflow alerts (n8n and friends): payload, auth header, HMAC signature, retries."""

import asyncio
import hashlib
import hmac
import json
from datetime import UTC, datetime

import httpx

from netsync.plugins.base import AlertEvent
from netsync.plugins.builtin import notify

EV = AlertEvent(0, "pve002", "Memory", 0, 2, "97% used", datetime(2026, 11, 15, 10, 0, tzinfo=UTC),
                "http://netsync:8080/devices/4")


def run(config, responses):
    sent = []
    real = httpx.AsyncClient

    def handler(request):
        sent.append(request)
        return httpx.Response(responses.pop(0) if responses else 200)

    class Client(real):
        def __init__(self, **kw):
            super().__init__(transport=httpx.MockTransport(handler), **kw)

    orig, notify.httpx.AsyncClient = notify.httpx.AsyncClient, Client
    orig_sleep = asyncio.sleep

    async def no_sleep(_):
        await orig_sleep(0)

    asyncio.sleep = no_sleep
    try:
        error = None
        try:
            asyncio.run(notify.WorkflowChannel().send(EV, config))
        except Exception as e:  # noqa: BLE001
            error = e
    finally:
        notify.httpx.AsyncClient = orig
        asyncio.sleep = orig_sleep
    return sent, error


def test_payload_is_complete_and_signed():
    sent, error = run({"url": "http://n8n/webhook/x", "auth_header": "X-API-Key", "auth_value": "k1", "signing_secret": "s1"}, [])
    assert error is None and len(sent) == 1
    r = sent[0]
    body = json.loads(r.content)
    assert body["event"] == "problem" and body["state"] == "CRIT" and body["previous_state"] == "OK"
    assert body["device"]["hostname"] == "pve002" and body["service"]["name"] == "Memory"
    assert body["links"]["problems"] == "http://netsync:8080/problems" and "97% used" in body["text"]
    assert r.headers["X-API-Key"] == "k1" and r.headers["X-NETsync-Event"] == "problem"
    want = "sha256=" + hmac.new(b"s1", r.content, hashlib.sha256).hexdigest()
    assert r.headers["X-NETsync-Signature"] == want


def test_retries_server_errors_but_not_client_errors():
    sent, error = run({"url": "http://n8n/x"}, [502, 503, 200])
    assert error is None and len(sent) == 3
    sent, error = run({"url": "http://n8n/x"}, [404])
    assert isinstance(error, httpx.HTTPStatusError) and len(sent) == 1


def test_recovery_and_state_change_names():
    async def payload(old, new):
        return await notify.workflow_payload(AlertEvent(0, "h", "s", old, new, "", EV.time, EV.url))

    assert asyncio.run(payload(2, 0))["event"] == "recovery"
    assert asyncio.run(payload(1, 2))["event"] == "change"
