"""SmokePing style latency monitoring.

Also the reference example of a plugin that brings its own background
collector, its own checks and its own device page tab.
"""

import asyncio
import logging
from datetime import UTC, datetime

from icmplib import async_multiping
from sqlalchemy import select

from netsync.db import SessionLocal
from netsync.models import Device, State
from netsync.plugins.base import BackgroundService, CheckResult, MetricSample, Plugin, UITab

log = logging.getLogger(__name__)

INTERVAL = 60
PINGS = 10


class LatencyService(BackgroundService):
    name = "latency"

    async def run(self, stop: asyncio.Event) -> None:
        from netsync.alerting import dispatch
        from netsync.poller.pipeline import store_results

        while not stop.is_set():
            started = asyncio.get_running_loop().time()
            events = []
            try:
                async with SessionLocal() as s:
                    devices = (await s.scalars(select(Device).where(Device.disabled.is_(False)))).all()
                    if devices:
                        hosts = await async_multiping(
                            [d.ip or d.hostname for d in devices],
                            count=PINGS, interval=0.5, timeout=2, privileged=False, concurrent_tasks=100,
                        )
                        now = datetime.now(UTC)
                        for device, h in zip(devices, hosts, strict=True):
                            loss = h.packet_loss * 100
                            metrics = [MetricSample("ping_loss", loss)]
                            if h.is_alive:
                                metrics += [
                                    MetricSample("ping_min", h.min_rtt),
                                    MetricSample("ping_avg", h.avg_rtt),
                                    MetricSample("ping_max", h.max_rtt),
                                    MetricSample("ping_jitter", h.jitter),
                                ]
                                output = f"rtt avg {h.avg_rtt:.1f} ms (min {h.min_rtt:.1f}, max {h.max_rtt:.1f}), loss {loss:.0f}%"
                                checks = [
                                    CheckResult("ping_rtt", "Ping RTT", value=h.avg_rtt, unit="ms", output=output),
                                    CheckResult("ping_loss", "Ping loss", value=loss, unit="%", output=f"{loss:.0f}% packet loss"),
                                ]
                            else:
                                checks = [
                                    CheckResult("ping_rtt", "Ping RTT", state=State.CRIT, output="host unreachable"),
                                    CheckResult("ping_loss", "Ping loss", state=State.CRIT, value=100, unit="%",
                                                output="100% packet loss"),
                                ]
                            events += await store_results(s, device, metrics, checks, now)
                        await s.commit()
                        await dispatch(events)
            except Exception:
                log.exception("latency round failed")
            elapsed = asyncio.get_running_loop().time() - started
            try:
                await asyncio.wait_for(stop.wait(), timeout=max(1, INTERVAL - elapsed))
            except TimeoutError:
                pass


plugin = Plugin(
    name="latency",
    version="0.1.0",
    description="SmokePing style ICMP latency, jitter and packet loss",
    services=[LatencyService()],
    ui_tabs=[UITab(id="latency", label="Latency", view="latency",
                   metrics=["ping_min", "ping_avg", "ping_max", "ping_loss"])],
    builtin=True,
)
