"""General settings (Settings → General): branding, default time format, what discovery collects, and network
autodiscovery (scan subnets for SNMP agents and add them as devices)."""

from __future__ import annotations

import asyncio
import ipaddress
import json
import logging
import re
import socket
import time
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter
from sqlalchemy import select

from netsync.alerting import redis
from netsync.api.deps import Session, require
from netsync.db import SessionLocal
from netsync.models import Device, Role
from netsync.plugins import settings as plugin_settings
from netsync.plugins.base import BackgroundService, Plugin

log = logging.getLogger(__name__)

NAME = "general"
HEX = re.compile(r"^#[0-9a-fA-F]{6}$")
IMAGE = re.compile(r"^data:image/(png|svg\+xml|jpeg|webp|x-icon|vnd\.microsoft\.icon);base64,[A-Za-z0-9+/=]+$")
MAX_IMAGE = 400_000  # characters of data URL (~300 KB)
MAX_HOSTS = 4096  # per autodiscovery run
STATUS_KEY = "netsync:autodiscovery:last"
RUN_KEY = "netsync:autodiscovery:run"
SYS_NAME, SYS_OID = "1.3.6.1.2.1.1.5.0", "1.3.6.1.2.1.1.2.0"

# component kinds each discovery switch controls
KINDS = {"discover_ports": "port", "discover_storage": "storage", "discover_memory": "mempool",
         "discover_processors": "processor"}

SETTINGS = [
    {"key": "accent_color", "label": "Primary colour", "type": "color", "section": "Branding",
     "help": "Buttons, links, highlights. Empty = NETsync pink."},
    {"key": "logo", "label": "Logo", "type": "image", "section": "Branding",
     "help": "Shown in the sidebar and on the sign-in page instead of the NETsync logo (PNG, SVG, JPG or WebP, up to 300 KB)."},
    {"key": "icon", "label": "Browser icon", "type": "image", "section": "Branding",
     "help": "The tab icon (favicon). Square images work best."},
    {"key": "app_name", "label": "Name", "type": "text", "section": "Branding", "help": "Shown next to the logo and in the browser tab."},
    {"key": "time_format", "label": "Time format", "type": "select", "section": "Defaults",
     "options": [["24h", "24-hour (14:30)"], ["12h", "12-hour (2:30 PM)"]],
     "help": "For users who haven't chosen their own on their profile."},
    {"key": "discover_ports", "label": "Port discovery", "type": "bool", "section": "Discovery",
     "help": "Interfaces and their traffic (IF-MIB)."},
    {"key": "discover_storage", "label": "Storage discovery", "type": "bool", "section": "Discovery",
     "help": "Filesystems and disks (HOST-RESOURCES)."},
    {"key": "discover_memory", "label": "Memory discovery", "type": "bool", "section": "Discovery",
     "help": "Memory pools and the memory check."},
    {"key": "discover_processors", "label": "Processor discovery", "type": "bool", "section": "Discovery",
     "help": "CPUs and threads with their load."},
    {"key": "discover_ip_addresses", "label": "IP address discovery", "type": "bool", "section": "Discovery",
     "help": "IPv4 and IPv6 addresses of each port (IP-MIB)."},
    {"key": "autodiscovery", "label": "Device autodiscovery", "type": "bool", "section": "Autodiscovery",
     "help": "Scan the networks below for SNMP agents and add what answers as new devices."},
    {"key": "autodiscovery_networks", "label": "Networks to scan", "type": "textarea", "section": "Autodiscovery",
     "help": "One network per line, e.g. 10.128.100.0/24. At most 4096 addresses in total."},
    {"key": "autodiscovery_communities", "label": "SNMP communities to try", "type": "secret", "section": "Autodiscovery",
     "help": "Comma separated, tried in order (SNMP v2c)."},
    {"key": "autodiscovery_interval_hours", "label": "Scan every (hours)", "type": "number", "min": 1, "max": 168,
     "section": "Autodiscovery"},
]
DEFAULTS = {
    "accent_color": "", "logo": "", "icon": "", "app_name": "", "time_format": "24h",
    "discover_ports": True, "discover_storage": True, "discover_memory": True, "discover_processors": True,
    "discover_ip_addresses": True,
    "autodiscovery": False, "autodiscovery_networks": "", "autodiscovery_communities": "public",
    "autodiscovery_interval_hours": 24,
}


def networks(text: str) -> list[ipaddress.IPv4Network]:
    out = []
    for line in re.split(r"[\s,;]+", text or ""):
        if line.strip():
            out.append(ipaddress.ip_network(line.strip(), strict=False))
    return out


def validate(cfg: dict[str, Any]) -> None:
    if cfg.get("accent_color") and not HEX.match(cfg["accent_color"]):
        raise ValueError("Primary colour must look like #ff58ae")
    for key in ("logo", "icon"):
        v = cfg.get(key) or ""
        if v and (len(v) > MAX_IMAGE or not IMAGE.match(v)):
            raise ValueError(f"{key.capitalize()} must be a PNG, SVG, JPG or WebP image up to 300 KB")
    try:
        nets = networks(cfg.get("autodiscovery_networks", ""))
    except ValueError as e:
        raise ValueError(f"Networks to scan: {e}") from e
    if any(n.version != 4 for n in nets):
        raise ValueError("Networks to scan: IPv4 only")
    if sum(n.num_addresses for n in nets) > MAX_HOSTS:
        raise ValueError(f"Networks to scan add up to more than {MAX_HOSTS} addresses")
    if cfg.get("autodiscovery") and not nets:
        raise ValueError("Add at least one network to scan, or turn autodiscovery off")


async def get() -> dict[str, Any]:
    _, cfg = await plugin_settings.cached_settings(plugin)
    return {**DEFAULTS, **cfg}


async def disabled_kinds() -> set[str]:
    cfg = await get()
    return {kind for key, kind in KINDS.items() if not cfg.get(key, True)}


# --------------------------------------------------------------------------- autodiscovery

def clean_hostname(name: str | None) -> str | None:
    name = (name or "").strip().lower()
    return name if re.match(r"^[a-z0-9][a-z0-9._-]{0,252}$", name) else None


async def probe(ip: str, communities: list[str]) -> tuple[str, str] | None:
    """(community, sysName) of the first community the agent answers, or None."""
    from netsync.snmp.client import SnmpClient

    for community in communities:
        try:
            got = await SnmpClient(ip, community=community, timeout=1.0, retries=0).get(SYS_NAME, SYS_OID)
        except Exception:  # noqa: BLE001 - silence is the normal answer
            continue
        if got.get(SYS_OID) is not None:
            name = got.get(SYS_NAME)
            return community, name.decode(errors="ignore") if isinstance(name, bytes) else str(name or "")
    return None


async def scan(cfg: dict[str, Any]) -> dict[str, Any]:
    from netsync.poller.worker import enqueue_job

    started = time.monotonic()
    nets = networks(cfg.get("autodiscovery_networks", ""))
    communities = [c.strip() for c in (cfg.get("autodiscovery_communities") or "public").split(",") if c.strip()]
    async with SessionLocal() as s:
        known = set()
        for d in await s.scalars(select(Device)):
            known.add(d.ip or "")
            known.update(d.ip_addresses or [])
            known.add(d.hostname)
        names = set(await s.scalars(select(Device.hostname)))
    targets = [str(h) for n in nets for h in (n.hosts() if n.num_addresses > 2 else n) if str(h) not in known]
    sem = asyncio.Semaphore(64)

    async def one(ip: str):
        async with sem:
            return ip, await probe(ip, communities)

    found = [(ip, hit) for ip, hit in await asyncio.gather(*(one(ip) for ip in targets)) if hit]
    added = []
    async with SessionLocal() as s:
        for ip, (community, sys_name) in found:
            hostname = clean_hostname(sys_name)
            if hostname and "." not in hostname:
                try:  # prefer the DNS name of the address when it resolves
                    hostname = clean_hostname((await asyncio.get_running_loop().getnameinfo((ip, 0)))[0]) or hostname
                except (OSError, socket.gaierror):
                    pass
            hostname = hostname or ip
            if hostname in names:
                hostname = f"{hostname}-{ip}"
            names.add(hostname)
            d = Device(hostname=hostname, ip=ip, snmp_version="2c", snmp_community=community)
            s.add(d)
            await s.flush()
            added.append({"id": d.id, "hostname": hostname, "ip": ip})
        await s.commit()
    for d in added:
        await enqueue_job(d["id"], "discover")
    return {"finished": datetime.now(UTC).isoformat(), "seconds": round(time.monotonic() - started, 1),
            "scanned": len(targets), "answered": len(found), "added": added}


class AutodiscoveryService(BackgroundService):
    name = "autodiscovery"

    async def run(self, stop: asyncio.Event) -> None:
        while not stop.is_set():
            try:
                cfg = await get()
                last = json.loads(await redis().get(STATUS_KEY) or "{}")
                due = time.time() - float(last.get("ts", 0)) > float(cfg.get("autodiscovery_interval_hours", 24)) * 3600
                asked = bool(await redis().lpop(RUN_KEY))
                if asked or (cfg.get("autodiscovery") and due and cfg.get("autodiscovery_networks")):
                    await redis().set(STATUS_KEY, json.dumps({**last, "running": True}))
                    try:
                        result = await scan(cfg)
                    except Exception as e:  # noqa: BLE001 - shown in the settings
                        log.exception("autodiscovery failed")
                        result = {"error": str(e)[:500], "finished": datetime.now(UTC).isoformat()}
                    result["ts"] = time.time()
                    await redis().set(STATUS_KEY, json.dumps(result))
                    if result.get("added"):
                        log.info("autodiscovery added %d devices", len(result["added"]))
            except Exception:  # noqa: BLE001
                log.exception("autodiscovery loop")
            try:
                await asyncio.wait_for(stop.wait(), timeout=30)
            except TimeoutError:
                pass


# --------------------------------------------------------------------------- API

router = APIRouter()


@router.get("/branding")
async def branding():
    """Public (the sign-in page needs it): colour, logo, icon, name, default time format."""
    cfg = await get()
    return {k: cfg.get(k) or None for k in ("accent_color", "logo", "icon", "app_name", "time_format")}


@router.get("/autodiscovery", dependencies=[require(Role.ADMIN)])
async def autodiscovery_status():
    return json.loads(await redis().get(STATUS_KEY) or "{}")


@router.post("/autodiscovery/run", dependencies=[require(Role.ADMIN)])
async def autodiscovery_run(session: Session):
    _, cfg = await plugin_settings.get_settings(session, plugin)
    if not networks(cfg.get("autodiscovery_networks", "")):
        return {"ok": False, "message": "Add a network to scan first"}
    await redis().rpush(RUN_KEY, "1")
    return {"ok": True, "message": "Scan started; new devices appear in a minute or two."}


plugin = Plugin(
    name=NAME,
    label="General",
    version="1.0.0",
    description="Branding, defaults, discovery switches and network autodiscovery",
    services=[AutodiscoveryService()],
    router=router,
    builtin=True,
    settings=SETTINGS,
    defaults=DEFAULTS,
    validate=validate,
    actions=[{"id": "scan", "label": "Scan networks now", "method": "POST", "path": "/autodiscovery/run"}],
)
