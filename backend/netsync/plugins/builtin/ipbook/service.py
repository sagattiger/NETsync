"""IP Book ping service: every few minutes pings every IP in the list, keeps its health, stores response times as
metrics on one virtual device, and - only for IPs whose "Alert when down" is on - keeps a service so a down IP
becomes a normal problem (Problems, notification rules, acknowledge, downtime)."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, select

from netsync.models import Component, Device, IpbAddress, IpbBook, IpbRow, Service, State
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


def check_for(row, ip: str, state: dict, position: int = 1) -> CheckResult:
    """The alert service of one (row, IP). A sensitive row gets a neutral name and output (Problems are visible to
    every role): no IP, no service or host name - its IPs are told apart by their position ("address 2")."""
    st = STATES.get(state.get("state"), State.UNKNOWN)
    if row.sensitive:
        name, output = f"IP Book: sensitive entry #{row.id} address {position}", "down" if st == State.CRIT else "up"
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


@dataclass
class Target:
    """One address to ping: a service entry's IP or a used address of an IP book."""

    key: str  # health / component index: "<row id>:<ip>" or "a<book id>:<ip>"
    ip: str
    alert: bool
    check: Callable[[dict], CheckResult]
    label: str  # component name (no IP for sensitive entries)


def targets(rows, books: dict, addresses, ip_cols: set[str]) -> list[Target]:
    """Every address to ping, with its effective "Alert when down" (its own switch, else its book's)."""
    out: list[Target] = []
    for r in rows:
        book = books.get(r.book_id)
        if book is None:
            continue
        for pos, ip in enumerate(sorted({ip for _, ip in row_ips(r, ip_cols)}), start=1):
            key = health.key(r.id, ip)
            out.append(Target(key, ip, effective_alert(r, [book.alert_when_down]),
                              lambda st, r=r, ip=ip, pos=pos: check_for(r, ip, st, pos),
                              "sensitive entry" if r.sensitive else ip))
    for a in addresses:
        book = books.get(a.book_id)
        if book is None or a.reserved or not any(v not in (None, "", []) for v in (a.values or {}).values()):
            continue
        key = f"a{a.book_id}:{a.ip}"
        alert = a.alert_when_down if a.alert_when_down is not None else bool(book.alert_when_down)
        name = (a.values or {}).get("addr_hostname")
        label = f"{name} {a.ip}" if name else f"{a.ip} ({book.title})"
        out.append(Target(key, a.ip, alert, lambda st, key=key, ip=a.ip, label=label: _address_check(key, ip, label, st), a.ip))
    return out


def _address_check(key: str, ip: str, label: str, state: dict) -> CheckResult:
    st = STATES.get(state.get("state"), State.UNKNOWN)
    rtt = state.get("rtt")
    output = (f"{ip} answers in {rtt} ms" if st == State.OK and rtt is not None
              else f"{ip} does not answer ping" if st == State.CRIT else f"{ip}: no answer yet")
    return CheckResult(CHECK, label, output=output, state=st, kind=KIND, index=key)


async def run_once(now: datetime | None = None) -> None:
    """One round: ping everything, update health, metrics and alert services."""
    from netsync.alerting import dispatch, redis
    from netsync.db import SessionLocal
    from netsync.plugins.builtin.ipbook.api import _columns
    from netsync.poller.pipeline import store_results

    now = now or datetime.now(UTC)
    async with SessionLocal() as s:
        cols = await _columns(s)
        books = {b.id: b for b in await s.scalars(select(IpbBook))}
        rows = list(await s.scalars(select(IpbRow).where(IpbRow.book_id.is_not(None))))
        addrs = list(await s.scalars(select(IpbAddress)))
        await s.commit()
    tlist = targets(rows, books, addrs, ip_keys(cols))
    results = await health.ping(sorted({t.ip for t in tlist}))  # no DB connection held while pinging

    rd = redis()
    prev = await health.read(rd)
    states = {t.key: health.next_state(prev.get(t.key), *results.get(t.ip, (False, None)), now) for t in tlist}
    await health.write(rd, states, drop=set(prev) - set(states))

    async with SessionLocal() as s:
        dev = await ensure_device(s)
        comps = {c.index: c for c in await s.scalars(select(Component).where(
            Component.device_id == dev.id, Component.kind == KIND))}
        for t in tlist:
            c = comps.get(t.key)
            if c is None:
                c = Component(device_id=dev.id, module="ipbook", kind=KIND, index=t.key, name=t.label, attrs={}, values={})
                s.add(c)
                comps[t.key] = c
            c.name, c.deleted, c.last_seen = t.label, False, now
        stale = [c.id for i, c in comps.items() if i not in states]
        if stale:
            await s.execute(delete(Service).where(Service.component_id.in_(stale)))
            await s.execute(delete(Component).where(Component.id.in_(stale)))
            comps = {i: c for i, c in comps.items() if i in states}
        await s.flush()

        metrics, checks, alerting = [], [], set()
        for t in tlist:
            st = states[t.key]
            loss = 0.0 if st["state"] == "up" and st["misses"] == 0 else 100.0
            metrics.append(MetricSample("ping_loss", loss, kind=KIND, index=t.key))
            if st.get("rtt") is not None:
                metrics.append(MetricSample("ping_rtt", st["rtt"], kind=KIND, index=t.key))
            if t.alert:
                alerting.add(t.key)
                checks.append(t.check(st))
        # alert switched off, or the entry/address is gone: its service (and problem) goes away
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
        from netsync.plugins.builtin.ipbook import plugin
        from netsync.plugins.settings import cached_settings

        last_run: datetime | None = None
        while not stop.is_set():
            try:
                enabled, cfg = await cached_settings(plugin)
                now = datetime.now(UTC)
                every = timedelta(minutes=max(1, min(60, int(cfg.get("interval_min") or 5))))
                if enabled and (last_run is None or now - last_run >= every):
                    last_run = now
                    await run_once(now)
            except Exception:
                log.exception("IP Book ping round failed")
            try:
                await asyncio.wait_for(stop.wait(), timeout=TICK)
            except TimeoutError:
                pass
