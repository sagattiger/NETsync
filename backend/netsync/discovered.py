"""What discovery found, grouped so Settings → General → Discovery can offer it as tick boxes to ignore.

Each choice carries the line it adds to an ignore setting (``field`` + ``rule``), so the picker only fills in the
existing settings - nothing new to learn or to keep in sync."""

from __future__ import annotations

import re
from collections import defaultdict
from typing import Any

# Well-known port name prefixes (checked longest first) and what they are.
PORT_PREFIXES = {
    "veth": "Container virtual ethernet (LXC, Docker)",
    "tap": "VM network taps (Proxmox, KVM)",
    "fwln": "Proxmox firewall links",
    "fwpr": "Proxmox firewall ports",
    "fwbr": "Proxmox firewall bridges",
    "vmbr": "Proxmox bridges",
    "br-": "Docker networks",
    "docker": "Docker default bridge",
    "virbr": "libvirt bridges",
    "cali": "Calico (Kubernetes)",
    "flannel": "Flannel (Kubernetes)",
    "cni": "Kubernetes CNI",
    "vxlan": "VXLAN tunnels",
    "tun": "Tunnels",
    "wg": "WireGuard",
    "ppp": "PPP",
    "pppoe-": "PPPoE sessions",
    "l2tp-": "L2TP sessions",
    "ovpn-": "OpenVPN sessions",
    "sstp-": "SSTP sessions",
    "gre": "GRE tunnels",
    "eoip-": "EoIP tunnels",
    "lo": "Loopback",
    "bond": "Bonds",
    "vlan": "VLANs",
    "eth": "Ethernet",
    "enp": "Ethernet (PCI)",
    "ens": "Ethernet (slot)",
    "eno": "Ethernet (onboard)",
    "wlan": "Wi-Fi",
    "wlx": "Wi-Fi (USB)",
}
_PREFIX_ORDER = sorted(PORT_PREFIXES, key=len, reverse=True)


def port_prefix(name: str) -> str | None:
    """veth101i0 → veth, br-3f2a… → br-, Gi0/1 → Gi; None when the name has no clear prefix."""
    low = name.lower()
    for p in _PREFIX_ORDER:
        if low.startswith(p) and (len(name) > len(p)):
            return name[: len(p)]
    m = re.match(r"^([A-Za-z]+[-_.]?)[0-9]", name)
    return m.group(1) if m else None


def digit_pattern(name: str) -> str | None:
    """CPU 12 → "CPU #", Core 3 → "Core #"; None when the name has no number."""
    return re.sub(r"[0-9]+", "#", name) if re.search(r"[0-9]", name) else None


def pattern_rule(pattern: str) -> str:
    """ "CPU #" → /^CPU [0-9]+$/ """
    return "/^" + "[0-9]+".join(re.escape(p) for p in pattern.split("#")) + "$/"


def exact_rule(name: str) -> str:
    return "/^" + re.escape(name) + "$/"


def summarize(components: list[Any], cfg: dict[str, Any], devices: dict[int, str]) -> dict[str, Any]:
    """Ports (by type, name prefix and name) and storage/processors/sensors (by pattern and name), with how many
    devices have each and whether the saved settings already ignore all of them."""
    from netsync.general import IF_TYPES, ignored

    if_names = {v: k for k, v in IF_TYPES.items()}

    def group(items, key, label=None):
        out: dict[str, dict] = {}
        for c in items:
            k = key(c)
            if k is None:
                continue
            g = out.setdefault(k, {"key": k, "count": 0, "devices": set(), "examples": [], "ignored": 0})
            g["count"] += 1
            g["devices"].add(c.device_id)
            if len(g["examples"]) < 4 and c.name not in g["examples"]:
                g["examples"].append(c.name)
            g["ignored"] += bool(ignored(c, cfg))
        rows = []
        for g in out.values():
            g["all_ignored"] = g.pop("ignored") == g["count"]
            ids = g.pop("devices")
            g["device_count"] = len(ids)
            g["device_names"] = sorted(devices.get(d, str(d)) for d in ids)[:6]
            if label:
                g.update(label(g["key"]))
            rows.append(g)
        return sorted(rows, key=lambda g: (-g["count"], str(g["key"]).lower()))

    by_kind: dict[str, list] = defaultdict(list)
    for c in components:
        by_kind[c.kind].append(c)
    ports = by_kind["port"]

    result: dict[str, Any] = {
        "port": {
            "types": group(ports, lambda c: if_names.get((c.attrs or {}).get("if_type")),
                           lambda k: {"label": k, "field": "ports_ignore_types", "rule": k}),
            "patterns": group(ports, lambda c: port_prefix(c.name),
                              lambda k: {"label": f"{k}*", "hint": PORT_PREFIXES.get(k.lower(), ""),
                                         "field": "ports_ignore_regex", "rule": "/^" + re.escape(k) + "/"}),
            "names": group(ports, lambda c: c.name,
                           lambda k: {"label": k, "field": "ports_ignore_regex", "rule": exact_rule(k)}),
        },
    }
    for kind in ("storage", "processor", "sensor"):
        items = by_kind[kind]
        patterns = [g for g in group(items, lambda c: digit_pattern(c.name),
                                     lambda k, kind=kind: {"label": k.replace("#", "N"), "field": f"{kind}_ignore_regex",
                                                "rule": pattern_rule(k)})
                    if g["count"] > 1]
        result[kind] = {
            "patterns": patterns,
            "names": group(items, lambda c: c.name,
                           lambda k, kind=kind: {"label": k, "field": f"{kind}_ignore_exact", "rule": k}),
        }
    return result
