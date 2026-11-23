"""Which Proxmox VE host runs which LXC container and VM, from the host's SNMP process table (no Proxmox API key).

A Proxmox host runs one process per running guest, visible in HOST-RESOURCES-MIB hrSWRunTable:
  * VM:  name "kvm",       parameters "-id 203 -name vm203-infra.example.net -no-shutdown ..."
  * LXC: name "lxc-start", parameters "-F -n 100"
Discovery of the host stores each running guest as a ``pve_guest`` component. Each guest device is then linked to its
host (``Device.hypervisor_id``): a VM by its name, a container by its ID appearing in its hostname or SNMP name
(lxc100-infra -> 100), and only when exactly one host runs that ID. A link set by hand is never changed.
"""

from __future__ import annotations

import re

from sqlalchemy import select

from netsync.plugins.base import ComponentSpec, DeviceContext, Module
from netsync.snmp.client import text

HR_SW_RUN_NAME = "1.3.6.1.2.1.25.4.2.1.2"
HR_SW_RUN_PARAMETERS = "1.3.6.1.2.1.25.4.2.1.5"
KIND = "pve_guest"

_KVM = re.compile(r"(?:^|\s)-id\s+(\d+)(?:\s.*?-name\s+([^\s,]+))?")
_LXC = re.compile(r"(?:^|\s)-n\s+(\d+)\b")


def parse_guests(names: dict[str, str], params: dict[str, str]) -> list[dict]:
    """[{"type": "qemu" | "lxc", "vmid": int, "name": str | None}] from hrSWRunName / hrSWRunParameters."""
    out: dict[tuple[str, int], dict] = {}
    for idx, name in names.items():
        name = (name or "").strip()
        p = params.get(idx) or ""
        if name == "kvm" and (m := _KVM.search(p)):
            out[("qemu", int(m[1]))] = {"type": "qemu", "vmid": int(m[1]), "name": (m[2] or "").lower() or None}
        elif name == "lxc-start" and (m := _LXC.search(p)):
            out.setdefault(("lxc", int(m[1])), {"type": "lxc", "vmid": int(m[1]), "name": None})
    return sorted(out.values(), key=lambda g: (g["vmid"], g["type"]))


def _labels(*names: str | None) -> set[str]:
    out = set()
    for n in names:
        n = (n or "").strip().lower().rstrip(".")
        if n:
            out.add(n)
            out.add(n.split(".")[0])
    return out


def match_host(device_names: list[str | None], virtualization: str | None,
               guests: list[tuple[int, dict]]) -> tuple[int, dict] | None:
    """(host id, guest) running this device, or None. ``guests``: (host id, guest) of every Proxmox host.

    VM: its name (full or first label) equals the device's hostname or SNMP name. Container: the device was detected
    as an LXC container and its ID is a whole number in the first label of its hostname or SNMP name; if several
    hosts or IDs fit, nothing is linked rather than a guess."""
    names = _labels(*device_names)
    if not names:
        return None
    if virtualization != "lxc":
        hits = [(h, g) for h, g in guests if g["type"] == "qemu" and g["name"] and _labels(g["name"]) & names]
        if len(hits) == 1:
            return hits[0]
    if virtualization == "lxc":  # only detected containers: a switch named "sw-105" must not become CT 105
        firsts = {n.split(".")[0] for n in names}
        hits = [(h, g) for h, g in guests if g["type"] == "lxc"
                and any(re.search(rf"(?<!\d){g['vmid']}(?!\d)", f) for f in firsts)]
        if len(hits) == 1:
            return hits[0]
    return None


class ProxmoxGuestsModule(Module):
    name = "proxmox_guests"
    kinds = (KIND,)
    order = 90

    def applies_to(self, device) -> bool:
        return getattr(device, "os", None) == "proxmox"

    async def discover(self, ctx: DeviceContext):
        names = {i: text(v) or "" for i, v in (await ctx.snmp.walk(HR_SW_RUN_NAME)).items()}
        wanted = {i: n for i, n in names.items() if n.strip() in ("kvm", "lxc-start")}
        if not wanted:
            return []
        params = {i: text(v) or "" for i, v in (await ctx.snmp.walk(HR_SW_RUN_PARAMETERS)).items() if i in wanted}
        return [ComponentSpec(KIND, f"{g['type']}:{g['vmid']}",
                              g["name"] or f"{'VM' if g['type'] == 'qemu' else 'CT'} {g['vmid']}",
                              attrs={"type": g["type"], "vmid": g["vmid"], "guest_name": g["name"]})
                for g in parse_guests(wanted, params)]


async def link_guests(session, device) -> int:
    """After a discovery: link guest devices to their Proxmox host. For a host, every guest device is checked; for a
    guest, only itself. Links set by hand stay. Returns how many links changed."""
    from netsync.models import Component, Device, real_device

    hosts = list(await session.scalars(select(Device).where(Device.os == "proxmox")))
    if not hosts:
        return 0
    comps = await session.scalars(select(Component).where(
        Component.kind == KIND, Component.deleted.is_(False), Component.device_id.in_([h.id for h in hosts])))
    guests = [(c.device_id, {"type": c.attrs.get("type"), "vmid": c.attrs.get("vmid"), "name": c.attrs.get("guest_name")})
              for c in comps if isinstance(c.attrs.get("vmid"), int)]
    if device.os == "proxmox":
        candidates = list(await session.scalars(select(Device).where(real_device(), Device.os != "proxmox")))
    else:
        candidates = [device]
    changed = 0
    for d in candidates:
        if d.hypervisor_source == "manual" or d.os == "proxmox":
            continue
        hit = match_host([d.hostname, d.sys_name], d.virtualization, guests)
        if hit and (d.hypervisor_id, d.guest_id) != (hit[0], hit[1]["vmid"]):
            d.hypervisor_id, d.guest_id, d.hypervisor_source = hit[0], hit[1]["vmid"], "auto"
            changed += 1
    return changed
