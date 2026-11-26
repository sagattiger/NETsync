"""IP Book networks: which rows are in which network, how full a network is, its address grid, and the warnings
(overlap, duplicate IP, IP on another device, private IP outside every network, missing learned row, full network,
unresolved import conflict). Pure functions: rows and networks are any objects with the model's attributes."""

from __future__ import annotations

import ipaddress
import re
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Any

MISSING_AFTER = timedelta(days=7)
FULL_PCT = 90
GRID_MIN_PREFIX = 20  # IPv4 /20 (4094 hosts) or smaller gets a per-address grid
PRIVATE = [ipaddress.ip_network(n) for n in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "100.64.0.0/10", "fc00::/7")]


def learnable_network(cidr: str) -> str | None:
    """The network of a discovered address with its prefix, when it's worth learning (IPv4 /16../31, not loopback,
    link-local or multicast); None otherwise."""
    if "/" not in str(cidr):
        return None
    try:
        iface = ipaddress.ip_interface(cidr)
    except ValueError:
        return None
    ip, net = iface.ip, iface.network
    if ip.version != 4 or not 16 <= net.prefixlen <= 31 or ip.is_loopback or ip.is_link_local or ip.is_multicast:
        return None
    return str(net)


def _ips(value: Any) -> list[str]:
    items = value if isinstance(value, list) else re.split(r"[\s,;]+", str(value or ""))
    out = []
    for item in items:
        try:
            out.append(str(ipaddress.ip_address(str(item).strip())))
        except ValueError:
            continue
    return out


def row_ips(row, ip_columns: set[str]) -> list[tuple[str, str]]:
    """(column key, ip) for every address in the row's IP-bearing columns."""
    return [(k, ip) for k in sorted(ip_columns) for ip in _ips((row.values or {}).get(k))]


def rows_in_network(network, rows, ip_columns: set[str]) -> list[tuple[Any, list[str]]]:
    """Rows with at least one IP in the network, and the keys of the columns holding those IPs."""
    net = ipaddress.ip_network(network.cidr, strict=False)
    out = []
    for r in rows:
        keys = sorted({k for k, ip in row_ips(r, ip_columns) if ipaddress.ip_address(ip) in net})
        if keys:
            out.append((r, keys))
    return out


def _hosts(net) -> tuple[int, int]:
    """First and last usable address as ints (IPv4 network/broadcast excluded for /30 and wider)."""
    first, last = int(net.network_address), int(net.broadcast_address)
    if net.version == 4 and net.prefixlen <= 30:
        first, last = first + 1, last - 1
    return first, last


def usage(cidr: str, used_ips: set[str]) -> dict[str, int]:
    net = ipaddress.ip_network(cidr, strict=False)
    first, last = _hosts(net)
    size = last - first + 1
    used = sum(1 for ip in used_ips if first <= int(ipaddress.ip_address(ip)) <= last
               and ipaddress.ip_address(ip).version == net.version)
    return {"size": size, "used": used, "free": max(size - used, 0), "pct": round(used * 100 / size) if size else 0}


def grid(cidr: str, states: dict[str, str]) -> list[str] | None:
    """One state per usable IPv4 address ("used", "down", "free"...) for /20 or smaller networks."""
    net = ipaddress.ip_network(cidr, strict=False)
    if net.version != 4 or net.prefixlen < GRID_MIN_PREFIX:
        return None
    first, last = _hosts(net)
    return [states.get(str(ipaddress.IPv4Address(i)), "free") for i in range(first, last + 1)]


def is_private(ip: str) -> bool:
    addr = ipaddress.ip_address(ip)
    return any(addr in n for n in PRIVATE if n.version == addr.version)



def _w(kind: str, text: str, rows=(), networks=()) -> dict:
    return {"kind": kind, "text": text, "rows": sorted(set(rows)), "networks": sorted(set(networks))}


def warnings(networks, rows, ip_columns: set[str], device_ips: dict[str, int], row_devices: dict[int, int | None],
             now: datetime) -> dict[str, dict[int, list[dict]]]:
    """Warnings for the networks and rows given. ``device_ips``: discovered IP → device id; ``row_devices``: row id →
    the device it was learned from."""
    nets = [(n, ipaddress.ip_network(n.cidr, strict=False)) for n in networks if not getattr(n, "hidden", False)]
    out_n: dict[int, list[dict]] = defaultdict(list)
    out_r: dict[int, list[dict]] = defaultdict(list)

    for i, (a, na) in enumerate(nets):
        for b, nb in nets[i + 1:]:
            if na.version == nb.version and na.overlaps(nb):
                w = _w("overlap", f"{a.cidr} overlaps {b.cidr}", networks=(a.id, b.id))
                out_n[a.id].append(w)
                out_n[b.id].append(w)

    by_ip: dict[str, list] = defaultdict(list)
    for r in rows:
        nat = bool((r.values or {}).get("nat"))
        for key, ip in row_ips(r, ip_columns):
            if not (nat and key == "ip_wan") and r not in by_ip[ip]:
                by_ip[ip].append(r)
            dev = device_ips.get(ip)
            linked = row_devices.get(r.id)
            if dev is not None and linked is not None and dev != linked:
                out_r[r.id].append(_w("device_conflict", f"{ip} is also on another discovered device", rows=(r.id,)))
            if is_private(ip) and not any(ipaddress.ip_address(ip) in n for _, n in nets
                                          if n.version == ipaddress.ip_address(ip).version):
                out_r[r.id].append(_w("outside", f"{ip} is in no network", rows=(r.id,)))
        if r.source == "learned" and r.missing_since and now - r.missing_since > MISSING_AFTER:
            out_r[r.id].append(_w("missing", "Discovery no longer finds this device", rows=(r.id,)))
        if r.conflicts:
            out_r[r.id].append(_w("conflict", "Discovery disagrees with saved values", rows=(r.id,)))

    for ip, holders in by_ip.items():
        # A host row and the rows running on it are one owner ("family"); an IP is a duplicate only across families.
        # The warning goes to the family's host row when it holds the IP, else to the family members that do.
        families: dict[int, list] = defaultdict(list)
        for r in holders:
            families[r.runs_on_id if r.runs_on_id is not None else r.id].append(r)
        if len(families) < 2:
            continue
        clash = set()
        for root, members in families.items():
            roots = [m for m in members if m.id == root]
            clash |= {m.id for m in (roots or members)}
        for rid in clash:
            out_r[rid].append(_w("duplicate", f"{ip} is used by another entry", rows=clash))
        addr = ipaddress.ip_address(ip)
        for n, na in nets:
            if na.version == addr.version and addr in na:
                out_n[n.id].append(_w("duplicate", f"{ip} is used by more than one entry", rows=clash, networks=(n.id,)))

    for n, _ in nets:
        used = {ip for r, _keys in rows_in_network(n, rows, ip_columns) for k, ip in row_ips(r, ip_columns)}
        u = usage(n.cidr, used)
        if u["pct"] > FULL_PCT:
            out_n[n.id].append(_w("full", f"{u['pct']} % used", networks=(n.id,)))
    return {"networks": dict(out_n), "rows": dict(out_r)}
