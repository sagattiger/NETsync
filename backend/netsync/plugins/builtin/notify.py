"""Built-in notification channels: email, Telegram, generic webhook."""

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
