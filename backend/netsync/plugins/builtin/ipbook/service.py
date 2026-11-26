"""IP Book ping service: every few minutes pings every IP in the list, keeps its health, stores response times as
metrics on one virtual device, and - only for IPs whose "Alert when down" is on - keeps a service so a down IP
becomes a normal problem (Problems, notification rules, acknowledge, downtime)."""

from __future__ import annotations

import asyncio
import ipaddress
import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, select

from netsync.models import Component, Device, IpbNetwork, IpbRow, Service, State
from netsync.plugins.base import BackgroundService, CheckResult, MetricSample
from netsync.plugins.builtin.ipbook import health
from netsync.plugins.builtin.ipbook.columns import ip_keys
from netsync.plugins.builtin.ipbook.netlogic import row_ips

log = logging.getLogger(__name__)
KIND = "ipbook_ip"
CHECK = "ipbook_ping"
HOSTNAME = "ipbook.netsync"
TICK = 30
STATES = {"up": State.OK, "down": State.CRIT}


def effective_alert(row, network_alerts: list[bool]) -> bool:
    """The row's own switch when set, else on when any network holding its IPs has it on."""
    if row.alert_when_down is not None:
        return bool(row.alert_when_down)
    return any(network_alerts)


def check_for(row, ip: str, state: dict) -> CheckResult:
    """The alert service of one (row, IP). A sensitive row gets a neutral name and output (Problems are visible to
    every role): no IP, no service or host name."""
    st = STATES.get(state.get("state"), State.UNKNOWN)
    if row.sensitive:
        name, output = f"IP Book: sensitive entry #{row.id}", "down" if st == State.CRIT else "up"
    else:
        vals = row.values or {}
        label = (vals.get("service") or {}).get("name") or vals.get("hostname") or f"entry #{row.id}"
        name = f"{label} {ip}"
        rtt = state.get("rtt")
        output = (f"{ip} answers in {rtt} ms" if st == State.OK and rtt is not None
                  else f"{ip} does not answer ping" if st == State.CRIT else f"{ip}: no answer yet")
    return CheckResult(CHECK, name, output=output, state=st, kind=KIND, index=health.key(row.id, ip))


def services_to_remove(existing_service_indexes: set[str], alerting_indexes: set[str]) -> set[str]:
    return set(existing_service_indexes) - set(alerting_indexes)


async def ensure_device(session) -> Device:
    dev = await session.scalar(select(Device).where(Device.device_type == "ipbook"))
    if dev is None:
        dev = Device(hostname=HOSTNAME, device_type="ipbook", sys_name="IP Book", vendor="NETsync", os="ipbook",
                     status=State.UNKNOWN, snmp_community=None)
        session.add(dev)
        await session.flush()
    return dev


async def run_once(now: datetime | None = None) -> None:
    """One round: ping everything, update health, metrics, alert services and missing rows."""
    from netsync.alerting import dispatch, redis
    from netsync.db import SessionLocal
    from netsync.plugins.builtin.ipbook.api import _columns
    from netsync.poller.pipeline import store_results

    now = now or datetime.now(UTC)
    async with SessionLocal() as s:
        cols = await _columns(s)
        rows = list(await s.scalars(select(IpbRow)))
        nets = [(ipaddress.ip_network(n.cidr, strict=False), n.alert_when_down)
                for n in await s.scalars(select(IpbNetwork).where(IpbNetwork.hidden.is_(False)))]
        await s.commit()
    ip_cols = ip_keys(cols)
    targets = [(r, ip) for r in rows for ip in sorted({ip for _, ip in row_ips(r, ip_cols)})]
    results = await health.ping(sorted({ip for _, ip in targets}))  # no DB connection held while pinging

    rd = redis()
    prev = await health.read(rd)
    states = {health.key(r.id, ip): health.next_state(prev.get(health.key(r.id, ip)), *results.get(ip, (False, None)), now)
              for r, ip in targets}
    await health.write(rd, states, drop=set(prev) - set(states))

    async with SessionLocal() as s:
        dev = await ensure_device(s)
        comps = {c.index: c for c in await s.scalars(select(Component).where(
            Component.device_id == dev.id, Component.kind == KIND))}
        for r, ip in targets:
            idx = health.key(r.id, ip)
            c = comps.get(idx)
            if c is None:
                c = Component(device_id=dev.id, module="ipbook", kind=KIND, index=idx, name=idx, attrs={}, values={})
                s.add(c)
                comps[idx] = c
            c.name, c.deleted, c.last_seen = ("sensitive entry" if r.sensitive else ip), False, now
        stale = [c.id for i, c in comps.items() if i not in states]
        if stale:
            await s.execute(delete(Service).where(Service.component_id.in_(stale)))
            await s.execute(delete(Component).where(Component.id.in_(stale)))
            comps = {i: c for i, c in comps.items() if i in states}
        await s.flush()

        metrics, checks, alerting = [], [], set()
        for r, ip in targets:
            idx = health.key(r.id, ip)
            st = states[idx]
            loss = 0.0 if st["state"] == "up" and st["misses"] == 0 else 100.0
            metrics.append(MetricSample("ping_loss", loss, kind=KIND, index=idx))
            if st.get("rtt") is not None:
                metrics.append(MetricSample("ping_rtt", st["rtt"], kind=KIND, index=idx))
            addr = ipaddress.ip_address(ip)
            if effective_alert(r, [on for n, on in nets if n.version == addr.version and addr in n]):
                alerting.add(idx)
                checks.append(check_for(r, ip, st))
        # alert switched off, or the row/IP is gone: its service (and problem) goes away
        by_comp = {c.id: i for i, c in comps.items()}
        svcs = list(await s.scalars(select(Service).where(Service.device_id == dev.id)))
        drop = services_to_remove({by_comp.get(v.component_id, "") for v in svcs}, alerting)
        names = {c.name for c in checks}
        gone = [v.id for v in svcs if by_comp.get(v.component_id, "") in drop or
                (by_comp.get(v.component_id) in alerting and v.name not in names)]
        if gone:
            await s.execute(delete(Service).where(Service.id.in_(gone)))
        events = await store_results(s, dev, metrics, checks, now, list(comps.values()))
        dev.status = State.OK
        dev.last_polled = now
        await s.commit()
    await dispatch(events)


class IpBookPingService(BackgroundService):
    name = "ipbook"

    async def run(self, stop: asyncio.Event) -> None:
        from netsync.db import SessionLocal
        from netsync.plugins.builtin.ipbook import learn, plugin
        from netsync.plugins.settings import cached_settings

        last_run: datetime | None = None
        last_missing: datetime | None = None
        while not stop.is_set():
            try:
                enabled, cfg = await cached_settings(plugin)
                now = datetime.now(UTC)
                every = timedelta(minutes=max(1, min(60, int(cfg.get("interval_min") or 5))))
                if enabled and (last_run is None or now - last_run >= every):
                    last_run = now
                    await run_once(now)
                if enabled and (last_missing is None or now - last_missing >= timedelta(hours=1)):
                    last_missing = now
                    async with SessionLocal() as s:
                        await learn.mark_missing(s, now)
                        await s.commit()
            except Exception:
                log.exception("IP Book ping round failed")
            try:
                await asyncio.wait_for(stop.wait(), timeout=TICK)
            except TimeoutError:
                pass
