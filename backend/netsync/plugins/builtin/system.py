"""SNMPv2-MIB system group: identity, OS detection, uptime / reboot check."""

import asyncio
import ipaddress
import re
import socket

from netsync.models import State
from netsync.plugins.base import CheckResult, DeviceContext, MetricSample, Module, PollResult
from netsync.snmp.client import text
from netsync.snmp.profiles import detect

SYS_DESCR = "1.3.6.1.2.1.1.1.0"
SYS_OBJECT_ID = "1.3.6.1.2.1.1.2.0"
SYS_UPTIME = "1.3.6.1.2.1.1.3.0"
SYS_CONTACT = "1.3.6.1.2.1.1.4.0"
SYS_NAME = "1.3.6.1.2.1.1.5.0"
SYS_LOCATION = "1.3.6.1.2.1.1.6.0"
ENT_SERIAL = "1.3.6.1.2.1.47.1.1.1.1.11.1"
ENT_MODEL = "1.3.6.1.2.1.47.1.1.1.1.13.1"


IP_AD_ENT_ADDR = "1.3.6.1.2.1.4.20.1.1"  # IP-MIB ipAddrTable


async def device_addresses(ctx: DeviceContext) -> list[str]:
    """All IPv4 addresses of the device: its IP-MIB address table plus the address we poll.

    Syslog and traps are sent from whichever interface faces the receiver, which is often
    not the address the device is monitored on."""
    addrs: set[str] = set()
    try:
        for value in (await ctx.snmp.walk(IP_AD_ENT_ADDR)).values():
            if isinstance(value, str):
                addrs.add(value)
    except Exception:
        pass
    host = ctx.snmp.host
    try:
        ipaddress.ip_address(host)
        addrs.add(host)
    except ValueError:
        try:
            infos = await asyncio.get_running_loop().getaddrinfo(host, None, family=socket.AF_INET)
            addrs.update(i[4][0] for i in infos)
        except OSError:
            pass
    return sorted(a for a in addrs if not a.startswith(("127.", "0.")))


def fmt_uptime(seconds: int) -> str:
    d, rem = divmod(seconds, 86400)
    h, rem = divmod(rem, 3600)
    m, _ = divmod(rem, 60)
    return f"{d}d {h}h {m}m"


class SystemModule(Module):
    name = "system"
    order = 0

    async def discover(self, ctx: DeviceContext):
        d = ctx.device
        r = await ctx.snmp.get(SYS_DESCR, SYS_OBJECT_ID, SYS_CONTACT, SYS_NAME, SYS_LOCATION)
        d.sys_descr = text(r.get(SYS_DESCR))
        d.sys_object_id = r.get(SYS_OBJECT_ID)
        d.sys_contact = text(r.get(SYS_CONTACT))
        d.sys_name = text(r.get(SYS_NAME))
        d.sys_location = text(r.get(SYS_LOCATION))

        profile, version = detect(d.sys_object_id or "", d.sys_descr or "")
        if profile:
            d.os, d.vendor, d.device_type = profile.os, profile.vendor, profile.device_type
            d.version = version
        else:
            d.os, d.vendor, d.device_type = "generic", None, d.device_type or "network"

        try:
            ent = await ctx.snmp.get(ENT_SERIAL, ENT_MODEL)
            d.serial = text(ent.get(ENT_SERIAL)) or d.serial
            d.hardware = text(ent.get(ENT_MODEL)) or d.hardware
        except Exception:
            pass

        if profile:
            if profile.hardware_regex and (m := re.search(profile.hardware_regex, d.sys_descr or "")):
                d.hardware = m.group(1).strip()
            vendor_oids = {k: o for k, o in (("version", profile.version_oid), ("serial", profile.serial_oid),
                                             ("hardware", profile.hardware_oid)) if o}
            if vendor_oids:
                try:
                    r = await ctx.snmp.get(*vendor_oids.values())
                    for field, oid in vendor_oids.items():
                        if value := text(r.get(oid)):
                            setattr(d, field, value)
                except Exception:
                    pass

        d.ip_addresses = await device_addresses(ctx)
        return []

    async def poll(self, ctx: DeviceContext):
        # Raises SnmpTimeout when the device is unreachable -> poller marks it down.
        r = await ctx.snmp.get(SYS_UPTIME)
        ticks = r.get(SYS_UPTIME) or 0
        uptime = int(ticks) // 100
        previous = ctx.device.uptime
        ctx.device.uptime = uptime

        rebooted = previous is not None and uptime < previous
        return PollResult(
            metrics=[MetricSample("uptime", uptime)],
            checks=[
                CheckResult(
                    check="uptime",
                    name="Uptime",
                    state=State.WARN if rebooted else State.OK,
                    output=("Device rebooted, " if rebooted else "") + f"up {fmt_uptime(uptime)}",
                    value=uptime,
                    unit="s",
                )
            ],
        )
