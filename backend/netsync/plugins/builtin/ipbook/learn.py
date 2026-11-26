"""IP Book learning: after each device discovery, its learned row and the networks of its addresses are refreshed.
Values a person set (``manual_keys``) are never written; nothing is deleted - a row whose device disappears is only
marked ``missing_since``."""

from __future__ import annotations

import ipaddress
import logging
from datetime import datetime, timedelta
from typing import Any

from netsync.plugins.builtin.ipbook.netlogic import MISSING_AFTER, learnable_network

log = logging.getLogger(__name__)
TYPES = {"lxc": "LXC", "vm": "VM"}


def learned_values(device, hypervisor, port_ipv4: list[str]) -> dict[str, Any]:
    """What discovery knows about a device, keyed by IP Book column. ``port_ipv4``: its ports' addresses with prefix."""
    v: dict[str, Any] = {"hostname": device.hostname, "type": TYPES.get(device.virtualization or "", "Device")}
    if device.app_name:
        v["service"] = {"name": device.app_name, "logo": device.app_logo}
    if hypervisor is not None:
        v["hypervisor"] = {"id": hypervisor.id, "name": hypervisor.hostname}
    if device.guest_id is not None:
        v["vmid"] = device.guest_id
    if device.os:
        v["os"] = device.os
    if device.ip:
        v["ip_mgmt"] = device.ip
    others = []
    for cidr in port_ipv4:
        try:
            ip = str(ipaddress.ip_interface(cidr).ip)
        except ValueError:
            continue
        if ip != device.ip and ip not in others and not ipaddress.ip_address(ip).is_loopback:
            others.append(ip)
    if others:
        v["ip_lan"] = others[0]
    if others[1:]:
        v["other_ips"] = others[1:]
    if device.app_url:
        v["urls_internal"] = [device.app_url]
    if device.app_port:
        https = str(device.app_url or "").lower().startswith("https")
        v["https_port" if https else "http_port"] = device.app_port
    return v


def merge_learned(row_values: dict, manual_keys: set[str], learned: dict, from_import: bool,
                  previous: dict | None = None) -> tuple[dict, dict]:
    """New values after discovery: learned keys are written unless a person set them; learned keys discovery no
    longer reports are removed (unless manual). Conflicts are recorded only for rows that came from an import."""
    new = dict(row_values or {})
    manual = set(manual_keys or ())
    for key in set(previous or {}) - set(learned) - manual:
        new.pop(key, None)
    conflicts = {}
    for key, value in learned.items():
        if key in manual:
            if from_import and new.get(key) != value:
                conflicts[key] = {"manual": new.get(key), "discovered": value}
            continue
        new[key] = value
    return new, conflicts


async def learn_device(session, device) -> None:
    """Refresh the device's learned row and learn the networks of its ports' IPv4 addresses."""
    from sqlalchemy import select

    from netsync.models import VIRTUAL_DEVICE_TYPES, Component, Device, IpbNetwork, IpbRow

    if device.device_type in VIRTUAL_DEVICE_TYPES:
        return
    hypervisor = await session.get(Device, device.hypervisor_id) if device.hypervisor_id else None
    ports = await session.scalars(select(Component).where(
        Component.device_id == device.id, Component.kind == "port", Component.deleted.is_(False)))
    port_ipv4 = [a for c in ports for a in ((c.attrs or {}).get("ipv4") or [])]
    learned = learned_values(device, hypervisor, port_ipv4)

    row = await session.scalar(select(IpbRow).where(IpbRow.device_id == device.id).order_by(IpbRow.id).limit(1))
    if row is None:
        row = IpbRow(device_id=device.id, source="learned", values={}, learned={}, manual_keys=[], conflicts={})
        session.add(row)
    values, conflicts = merge_learned(row.values, set(row.manual_keys or []), learned, row.source == "imported",
                                      previous=row.learned)
    row.values, row.learned, row.missing_since = values, learned, None
    if conflicts:
        row.conflicts = {**(row.conflicts or {}), **conflicts}

    known = set(await session.scalars(select(IpbNetwork.cidr)))
    for cidr in port_ipv4:
        net = learnable_network(cidr)
        if net and net not in known:
            session.add(IpbNetwork(cidr=net, title=net, source="learned"))
            known.add(net)
    await session.flush()


async def mark_missing(session, now: datetime) -> None:
    """Learned rows whose device is gone, or wasn't discovered for 7 days, get ``missing_since``."""
    from sqlalchemy import select

    from netsync.models import Device, IpbRow

    rows = list(await session.scalars(select(IpbRow).where(IpbRow.source == "learned", IpbRow.missing_since.is_(None))))
    for row in rows:
        dev = await session.get(Device, row.device_id) if row.device_id else None
        if dev is None:
            row.missing_since = now - MISSING_AFTER - timedelta(seconds=1)
        elif dev.last_discovered and now - dev.last_discovered > MISSING_AFTER:
            row.missing_since = dev.last_discovered
    await session.flush()
