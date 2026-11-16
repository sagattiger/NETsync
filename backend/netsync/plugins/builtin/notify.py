"""Built-in notification channels: email, Telegram, generic webhook, workflows (n8n and friends)."""

from email.message import EmailMessage

import aiosmtplib
import httpx

from netsync.config import get_settings
from netsync.models import State
from netsync.plugins.base import AlertEvent, NotificationChannel


def subject(e: AlertEvent) -> str:
    return f"[NETsync] {State(e.new_state).name} - {e.hostname} / {e.service}"


def body(e: AlertEvent) -> str:
    return (
        f"Device:  {e.hostname}\n"
        f"Service: {e.service}\n"
        f"State:   {State(e.old_state).name} -> {State(e.new_state).name}\n"
        f"Output:  {e.output}\n"
        f"Time:    {e.time:%Y-%m-%d %H:%M:%S %Z}\n"
        f"Link:    {e.url}\n"
    )


class EmailChannel(NotificationChannel):
    name = "email"
    label = "Email"
    config_fields = [{"key": "to", "label": "Recipients (comma separated)", "type": "text", "required": True}]

    async def send(self, event, config):
        s = get_settings()
        msg = EmailMessage()
        msg["From"] = s.smtp_from
        msg["To"] = config["to"]
        msg["Subject"] = subject(event)
        msg.set_content(body(event))
        await aiosmtplib.send(
            msg,
            hostname=s.smtp_host,
            port=s.smtp_port,
            username=s.smtp_user or None,
            password=s.smtp_password or None,
            start_tls=s.smtp_port == 587,
        )


class TelegramChannel(NotificationChannel):
    name = "telegram"
    label = "Telegram"
    config_fields = [
        {"key": "bot_token", "label": "Bot token", "type": "secret", "required": True},
        {"key": "chat_id", "label": "Chat ID", "type": "text", "required": True},
    ]

    async def send(self, event, config):
        icon = {0: "✅", 1: "⚠️", 2: "\U0001f534", 3: "❔"}[event.new_state]
        text = f"{icon} *{subject(event)}*\n{event.output}\n{event.url}"
        async with httpx.AsyncClient(timeout=10) as c:
            r = await c.post(
                f"https://api.telegram.org/bot{config['bot_token']}/sendMessage",
                json={"chat_id": config["chat_id"], "text": text, "parse_mode": "Markdown"},
            )
            r.raise_for_status()


class WebhookChannel(NotificationChannel):
    name = "webhook"
    label = "Webhook (JSON POST)"
    config_fields = [
        {"key": "url", "label": "URL", "type": "text", "required": True},
        {"key": "secret", "label": "Bearer token (optional)", "type": "secret"},
    ]

    async def send(self, event, config):
        headers = {"Authorization": f"Bearer {config['secret']}"} if config.get("secret") else {}
        payload = {
            "device_id": event.device_id,
            "hostname": event.hostname,
            "service": event.service,
            "old_state": State(event.old_state).name,
            "new_state": State(event.new_state).name,
            "output": event.output,
            "time": event.time.isoformat(),
            "url": event.url,
        }
        async with httpx.AsyncClient(timeout=10) as c:
            r = await c.post(config["url"], json=payload, headers=headers)
            r.raise_for_status()


# --------------------------------------------------------------------------- workflows (n8n, Make, Zapier, Node-RED…)

EVENT_NAMES = {True: "recovery", False: "problem"}


async def workflow_payload(event: AlertEvent) -> dict:
    """Everything a workflow needs to route an alert without calling NETsync back."""
    from sqlalchemy import select

    from netsync import __version__
    from netsync.db import SessionLocal
    from netsync.models import Device, Service, Site

    device = svc = site = None
    try:
        async with SessionLocal() as s:
            device = await s.get(Device, event.device_id) if event.device_id else None
            if device:
                svc = await s.scalar(select(Service).where(Service.device_id == device.id, Service.name == event.service))
                site = await s.get(Site, device.site_id) if device.site_id else None
    except Exception:  # noqa: BLE001 - send what we have
        pass
    recovered = event.new_state == State.OK
    kind = EVENT_NAMES[recovered] if event.old_state == State.OK or recovered else "change"
    state, prev = State(event.new_state).name, State(event.old_state).name
    summary = f"{state} - {event.hostname} / {event.service}: {event.output}"
    base = event.url.split("/devices/")[0]
    return {
        "event": kind,  # problem | recovery | change (WARN <-> CRIT)
        "summary": summary,
        "text": summary,  # Slack / Mattermost / Chatwoot style consumers read "text"
        "state": state, "previous_state": prev, "severity": int(event.new_state),
        "time": event.time.isoformat(),
        "device": {
            "id": event.device_id, "hostname": event.hostname,
            "ip": device.ip if device else None, "os": device.os if device else None,
            "type": device.device_type if device else None, "location": device.sys_location if device else None,
            "site": site.name if site else None,
            "lat": (site.lat if site and site.lat is not None else device.lat) if device else None,
            "lon": (site.lon if site and site.lon is not None else device.lon) if device else None,
            "groups": [g.name for g in device.groups] if device else [],
        },
        "service": {
            "id": svc.id if svc else None, "name": event.service, "check": svc.check if svc else None,
            "output": event.output, "values": svc.perf if svc else {},
            "acknowledged": bool(svc.acknowledged) if svc else False,
        },
        "links": {"device": event.url, "problems": f"{base}/problems"},
        "netsync": {"version": __version__, "url": base},
    }


class WorkflowChannel(NotificationChannel):
    name = "workflow"
    label = "Workflow (n8n, Make, Zapier, Node-RED…)"
    config_fields = [
        {"key": "url", "label": "Webhook URL", "type": "text", "required": True,
         "help": "The URL of the workflow's webhook trigger, e.g. https://n8n.example.com/webhook/netsync"},
        {"key": "auth_header", "label": "Auth header name (optional)", "type": "text",
         "help": "e.g. Authorization or X-API-Key, for webhooks protected by header auth"},
        {"key": "auth_value", "label": "Auth header value (optional)", "type": "secret"},
        {"key": "signing_secret", "label": "Signing secret (optional)", "type": "secret",
         "help": "Adds X-NETsync-Signature: sha256=<HMAC of the body> so the workflow can check the sender"},
    ]

    async def send(self, event, config):
        import hashlib
        import hmac
        import json

        payload = await workflow_payload(event)
        body = json.dumps(payload, default=str).encode()
        headers = {"Content-Type": "application/json", "User-Agent": "NETsync", "X-NETsync-Event": payload["event"]}
        if config.get("auth_header") and config.get("auth_value"):
            headers[config["auth_header"].strip()] = config["auth_value"]
        if config.get("signing_secret"):
            sig = hmac.new(config["signing_secret"].encode(), body, hashlib.sha256).hexdigest()
            headers["X-NETsync-Signature"] = f"sha256={sig}"
        last: Exception | None = None
        for attempt in range(3):  # workflows restart; try a few times before giving up
            try:
                async with httpx.AsyncClient(timeout=15) as c:
                    r = await c.post(config["url"], content=body, headers=headers)
                if r.status_code < 500:
                    r.raise_for_status()
                    return
                last = httpx.HTTPStatusError(f"HTTP {r.status_code}", request=r.request, response=r)
            except (httpx.TransportError, httpx.TimeoutException) as e:
                last = e
            import asyncio

            await asyncio.sleep(1 + attempt * 2)
        raise last or RuntimeError("workflow did not answer")
