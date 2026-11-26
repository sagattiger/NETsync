"""General settings (Settings → General): branding, defaults, what discovery collects and ignores, network
autodiscovery, entities, alerting, sign-in and network options. Stored as the settings of the built-in "general"
plugin; every field names the sub-tab (``tab``) and card (``section``) it is shown in."""

from __future__ import annotations

import asyncio
import ipaddress
import json
import logging
import re
import socket
import time
from datetime import UTC, datetime
from functools import lru_cache
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
SYS_DESCR, SYS_NAME, SYS_OID = "1.3.6.1.2.1.1.1.0", "1.3.6.1.2.1.1.5.0", "1.3.6.1.2.1.1.2.0"

# component kinds each discovery switch controls
KINDS = {"discover_ports": "port", "discover_storage": "storage", "discover_memory": "mempool",
         "discover_processors": "processor"}

# IANA ifType names (the ones worth ignoring, and the common ones)
IF_TYPES = {
    "other": 1, "ethernetCsmacd": 6, "iso88025TokenRing": 9, "ds1": 18, "e1": 19, "propPointToPointSerial": 22,
    "ppp": 23, "softwareLoopback": 24, "ds3": 30, "frameRelay": 32, "rs232": 33, "sonet": 39, "aal5": 49,
    "propVirtual": 53, "propMultiplexor": 54, "fastEther": 62, "isdn": 63, "ieee80211": 71, "lapd": 77, "ds0": 81,
    "ds0Bundle": 82, "adsl": 94, "voiceEM": 100, "voiceFXO": 101, "voiceFXS": 102, "voiceEncap": 103,
    "voiceOverIp": 104, "gigabitEthernet": 117, "docsCableMaclayer": 127, "tunnel": 131, "atmSubInterface": 134,
    "l2vlan": 135, "l3ipvlan": 136, "ipForward": 142, "ieee1394": 144, "mplsTunnel": 150, "voiceOverAtm": 152,
    "voiceOverFrameRelay": 153, "usb": 160, "ieee8023adLag": 161, "mpls": 166, "shdsl": 169, "pos": 171,
    "bridge": 209, "adsl2plus": 238, "vdsl2": 251, "atm": 37,
}

# IP address types, checked in this order (the first that matches wins)
IP_TYPES = [
    ("unspecified", "Unspecified"), ("loopback", "Loopback"), ("ipv4-mapped", "IPv6 IPv4-Mapped"),
    ("ipv4-embedded", "IPv6 IPv4-Embedded"), ("6to4", "IPv6 6to4"), ("teredo", "IPv6 Teredo"),
    ("orchid", "IPv6 Orchid"), ("benchmarking", "Benchmarking"), ("documentation", "Documentation"),
    ("cgnat", "Carrier Grade NAT (CGNAT)"), ("link-local", "Link-Local Addresses"), ("multicast", "Multicast"),
    ("private", "Private Local Addresses"), ("broadcast", "IPv4 Broadcast"), ("anycast", "Anycast"),
    ("reserved", "Reserved"), ("global", "Global Unicast"),
]
NETS = {
    "ipv4-embedded": ["64:ff9b::/96"], "6to4": ["2002::/16"], "teredo": ["2001::/32"],
    "orchid": ["2001:10::/28", "2001:20::/28"], "benchmarking": ["198.18.0.0/15", "2001:2::/48"],
    "documentation": ["192.0.2.0/24", "198.51.100.0/24", "203.0.113.0/24", "2001:db8::/32"],
    "cgnat": ["100.64.0.0/10"], "link-local": ["169.254.0.0/16", "fe80::/10"],
    "private": ["10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "fc00::/7"],
}
NETS = {k: [ipaddress.ip_network(n) for n in v] for k, v in NETS.items()}


def _f(key, label, type_, tab, section, help_=None, **extra):
    return {"key": key, "label": label, "type": type_, "tab": tab, "section": section,
            **({"help": help_} if help_ else {}), **extra}


ONE_PER_LINE = "One per line."
REGEX_HELP = "One per line, like /^eth[0-9]+$/i (flags: i, m, s, x)."

SETTINGS = [
    # ---- Branding
    _f("accent_color", "Primary colour", "color", "Branding", "Branding", "Buttons, links, highlights. Empty = NETsync blue (#12B8FF)."),
    _f("logo", "Logo (light theme)", "image", "Branding", "Branding",
       "Shown in the sidebar and on the sign-in page instead of the NETsync logo, on the light theme "
       "(PNG, SVG, JPG or WebP, up to 300 KB). Also used on the dark theme when there's no dark logo."),
    _f("logo_dark", "Logo (dark theme)", "image", "Branding", "Branding",
       "The same logo for the dark theme, e.g. with light text. Empty = the light-theme logo is used on both."),
    _f("icon", "Browser icon", "image", "Branding", "Branding", "The tab icon (favicon). Square images work best."),
    _f("app_name", "Name", "text", "Branding", "Branding", "Shown next to the logo and in the browser tab."),
    _f("time_format", "Time format", "select", "Branding", "Defaults", "For users who haven't chosen their own on their profile.",
       options=[["24h", "24-hour (14:30)"], ["12h", "12-hour (2:30 PM)"]]),
    # ---- Discovery: modules
    _f("discover_ports", "Port discovery", "bool", "Discovery", "What discovery collects", "Interfaces and their traffic (IF-MIB)."),
    _f("discover_storage", "Storage discovery", "bool", "Discovery", "What discovery collects", "Filesystems and disks (HOST-RESOURCES)."),
    _f("discover_memory", "Memory discovery", "bool", "Discovery", "What discovery collects", "Memory pools and the memory check."),
    _f("discover_processors", "Processor discovery", "bool", "Discovery", "What discovery collects", "CPUs and threads with their load."),
    _f("discover_ip_addresses", "IP address discovery", "bool", "Discovery", "What discovery collects", "IPv4 and IPv6 addresses of each port (IP-MIB)."),
    # ---- Discovery: ports
    _f("ports_ignore_regex", "Ignore ports by ifName/ifDescr (regular expression)", "textarea", "Discovery", "Port discovery",
       "Ports whose ifName or ifDescr match are ignored. " + REGEX_HELP, placeholder="/^eth[0-9]+$/"),
    _f("ports_ignore_string", "Ignore ports by ifName/ifDescr (contains)", "textarea", "Discovery", "Port discovery",
       "Ports whose ifName or ifDescr contain one of these are ignored. " + ONE_PER_LINE, placeholder="pppoe-"),
    _f("ports_ignore_alias_regex", "Ignore ports by ifAlias (regular expression)", "textarea", "Discovery", "Port discovery",
       "Ports whose description (ifAlias) matches are ignored. " + REGEX_HELP, placeholder="/^Transit:/"),
    _f("ports_ignore_types", "Ignore ports by ifType", "multi", "Discovery", "Port discovery",
       "Ports of the selected types are ignored.", options=[[k, k] for k in sorted(IF_TYPES, key=str.lower)]),
    # ---- Discovery: storage
    _f("storage_ignore_removable", "Ignore removable mounted storage", "bool", "Discovery", "Storage discovery",
       "As reported by the device's SNMP agent (hrStorageRemovableDisk, floppy)."),
    _f("storage_ignore_optical", "Ignore optical mounted storage", "bool", "Discovery", "Storage discovery",
       "CD/DVD drives (hrStorageCompactDisc)."),
    _f("storage_ignore_network", "Ignore network mounted storage", "bool", "Discovery", "Storage discovery",
       "Usually NFS and SMB mounts (hrStorageNetworkDisk)."),
    _f("storage_ignore_exact", "Ignore storage by name (exact)", "textarea", "Discovery", "Storage discovery", ONE_PER_LINE, placeholder="/proc"),
    _f("storage_ignore_string", "Ignore storage by name (contains)", "textarea", "Discovery", "Storage discovery", ONE_PER_LINE, placeholder="procfs"),
    _f("storage_ignore_regex", "Ignore storage by name (regular expression)", "textarea", "Discovery", "Storage discovery", REGEX_HELP),
    # ---- Discovery: processors
    _f("processor_ignore_exact", "Ignore processor by name (exact)", "textarea", "Discovery", "Processor discovery",
       "Matched against the name (CPU 0) and the model. " + ONE_PER_LINE, placeholder="Cached Processor"),
    _f("processor_ignore_string", "Ignore processor by name (contains)", "textarea", "Discovery", "Processor discovery", ONE_PER_LINE, placeholder="Cache"),
    _f("processor_ignore_regex", "Ignore processor by name (regular expression)", "textarea", "Discovery", "Processor discovery", REGEX_HELP),
    # ---- Discovery: sensors
    _f("sensor_ignore_exact", "Ignore sensor by name (exact)", "textarea", "Discovery", "Sensor discovery", ONE_PER_LINE, placeholder="Outside Temperature"),
    _f("sensor_ignore_string", "Ignore sensor by name (contains)", "textarea", "Discovery", "Sensor discovery", ONE_PER_LINE, placeholder="Outside"),
    _f("sensor_ignore_regex", "Ignore sensor by name (regular expression)", "textarea", "Discovery", "Sensor discovery", REGEX_HELP),
    # ---- Discovery: IP addresses
    _f("ip_ignore_types", "Ignore IP addresses by type", "multi", "Discovery", "IP address discovery",
       "Addresses of the selected types are left out of each port's address list.", options=[list(t) for t in IP_TYPES]),
    # ---- Discovery: autodiscovery
    _f("autodiscovery", "Device autodiscovery", "bool", "Discovery", "Device autodiscovery",
       "Scan the networks below for SNMP agents and add what answers as new devices."),
    _f("autodiscovery_networks", "Networks to permit autodiscovery", "textarea", "Discovery", "Device autodiscovery",
       "Scanned for new devices; nothing outside them is added. One IPv4 network per line, at most 4096 addresses in total.",
       placeholder="10.0.0.0/24"),
    _f("autodiscovery_communities", "SNMP communities to try", "secret", "Discovery", "Device autodiscovery",
       "Comma separated, tried in order (SNMP v2c)."),
    _f("autodiscovery_interval_hours", "Scan every (hours)", "number", "Discovery", "Device autodiscovery", min=1, max=168),
    _f("autodiscovery_domain", "Domain name to add to autodiscovered hosts", "text", "Discovery", "Device autodiscovery",
       "Appended to short names, e.g. example.com turns sw01 into sw01.example.com.", placeholder="example.com"),
    _f("autodiscovery_require_hostname", "Require valid hostname", "bool", "Discovery", "Device autodiscovery",
       "Only add devices whose name resolves (DNS or hosts file); never add one by its IP address."),
    _f("autodiscovery_skip_icmp", "Skip ICMP echo checks", "bool", "Discovery", "Device autodiscovery",
       "Ask every address over SNMP, not only the ones that answer ping (slower; for networks that drop ping)."),
    _f("autodiscovery_block_hostname", "Block by hostname", "textarea", "Discovery", "Device autodiscovery",
       ONE_PER_LINE, placeholder="badhost.example.com"),
    _f("autodiscovery_block_hostname_regex", "Block by hostname (regular expression)", "textarea", "Discovery", "Device autodiscovery",
       REGEX_HELP, placeholder="/^badhost.*/"),
    _f("autodiscovery_block_platform", "Block by platform (contains)", "textarea", "Discovery", "Device autodiscovery",
       "Matched against the system description (sysDescr). " + ONE_PER_LINE, placeholder="Cisco IP Phone"),
    _f("autodiscovery_block_platform_regex", "Block by platform (regular expression)", "textarea", "Discovery", "Device autodiscovery",
       REGEX_HELP, placeholder="/^Cisco IP Phone/"),
    # ---- Entities
    _f("ports_monitor_up_only", "Monitor new ports only when up", "bool", "Entities", "Ports",
       "A port found down at discovery gets no service (no alert) until you turn monitoring on."),
    _f("entity_missing_discoveries", "Remove missing entities after (discoveries)", "number", "Entities", "All entities",
       "Ports, disks, sensors and so on that a device stops reporting are removed after this many discoveries in a row.",
       min=1, max=10),
    # ---- Alerting
    _f("alert_skip_acknowledged", "No notifications for acknowledged problems", "bool", "Alerting", "Notifications",
       "An acknowledged problem that changes state (WARN ↔ CRIT) stays quiet; its recovery is still sent."),
    _f("alert_skip_downtime", "No notifications during scheduled downtime", "bool", "Alerting", "Notifications"),
    # ---- Authentication
    _f("session_hours", "Stay signed in for (hours)", "number", "Authentication", "Sessions",
       "How long a sign-in lasts before asking for the password again.", min=1, max=720),
    _f("login_lockout_attempts", "Lock after failed sign-ins", "number", "Authentication", "Sign-in protection",
       "Failed attempts for one user name from one address before it is locked. 0 = never.", min=0, max=100),
    _f("login_lockout_minutes", "Lock for (minutes)", "number", "Authentication", "Sign-in protection", min=1, max=1440),
    # ---- Network
    _f("snmp_timeout", "SNMP timeout (seconds)", "number", "Network", "SNMP",
       "How long to wait for each SNMP answer.", min=0.5, max=30, float=True),
    _f("snmp_retries", "SNMP retries", "number", "Network", "SNMP", "Extra tries after a timeout.", min=0, max=5),
    _f("public_url", "NETsync address", "text", "Network", "Links",
       "The address people open NETsync at; used in links inside notifications and push URLs. Empty = the server's setting.",
       placeholder="https://netsync.example.com"),
]
TABS = ["Branding", "Discovery", "Entities", "Alerting", "Authentication", "Network"]

DEFAULTS = {
    "accent_color": "", "logo": "", "logo_dark": "", "icon": "", "app_name": "", "time_format": "24h",
    "discover_ports": True, "discover_storage": True, "discover_memory": True, "discover_processors": True,
    "discover_ip_addresses": True,
    "ports_ignore_regex": "\n".join([r"/^ng[0-9]+$/i", r"/^sl[0-9]/i", r"/^lp0/", r"/^<(none|invalid)>$/i",
                                     r"/^<(invalid|ethportany):[\d-]+>$/i", r"/^(ZTPCONFIG|TopoNode|SYSLOG)=/i",
                                     r"/^\s*CPU Interface for Unit/"]),
    "ports_ignore_string": "\n".join(["voip-null", "virtual-", "unrouted", "eobc", "-atm", "faith0", "container",
                                      "async", "plip", "-physical", "bluetooth", "isatap", "qos", "span rp", "span sp",
                                      "sslvpn", "pppoe-", "ovs-system", "BRG-ET"]),
    "ports_ignore_alias_regex": "",
    "ports_ignore_types": ["voiceEncap", "voiceEM", "voiceOverAtm", "voiceOverFrameRelay", "voiceOverIp", "ds0", "ds1",
                           "ds3", "atmSubInterface", "aal5", "shdsl", "mpls", "usb"],
    "storage_ignore_removable": True, "storage_ignore_optical": True, "storage_ignore_network": False,
    "storage_ignore_exact": "\n".join(["/kern", "/mnt/cdrom", "/proc", "/dev", "/dev/shm", "/run"]),
    "storage_ignore_string": "\n".join(["packages", "devfs", "procfs", "UMA", "MALLOC"]),
    "storage_ignore_regex": "",
    "processor_ignore_exact": "", "processor_ignore_string": "", "processor_ignore_regex": "",
    "sensor_ignore_exact": "", "sensor_ignore_string": "",
    "sensor_ignore_regex": "\n".join([r"/(OSR\-7600|C6K) Clock FRU \d/", r"/^Chassis \d+ clock \d clock/"]),
    "ip_ignore_types": ["unspecified", "loopback", "link-local", "multicast", "broadcast"],
    "autodiscovery": False, "autodiscovery_networks": "", "autodiscovery_communities": "public",
    "autodiscovery_interval_hours": 24, "autodiscovery_domain": "", "autodiscovery_require_hostname": False,
    "autodiscovery_skip_icmp": False, "autodiscovery_block_hostname": "", "autodiscovery_block_hostname_regex": "",
    "autodiscovery_block_platform": "Cisco IP Phone",
    "autodiscovery_block_platform_regex": "\n".join([r"/^Not received$/", r"/^SIP\-CP\d+/"]),
    "ports_monitor_up_only": True, "entity_missing_discoveries": 2,
    "alert_skip_acknowledged": True, "alert_skip_downtime": True,
    "session_hours": 12, "login_lockout_attempts": 5, "login_lockout_minutes": 15,
    "snmp_timeout": 2.0, "snmp_retries": 1, "public_url": "",
}

# ------------------------------------------------------------------------------- parsing helpers


def lines(text: str | None) -> list[str]:
    return [ln.strip() for ln in (text or "").splitlines() if ln.strip()]


FLAGS = {"i": re.I, "m": re.M, "s": re.S, "x": re.X}


def regex(line: str) -> re.Pattern:
    """``/pattern/flags`` (as in Observium) or a bare pattern."""
    m = re.fullmatch(r"/(.*)/([a-zA-Z]*)", line, re.S)
    if not m:
        return re.compile(line)
    flags = 0
    for ch in m.group(2):
        flags |= FLAGS.get(ch.lower(), 0)
    return re.compile(m.group(1), flags)


@lru_cache(maxsize=64)
def regexes(text: str) -> tuple[re.Pattern, ...]:
    return tuple(regex(ln) for ln in lines(text))


def networks(text: str) -> list[ipaddress.IPv4Network]:
    return [ipaddress.ip_network(part.strip(), strict=False) for part in re.split(r"[\s,;]+", text or "") if part.strip()]


def ip_type(addr: str) -> str:
    """The type of one address, optionally with a prefix (10.0.0.255/24), as in IP_TYPES."""
    try:
        iface = ipaddress.ip_interface(addr)
    except ValueError:
        return "reserved"
    ip = iface.ip
    if ip.is_unspecified:
        return "unspecified"
    if ip.is_loopback:
        return "loopback"
    if ip.version == 6 and ip.ipv4_mapped:
        return "ipv4-mapped"
    for kind in ("ipv4-embedded", "6to4", "teredo", "orchid", "benchmarking", "documentation", "cgnat", "link-local"):
        if any(ip.version == n.version and ip in n for n in NETS[kind]):
            return kind
    if ip.is_multicast:
        return "multicast"
    if any(ip.version == n.version and ip in n for n in NETS["private"]):
        return "private"
    net = iface.network
    if ip.version == 4 and (str(ip) == "255.255.255.255" or (net.prefixlen < 31 and ip == net.broadcast_address)):
        return "broadcast"
    if ip.version == 6 and net.prefixlen < 127 and ip == net.network_address:
        return "anycast"  # subnet-router anycast
    if ip.is_reserved or ip.is_private:
        return "reserved"
    return "global"


def check_regexes(label: str, text: str) -> None:
    for ln in lines(text):
        try:
            regex(ln)
        except re.error as e:
            raise ValueError(f"{label}: {ln} is not a valid regular expression ({e})") from e


def validate(cfg: dict[str, Any]) -> None:
    if cfg.get("accent_color") and not HEX.match(cfg["accent_color"]):
        raise ValueError("Primary colour must look like #12b8ff")
    for key, label in (("logo", "Logo (light theme)"), ("logo_dark", "Logo (dark theme)"), ("icon", "Browser icon")):
        v = cfg.get(key) or ""
        if v and (len(v) > MAX_IMAGE or not IMAGE.match(v)):
            raise ValueError(f"{label} must be a PNG, SVG, JPG or WebP image up to 300 KB")
    for f in SETTINGS:
        if "regular expression" in f["label"]:
            check_regexes(f["label"], cfg.get(f["key"], ""))
    try:
        nets = networks(cfg.get("autodiscovery_networks", ""))
    except ValueError as e:
        raise ValueError(f"Networks to permit autodiscovery: {e}") from e
    if any(n.version != 4 for n in nets):
        raise ValueError("Networks to permit autodiscovery: IPv4 only")
    if sum(n.num_addresses for n in nets) > MAX_HOSTS:
        raise ValueError(f"Networks to permit autodiscovery add up to more than {MAX_HOSTS} addresses")
    if cfg.get("autodiscovery") and not nets:
        raise ValueError("Add at least one network to scan, or turn autodiscovery off")
    domain = (cfg.get("autodiscovery_domain") or "").strip().strip(".")
    if domain and not re.fullmatch(r"[a-zA-Z0-9]([a-zA-Z0-9-]*[a-zA-Z0-9])?(\.[a-zA-Z0-9]([a-zA-Z0-9-]*[a-zA-Z0-9])?)*", domain):
        raise ValueError("Domain name: letters, digits, dots and hyphens only")
    url = (cfg.get("public_url") or "").strip()
    if url and not re.match(r"^https?://[^\s/]+", url):
        raise ValueError("NETsync address must start with http:// or https://")


# ------------------------------------------------------------------------------- reading the settings

_current: dict[str, Any] = dict(DEFAULTS)


async def get() -> dict[str, Any]:
    global _current
    _, cfg = await plugin_settings.cached_settings(plugin)
    _current = {**DEFAULTS, **cfg}
    return _current


def current() -> dict[str, Any]:
    """The last settings read by get() in this process (for code that can't await, e.g. the SNMP client)."""
    return _current


def public_url() -> str:
    from netsync.config import get_settings

    return ((_current.get("public_url") or "").strip() or get_settings().public_url).rstrip("/")


async def disabled_kinds() -> set[str]:
    cfg = await get()
    return {kind for key, kind in KINDS.items() if not cfg.get(key, True)}


# ------------------------------------------------------------------------------- discovery filters


def _match(names: list[str], cfg: dict[str, Any], prefix: str) -> bool:
    names = [n for n in names if n]
    exact = set(lines(cfg.get(f"{prefix}_ignore_exact")))
    if any(n in exact for n in names):
        return True
    subs = [s.lower() for s in lines(cfg.get(f"{prefix}_ignore_string"))]
    if any(s in n.lower() for n in names for s in subs):
        return True
    return any(r.search(n) for n in names for r in regexes(cfg.get(f"{prefix}_ignore_regex") or ""))


def ignored(spec, cfg: dict[str, Any]) -> bool:
    """True when the settings say discovery should leave this component out."""
    attrs = spec.attrs or {}
    if spec.kind == "port":
        names = [spec.name, attrs.get("if_descr") or ""]
        if any(r.search(n) for n in names if n for r in regexes(cfg.get("ports_ignore_regex") or "")):
            return True
        subs = [s.lower() for s in lines(cfg.get("ports_ignore_string"))]
        if any(s in n.lower() for n in names if n for s in subs):
            return True
        if spec.descr and any(r.search(spec.descr) for r in regexes(cfg.get("ports_ignore_alias_regex") or "")):
            return True
        types = {IF_TYPES[t] for t in cfg.get("ports_ignore_types") or [] if t in IF_TYPES}
        return attrs.get("if_type") in types
    if spec.kind == "storage":
        kind = attrs.get("storage_type")
        if kind in ("removable", "optical", "network") and cfg.get(f"storage_ignore_{kind}"):
            return True
        return _match([spec.name], cfg, "storage")
    if spec.kind == "processor":
        return _match([spec.name, spec.descr or ""], cfg, "processor")
    if spec.kind == "sensor":
        return _match([spec.name], cfg, "sensor")
    return False


def keep_address(addr: str, cfg: dict[str, Any]) -> bool:
    return ip_type(addr) not in set(cfg.get("ip_ignore_types") or [])


# ------------------------------------------------------------------------------- autodiscovery


def clean_hostname(name: str | None) -> str | None:
    name = (name or "").strip().lower()
    return name if re.match(r"^[a-z0-9][a-z0-9._-]{0,252}$", name) else None


def is_ip(name: str) -> bool:
    try:
        ipaddress.ip_address(name)
        return True
    except ValueError:
        return False


def blocked_platform(descr: str, cfg: dict[str, Any]) -> bool:
    subs = [s.lower() for s in lines(cfg.get("autodiscovery_block_platform"))]
    if any(s in descr.lower() for s in subs):
        return True
    return any(r.search(descr) for r in regexes(cfg.get("autodiscovery_block_platform_regex") or ""))


def blocked_hostname(name: str, cfg: dict[str, Any]) -> bool:
    if name.lower() in {h.lower() for h in lines(cfg.get("autodiscovery_block_hostname"))}:
        return True
    return any(r.search(name) for r in regexes(cfg.get("autodiscovery_block_hostname_regex") or ""))


def with_domain(hostname: str, cfg: dict[str, Any]) -> str:
    domain = (cfg.get("autodiscovery_domain") or "").strip().strip(".").lower()
    if domain and "." not in hostname and not is_ip(hostname):
        return f"{hostname}.{domain}"
    return hostname


async def probe(ip: str, communities: list[str]) -> tuple[str, str, str] | None:
    """(community, sysName, sysDescr) of the first community the agent answers, or None."""
    from netsync.snmp.client import SnmpClient

    def txt(v) -> str:
        return v.decode(errors="ignore") if isinstance(v, bytes) else str(v or "")

    for community in communities:
        try:
            got = await SnmpClient(ip, community=community, timeout=1.0, retries=0).get(SYS_NAME, SYS_OID, SYS_DESCR)
        except Exception:  # noqa: BLE001 - silence is the normal answer
            continue
        if got.get(SYS_OID) is not None:
            return community, txt(got.get(SYS_NAME)), txt(got.get(SYS_DESCR))
    return None


async def alive(targets: list[str]) -> set[str]:
    """Addresses that answer one ping."""
    from icmplib import async_multiping

    alive_ = set()
    for i in range(0, len(targets), 512):
        hosts = await async_multiping(targets[i:i + 512], count=1, timeout=1, privileged=False, concurrent_tasks=256)
        alive_.update(h.address for h in hosts if h.is_alive)
    return alive_


async def resolves(name: str) -> bool:
    try:
        await asyncio.get_running_loop().getaddrinfo(name, None)
        return True
    except (OSError, socket.gaierror):
        return False


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
    scanned = len(targets)
    if not cfg.get("autodiscovery_skip_icmp"):
        up = await alive(targets)
        targets = [t for t in targets if t in up]
    sem = asyncio.Semaphore(64)

    async def one(ip: str):
        async with sem:
            return ip, await probe(ip, communities)

    found = [(ip, hit) for ip, hit in await asyncio.gather(*(one(ip) for ip in targets)) if hit]
    added, skipped = [], []
    async with SessionLocal() as s:
        for ip, (community, sys_name, sys_descr) in found:
            if blocked_platform(sys_descr, cfg):
                skipped.append({"ip": ip, "reason": "platform blocked"})
                continue
            hostname = clean_hostname(sys_name)
            try:  # prefer the DNS name of the address when it resolves
                dns = clean_hostname((await asyncio.get_running_loop().getnameinfo((ip, 0)))[0])
                if dns and not is_ip(dns) and (not hostname or "." not in hostname):
                    hostname = dns
            except (OSError, socket.gaierror):
                pass
            hostname = with_domain(hostname or ip, cfg)
            if blocked_hostname(hostname, cfg):
                skipped.append({"ip": ip, "hostname": hostname, "reason": "hostname blocked"})
                continue
            if cfg.get("autodiscovery_require_hostname") and (is_ip(hostname) or not await resolves(hostname)):
                skipped.append({"ip": ip, "hostname": hostname, "reason": "no resolvable hostname"})
                continue
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
            "scanned": scanned, "pinged": None if cfg.get("autodiscovery_skip_icmp") else len(targets),
            "answered": len(found), "added": added, "skipped": skipped}


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


# ------------------------------------------------------------------------------- sign-in lockout


def _lock_key(username: str, ip: str) -> str:
    return f"netsync:login:fail:{username.lower()}:{ip}"


async def login_locked(username: str, ip: str) -> int:
    """Minutes left on the lock for this user name from this address (0 = not locked)."""
    cfg = await get()
    limit = int(cfg.get("login_lockout_attempts") or 0)
    if not limit:
        return 0
    key = _lock_key(username, ip)
    fails = int(await redis().get(key) or 0)
    if fails < limit:
        return 0
    return max(1, round((await redis().ttl(key)) / 60))


async def login_failed(username: str, ip: str) -> None:
    cfg = await get()
    if not int(cfg.get("login_lockout_attempts") or 0):
        return
    key = _lock_key(username, ip)
    await redis().incr(key)
    await redis().expire(key, int(cfg.get("login_lockout_minutes") or 15) * 60)


async def login_ok(username: str, ip: str) -> None:
    await redis().delete(_lock_key(username, ip))


# ------------------------------------------------------------------------------- API

router = APIRouter()


@router.get("/branding")
async def branding():
    """Public (the sign-in page needs it): colour, logos (light and dark theme), icon, name, default time format."""
    cfg = await get()
    return {k: cfg.get(k) or None for k in ("accent_color", "logo", "logo_dark", "icon", "app_name", "time_format")}


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


@router.post("/ip-type", dependencies=[require(Role.ADMIN)])
async def ip_type_of(body: dict):
    """Try the IP type rules: {"address": "fe80::1"} → {"type": "link-local"}."""
    return {"type": ip_type(str(body.get("address", "")))}


async def remove_ignored(session, cfg: dict[str, Any]) -> str | None:
    """After a save: remove at once the ports, storage, processors and sensors the ignore rules now leave out (with
    their services), instead of waiting for two discoveries - an ignore rule is a deliberate choice."""
    from sqlalchemy import delete

    from netsync.models import Component, Service

    rows = list(await session.scalars(select(Component).where(
        Component.deleted.is_(False), Component.kind.in_(("port", "storage", "processor", "sensor")))))
    gone = [c for c in rows if ignored(c, cfg)]
    if not gone:
        return None
    for c in gone:
        c.deleted = True
    await session.execute(delete(Service).where(Service.component_id.in_([c.id for c in gone])))
    await session.commit()
    return f"Removed {len(gone)} ignored {'entity' if len(gone) == 1 else 'entities'} now."


@router.get("/discovered", dependencies=[require(Role.ADMIN)])
async def discovered(session: Session):
    """Ports, storage, processors and sensors found on all devices, grouped for the "pick what to ignore" lists."""
    from netsync.discovered import summarize
    from netsync.models import Component

    rows = list(await session.scalars(select(Component).where(
        Component.deleted.is_(False), Component.kind.in_(("port", "storage", "processor", "sensor")))))
    devices = dict((await session.execute(select(Device.id, Device.hostname))).all())
    return summarize(rows, await get(), devices)


plugin = Plugin(
    name=NAME,
    label="General",
    version="1.1.0",
    description="Branding, discovery rules, autodiscovery, entities, alerting, sign-in and network options",
    services=[AutodiscoveryService()],
    router=router,
    builtin=True,
    settings=SETTINGS,
    defaults=DEFAULTS,
    hooks={"settings_saved": [remove_ignored]},
    validate=validate,
    actions=[{"id": "scan", "label": "Scan networks now", "method": "POST", "path": "/autodiscovery/run"}],
)
