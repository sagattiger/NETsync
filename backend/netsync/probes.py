"""Probes: active checks of any IP address or FQDN, independent of SNMP devices.

Storage choice: every probe owns a lightweight *virtual device* (``device_type="probe"``, no SNMP
polling, no discovery). Its ping metrics go to the regular ``metrics`` hypertable and its
"Ping RTT" / "Ping loss" checks are regular services, so thresholds (rules), problems,
acknowledgements, downtimes, alerts, device-group scoping and dashboards all work unchanged.
"""

import asyncio
import ipaddress
import logging
import re
from datetime import UTC, datetime

from sqlalchemy import select

from netsync.models import Device, Probe, State
from netsync.plugins.base import BackgroundService, CheckResult, MetricSample, Plugin

log = logging.getLogger(__name__)

PROBE_DEVICE_TYPE = "probe"
KINDS = ("icmp",)  # "tcp" (host:port connect time) and "http" (status + response time) can follow
METRICS = ("ping_min", "ping_avg", "ping_max", "ping_jitter", "ping_loss")
INTERVAL_RANGE = (30, 300)
COUNT_RANGE = (1, 20)
TICK = 5  # seconds between "anything due?" checks

_LABEL = re.compile(r"^(?!-)[A-Za-z0-9-]{1,63}(?<!-)$")


def validate_target(value: str) -> str:
    """An IPv4/IPv6 address or a hostname/FQDN. Nothing else: no URLs, ports, spaces or shell characters."""
    v = (value or "").strip()
    if not v or len(v) > 253:
        raise ValueError("target must be an IP address or hostname")
    try:
        return str(ipaddress.ip_address(v))
    except ValueError:
        pass
    host = v[:-1] if v.endswith(".") else v
    labels = host.split(".")
    if not all(_LABEL.match(label) for label in labels):
        raise ValueError("target must be an IP address or hostname (letters, digits, '-' and '.')")
    if labels[-1].isdigit():
        raise ValueError("invalid IP address")  # e.g. 999.1.1.1 or 10.1
    return host.lower()


def device_hostname(name: str) -> str:
    """Hostname of the probe's virtual device: unique, readable in problem lists, never a real host."""
    return f"{name} (probe)"


def probe_results(target: str, h, loss_override: float | None = None) -> tuple[list[MetricSample], list[CheckResult], bool]:
    """Metrics and Ping checks for one icmplib Host result (pure, unit tested)."""
    loss = h.packet_loss * 100 if loss_override is None else loss_override
    metrics = [MetricSample("ping_loss", loss)]
    if h.is_alive:
        metrics += [MetricSample("ping_min", h.min_rtt), MetricSample("ping_avg", h.avg_rtt),
                    MetricSample("ping_max", h.max_rtt), MetricSample("ping_jitter", h.jitter)]
        out = f"rtt avg {h.avg_rtt:.1f} ms (min {h.min_rtt:.1f}, max {h.max_rtt:.1f}), loss {loss:.0f}%"
        checks = [CheckResult("ping_rtt", "Ping RTT", value=h.avg_rtt, unit="ms", output=out),
                  CheckResult("ping_loss", "Ping loss", value=loss, unit="%", output=f"{loss:.0f}% packet loss")]
        return metrics, checks, True
    checks = [CheckResult("ping_rtt", "Ping RTT", state=State.CRIT, output=f"{target} unreachable"),
              CheckResult("ping_loss", "Ping loss", state=State.CRIT, value=100, unit="%", output="100% packet loss")]
    return metrics, checks, False


async def ping(target: str, count: int):
    """One round. Resolves FQDNs on every call (icmplib does the lookup), unprivileged sockets."""
    from icmplib import async_ping

    return await async_ping(target, count=count, interval=0.5, timeout=2, privileged=False)


async def run_probe(session, probe: Probe, device: Device) -> list:
    from netsync.poller.pipeline import store_results

    now = datetime.now(UTC)
    error = None
    try:
        host = await ping(probe.target, probe.count)
        metrics, checks, alive = probe_results(probe.target, host)
    except Exception as e:  # NameLookupError, socket errors...
        error = f"{type(e).__name__}: {e}"[:500]
        metrics = [MetricSample("ping_loss", 100.0)]
        checks = [CheckResult("ping_rtt", "Ping RTT", state=State.CRIT, output=f"cannot ping {probe.target}: {e}"),
                  CheckResult("ping_loss", "Ping loss", state=State.CRIT, value=100, unit="%", output="100% packet loss")]
        alive = False
    probe.last_run, probe.last_error = now, error
    device.status = State.OK if alive else State.CRIT
    device.status_reason = None if alive else checks[0].output
    device.last_polled = now
    return await store_results(session, device, metrics, checks, now, components=[])


class ProbeService(BackgroundService):
    name = "probes"

    async def run(self, stop: asyncio.Event) -> None:
        from netsync.alerting import dispatch
        from netsync.db import SessionLocal

        running: set[int] = set()

        async def one(probe_id: int) -> None:
            try:
                async with SessionLocal() as s:
                    probe = await s.get(Probe, probe_id)
                    device = await s.get(Device, probe.device_id) if probe else None
                    if not probe or not device or not probe.enabled:
                        return
                    events = await run_probe(s, probe, device)
                    await s.commit()
                await dispatch(events)
            except Exception:
                log.exception("probe %s failed", probe_id)
            finally:
                running.discard(probe_id)

        while not stop.is_set():
            try:
                now = datetime.now(UTC)
                async with SessionLocal() as s:
                    rows = (await s.execute(select(Probe.id, Probe.last_run, Probe.interval_s)
                                            .where(Probe.enabled.is_(True)))).all()
                for pid, last, interval in rows:
                    if pid not in running and (last is None or (now - last).total_seconds() >= interval - 1):
                        running.add(pid)
                        asyncio.create_task(one(pid))
            except Exception:
                log.exception("probe scheduler failed")
            try:
                await asyncio.wait_for(stop.wait(), timeout=TICK)
            except TimeoutError:
                pass


plugin = Plugin(
    name="probes",
    version="0.1.0",
    description="Ping any IP address or FQDN (probes), with latency/loss graphs, checks and alerts",
    services=[ProbeService()],
    builtin=True,
)
