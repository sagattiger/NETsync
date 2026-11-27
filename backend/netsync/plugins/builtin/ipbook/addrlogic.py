"""IP books: one network, one row per address (like a range sheet). Only addresses with data are stored; the rest
are shown as available. Status: subnet, broadcast, gateway, reserved, down (ping), used, live (answers ping but
nothing is written on it: found by the network scan) or available."""

from __future__ import annotations

import ipaddress
from typing import Any

MAX_ADDRESSES = 4096  # an IPv4 /20; bigger networks would make a page nobody can read


def book_cidr(text: str) -> str:
    """The normalized network of an IP book; ValueError when it isn't one or has more than 4096 addresses."""
    try:
        net = ipaddress.ip_network(str(text).strip(), strict=False)
    except ValueError:
        raise ValueError(f"{text!r} is not a network like 10.0.0.0/24") from None
    if net.num_addresses > MAX_ADDRESSES:
        raise ValueError(f"{net} has {net.num_addresses} addresses; an IP book holds up to {MAX_ADDRESSES} (an IPv4 /20)")
    return str(net)


def books_for(ip: str, books) -> list:
    """The IP books whose network holds this address."""
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return []
    out = []
    for b in books:
        if not b.cidr:
            continue
        net = ipaddress.ip_network(b.cidr, strict=False)
        if net.version == addr.version and addr in net:
            out.append(b)
    return out


def _status(ip: str, net, gateway: str | None, addr, health: dict | None) -> str:
    if net.version == 4 and net.prefixlen <= 30:
        if ip == str(net.network_address):
            return "subnet"
        if ip == str(net.broadcast_address):
            return "broadcast"
    if gateway and ip == gateway:
        return "gateway"
    if addr is not None and addr.reserved:
        return "reserved"
    used = addr is not None and any(v not in (None, "", []) for v in (addr.values or {}).values())
    if used and (health or {}).get("state") == "down":
        return "down"
    if used:
        return "used"
    return "live" if (health or {}).get("state") == "up" else "available"


def address_rows(cidr: str, gateway: str | None, stored: dict[str, Any], states: dict[str, dict],
                 devices: dict[int, dict] | None = None) -> list[dict]:
    """Every address of the network in order, with its stored values (if any), status, last ping and the device
    discovery found it on (for its OS logo and link)."""
    devices = devices or {}
    net = ipaddress.ip_network(cidr, strict=False)
    gw = str(gateway).strip() if gateway else None
    rows = []
    for i in range(int(net.network_address), int(net.broadcast_address) + 1):
        ip = str(ipaddress.ip_address(i))
        addr = stored.get(ip)
        row = {"ip": ip, "status": _status(ip, net, gw, addr, states.get(ip)),
               "values": dict(addr.values or {}) if addr is not None else {},
               "reserved": bool(addr.reserved) if addr is not None else False,
               "learned": addr is not None and addr.source == "learned",
               "alert_when_down": addr.alert_when_down if addr is not None else None,
               "updated_at": addr.updated_at.isoformat() if addr is not None and addr.updated_at else None,
               "updated_by": addr.updated_by if addr is not None else None,
               "health": states.get(ip),
               "device": devices.get(getattr(addr, "device_id", None)) if addr is not None else None}
        rows.append(row)
    return rows


def counts(rows: list[dict]) -> dict[str, int]:
    """How the usable addresses are used (subnet and broadcast rows aren't counted)."""
    usable = [r for r in rows if r["status"] not in ("subnet", "broadcast")]
    return {"size": len(usable),
            "used": sum(1 for r in usable if r["status"] in ("used", "live", "down", "gateway")),
            "available": sum(1 for r in usable if r["status"] == "available"),
            "reserved": sum(1 for r in usable if r["status"] == "reserved")}


def learned_address_values(device, interface: str | None, mac: str | None) -> dict[str, str]:
    """What discovery knows about one address it found on a device."""
    out = {"addr_hostname": device.hostname}
    model = device.hardware or device.vendor
    if model:
        out["addr_device"] = model
    if interface:
        out["addr_interface"] = interface
    if mac:
        out["addr_mac"] = mac
    return out
