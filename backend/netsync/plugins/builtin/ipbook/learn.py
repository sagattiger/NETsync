"""IP Book and discovery: after each device discovery, the addresses it found are filled into the IP books the admin
created (hostname, device, interface, MAC). Service books are never touched; networks are never created here.
Values a person set (``manual_keys``) are never written."""

from __future__ import annotations

import ipaddress
import logging
from datetime import UTC, datetime

from netsync.plugins.builtin.ipbook.addrlogic import books_for, learned_address_values

log = logging.getLogger(__name__)


def addresses_of(device, ports: list[tuple[str, str | None, list[str]]]) -> dict[str, tuple[str | None, str | None]]:
    """Every address of a device → (interface name, MAC): its ports' IPv4 addresses, plus the address it's polled on."""
    out: dict[str, tuple[str | None, str | None]] = {}
    for name, mac, cidrs in sorted(ports, key=lambda p: (p[0] or "").lower()):
        for cidr in cidrs or []:
            try:
                ip = ipaddress.ip_interface(cidr).ip
            except ValueError:
                continue
            if not ip.is_loopback and str(ip) not in out:
                out[str(ip)] = (name or None, mac or None)
    if device.ip:
        try:
            out.setdefault(str(ipaddress.ip_address(device.ip)), (None, None))
        except ValueError:
            pass
    return out


def merge_learned(row_values: dict, manual_keys: set[str], learned: dict, from_import: bool,
                  previous: dict | None = None) -> tuple[dict, dict]:
    """New values after discovery: learned keys are written unless a person set them; learned keys discovery no
    longer reports are removed (unless manual). Conflicts are recorded only when ``from_import``."""
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
    """Fill the device's addresses into the IP books that hold them; addresses it no longer has lose what
    discovery wrote (and become available again unless a person wrote something)."""
    from sqlalchemy import select

    from netsync.models import VIRTUAL_DEVICE_TYPES, Component, IpbAddress, IpbBook

    if device.device_type in VIRTUAL_DEVICE_TYPES:
        return
    books = list(await session.scalars(select(IpbBook).where(IpbBook.kind == "ip")))
    if not books:
        return
    ports = await session.scalars(select(Component).where(
        Component.device_id == device.id, Component.kind == "port", Component.deleted.is_(False)))
    found = addresses_of(device, [(c.name, (c.attrs or {}).get("mac"), (c.attrs or {}).get("ipv4") or []) for c in ports])
    now = datetime.now(UTC)
    seen: set[tuple[int, str]] = set()
    for ip, (iface, mac) in found.items():
        for book in books_for(ip, books):
            seen.add((book.id, ip))
            addr = await session.scalar(select(IpbAddress).where(IpbAddress.book_id == book.id, IpbAddress.ip == ip))
            if addr is None:
                addr = IpbAddress(book_id=book.id, ip=ip, values={}, learned={}, manual_keys=[], source="learned")
                session.add(addr)
            learned = learned_address_values(device, iface, mac)
            values, _ = merge_learned(addr.values, set(addr.manual_keys or []), learned, False, previous=addr.learned)
            if values != (addr.values or {}) or addr.device_id != device.id:
                addr.updated_at, addr.updated_by = now, "discovery"
            addr.values, addr.learned, addr.device_id = values, learned, device.id
    # addresses this device had before but no longer reports
    for addr in list(await session.scalars(select(IpbAddress).where(IpbAddress.device_id == device.id))):
        if (addr.book_id, addr.ip) in seen:
            continue
        values, _ = merge_learned(addr.values, set(addr.manual_keys or []), {}, False, previous=addr.learned)
        addr.values, addr.learned, addr.device_id, addr.updated_at, addr.updated_by = values, {}, None, now, "discovery"
        if not values and not addr.reserved and not addr.manual_keys:
            await session.delete(addr)
    await session.flush()
