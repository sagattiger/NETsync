"""Build the prompt for an AI analysis from what NETsync knows about the device."""

from datetime import timedelta
from typing import Any

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from netsync.models import AIJob, Component, Device, Service, State, StateChange, SyslogMessage, device_group_members
from netsync.rules.engine import get_ruleset

SEVERITY = ["emergency", "alert", "critical", "error", "warning", "notice", "info", "debug"]
VIRT = {"lxc": "LXC container on a Proxmox VE host (shares the host kernel)", "vm": "virtual machine"}


def system_prompt(cfg: dict[str, Any]) -> str:
    extra = (cfg.get("extra_instructions") or "").strip()
    return (
        "You are a senior network and systems engineer embedded in NETsync, an SNMP monitoring system. "
        "You explain monitoring alerts to the operators who run this network.\n"
        f"Answer in {cfg.get('language') or 'English'}, in Markdown, using exactly these sections:\n"
        "**What happened** - one or two sentences in plain words.\n"
        "**Likely causes** - a short ranked list, most likely first, tied to the data you were given.\n"
        "**How to fix** - concrete steps and commands for this exact platform (vendor/OS/version).\n"
        "**How to verify** - how to confirm it is fixed.\n"
        f"Keep it under {int(cfg.get('max_words', 250))} words. Only use facts from the data; if something is "
        "missing say what to check instead of guessing. Never invent IP addresses, interface names or values."
        + (f"\n\nSite specific context from the operators:\n{extra}" if extra else "")
    )


# Short platform facts. Small local models give far better, platform-correct advice with these.
PLATFORM_HINTS = {
    "lxc": ("This is an LXC container: CPU, memory, swap and disk limits are set on the Proxmox host, "
            "e.g. `pct set <CTID> --memory 4096 --swap 1024`, `pct resize <CTID> rootfs +10G`, `pct config <CTID>`. "
            "Inside the container use `top`/`ps aux --sort=-%mem`, `df -h`, `journalctl -p warning -n 100`, `systemctl --failed`."),
    "proxmox": ("This is a Proxmox VE host: use `pvesh`, `qm list`, `pct list`, `pvesm status`, `zpool status`, "
                "`journalctl -u pve*` and the web UI on port 8006."),
    "routeros": ("This is MikroTik RouterOS: commands look like `/interface print stats`, `/system resource print`, "
                 "`/log print where topics~\"error\"`, `/interface ethernet monitor <name>`, `/tool ping`."),
    "debian": "Debian Linux: use `apt`, `systemctl`, `journalctl`, `ip -s link`, `ss -s`, `free -h`, `df -h`.",
    "ubuntu": "Ubuntu Linux: use `apt`, `systemctl`, `journalctl`, `ip -s link`, `ss -s`, `free -h`, `df -h`.",
}


def platform_hint(d: Device) -> str | None:
    hints = [PLATFORM_HINTS[k] for k in (d.virtualization, d.os) if k and k in PLATFORM_HINTS]
    return " ".join(dict.fromkeys(hints)) or None


def _device_block(d: Device) -> str:
    lines = [
        f"Hostname: {d.hostname}" + (f" (sysName {d.sys_name})" if d.sys_name and d.sys_name != d.hostname else ""),
        f"Type: {d.device_type or 'unknown'}" + (f", {VIRT[d.virtualization]}" if d.virtualization in VIRT else ""),
        f"Platform: {' '.join(filter(None, [d.vendor, d.hardware])) or 'unknown'}",
        f"OS: {' '.join(filter(None, [d.os, d.version])) or 'unknown'}" + (f", kernel {d.kernel}" if d.kernel else ""),
        f"Uptime: {round(d.uptime / 86400, 1)} days" if d.uptime else "Uptime: unknown",
    ]
    if d.sys_location:
        lines.append(f"Location: {d.sys_location}")
    if hint := platform_hint(d):
        lines.append(f"Platform notes: {hint}")
    return "\n".join(lines)


async def _recent_syslog(session: AsyncSession, device_id: int, around, minutes: int = 120, limit: int = 25) -> str:
    rows = list(await session.scalars(
        select(SyslogMessage)
        .where(SyslogMessage.device_id == device_id,
               SyslogMessage.time >= around - timedelta(minutes=minutes),
               SyslogMessage.time <= around + timedelta(minutes=10),
               SyslogMessage.severity <= 5)
        .order_by(SyslogMessage.time.desc()).limit(limit)
    ))
    if not rows:
        return "(no syslog messages from this device around that time)"
    return "\n".join(
        f"{m.time:%Y-%m-%d %H:%M:%S} [{SEVERITY[m.severity]}] {m.program or ''} {m.message}".strip() for m in reversed(rows)
    )


async def _other_problems(session: AsyncSession, device_id: int, exclude: int | None) -> str:
    rows = list(await session.scalars(
        select(Service).where(Service.device_id == device_id, Service.state > State.OK, Service.id != (exclude or 0))
        .order_by(Service.state.desc()).limit(10)
    ))
    return "\n".join(f"- {State(s.state).name} {s.name}: {s.output}" for s in rows) or "(none)"


async def event_prompt(session: AsyncSession, job: AIJob) -> tuple[Device, str]:
    device = await session.get(Device, job.device_id)
    svc = await session.get(Service, job.service_id)
    ev = await session.scalar(select(StateChange).where(and_(
        StateChange.service_id == job.service_id, StateChange.time == job.event_time)))
    if not device or not svc or not ev:
        raise LookupError("The event no longer exists")

    history = list(await session.scalars(
        select(StateChange).where(StateChange.service_id == svc.id, StateChange.time <= ev.time)
        .order_by(StateChange.time.desc()).limit(10)
    ))
    component = await session.get(Component, svc.component_id) if svc.component_id else None
    group_ids = set(await session.scalars(
        select(device_group_members.c.group_id).where(device_group_members.c.device_id == device.id)))
    levels = (await get_ruleset(session)).levels(svc.check, device.id, group_ids, svc.name)

    parts = [
        "## Device", _device_block(device),
        "## Alert",
        f"Service: {svc.name} (check type '{svc.check}')",
        f"State change: {State(ev.old_state).name} -> {State(ev.new_state).name} at {ev.time:%Y-%m-%d %H:%M:%S %Z}",
        f"Check output: {ev.output}",
        f"Current state: {State(svc.state).name} - {svc.output}",
    ]
    if levels:
        parts.append(f"Thresholds: warn {levels.direction} {levels.warn}, crit {levels.direction} {levels.crit}")
    if svc.perf:
        parts.append(f"Measured values: {svc.perf}")
    if component:
        attrs = {k: v for k, v in (component.attrs or {}).items() if k != "override" and v not in (None, "")}
        parts.append(f"Component: {component.kind} '{component.name}'" + (f" ({component.descr})" if component.descr else "")
                     + (f", attributes {attrs}" if attrs else ""))
    parts += [
        "## Recent state changes of this service (newest first)",
        "\n".join(f"- {h.time:%Y-%m-%d %H:%M} {State(h.old_state).name} -> {State(h.new_state).name}: {h.output}" for h in history),
        "## Other current problems on this device", await _other_problems(session, device.id, svc.id),
        "## Syslog from this device around the event", await _recent_syslog(session, device.id, ev.time),
        "Explain this alert to the on-call engineer.",
    ]
    return device, "\n".join(parts)


async def syslog_prompt(session: AsyncSession, job: AIJob) -> tuple[Device | None, str]:
    msg = await session.scalar(select(SyslogMessage).where(and_(
        SyslogMessage.id == job.syslog_id, SyslogMessage.time == job.syslog_time)))
    if not msg:
        raise LookupError("The syslog message no longer exists")
    device = await session.get(Device, msg.device_id) if msg.device_id else None
    parts = [
        "## Device", _device_block(device) if device else f"Unknown device, source IP {msg.source_ip}",
        "## Syslog message to explain",
        f"{msg.time:%Y-%m-%d %H:%M:%S %Z} severity={SEVERITY[msg.severity]} facility={msg.facility} "
        f"program={msg.program or '-'} host={msg.hostname or msg.source_ip}",
        f"Message: {msg.message}",
    ]
    if device:
        parts += [
            "## Other syslog from this device around that time", await _recent_syslog(session, device.id, msg.time, 30, 30),
            "## Current problems on this device", await _other_problems(session, device.id, None),
        ]
    parts.append("Explain this log message to the on-call engineer.")
    return device, "\n".join(parts)
