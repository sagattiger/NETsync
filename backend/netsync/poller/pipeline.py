"""Discovery and polling of a single device."""

import logging
import time
from datetime import UTC, datetime

from sqlalchemy import delete, insert, select
from sqlalchemy.ext.asyncio import AsyncSession

from netsync.config import get_settings
from netsync.models import Component, Device, Metric, Service, State, StateChange
from netsync.plugins.base import AlertEvent, CheckResult, DeviceContext, MetricSample
from netsync.plugins.registry import registry
from netsync.rules.engine import get_ruleset
from netsync.snmp.client import SnmpClient, SnmpError

log = logging.getLogger(__name__)


async def load_components(session: AsyncSession, device: Device) -> list[Component]:
    return list(await session.scalars(select(Component).where(Component.device_id == device.id)))


async def discover_device(session: AsyncSession, device: Device) -> None:
    now = datetime.now(UTC)
    snmp = SnmpClient.for_device(device)
    existing = await load_components(session, device)
    by_key = {(c.kind, c.index): c for c in existing}
    ctx = DeviceContext(device, snmp, existing, now)

    for module in registry.modules:
        if not module.applies_to(device):
            continue
        try:
            specs = await module.discover(ctx)
        except SnmpError as e:
            if module.name == "system":
                raise
            log.info("%s: discovery module %s failed: %s", device.hostname, module.name, e)
            continue
        except Exception:
            log.exception("%s: discovery module %s crashed", device.hostname, module.name)
            continue

        seen = set()
        for spec in specs:
            key = (spec.kind, spec.index)
            seen.add(key)
            comp = by_key.get(key)
            if comp is None:
                comp = Component(device_id=device.id, kind=spec.kind, index=spec.index, values={})
                session.add(comp)
                by_key[key] = comp
            comp.module = module.name
            comp.name = spec.name
            comp.descr = spec.descr
            # keep user overrides (e.g. monitor flag) that discovery would otherwise reset
            comp.attrs = {**spec.attrs, **(comp.attrs or {}).get("override", {}),
                          "override": (comp.attrs or {}).get("override", {})}
            comp.deleted = False
            comp.last_seen = now
        for key, comp in by_key.items():
            if key[0] in module.kinds and key not in seen and not comp.deleted:
                comp.deleted = True
                await session.execute(delete(Service).where(Service.component_id == comp.id))

    device.last_discovered = now
    await session.flush()
    log.info("%s: discovered %d components", device.hostname, sum(not c.deleted for c in by_key.values()))


async def store_results(
    session: AsyncSession,
    device: Device,
    metrics: list[MetricSample],
    checks: list[CheckResult],
    now: datetime,
    components: list[Component] | None = None,
) -> list[tuple[int, AlertEvent]]:
    """Persist metrics and check results. Returns state change events to dispatch after commit."""
    if components is None:
        components = await load_components(session, device)
    comp_ids = {(c.kind, c.index): c.id for c in components}

    rows = []
    for m in metrics:
        cid = comp_ids.get((m.kind, m.index), 0) if m.kind else 0
        if m.kind and not cid:
            continue
        rows.append({"time": now, "device_id": device.id, "component_id": cid, "name": m.name, "value": float(m.value)})
    if rows:
        await session.execute(insert(Metric), rows)

    rules = await get_ruleset(session)
    services = {
        s.name: s for s in await session.scalars(select(Service).where(Service.device_id == device.id))
    }
    events: list[tuple[int, AlertEvent]] = []
    url = get_settings().public_url.rstrip("/")
    for cr in checks:
        state, output = rules.evaluate(cr, device)
        svc = services.get(cr.name)
        if svc is None:
            svc = Service(device_id=device.id, name=cr.name, check=cr.check, state=State.UNKNOWN, last_change=now)
            session.add(svc)
            await session.flush()
            services[cr.name] = svc
        svc.component_id = comp_ids.get((cr.kind, cr.index)) if cr.kind else None
        old = svc.state
        svc.output = output
        svc.perf = {**cr.perf, **({"value": cr.value} if cr.value is not None else {})}
        svc.last_check = now
        if old != state:
            svc.state = state
            svc.last_change = now
            if state == State.OK:
                svc.acknowledged, svc.ack_comment, svc.ack_by = False, None, None
            session.add(StateChange(time=now, service_id=svc.id, device_id=device.id,
                                    old_state=old, new_state=state, output=output))
            # first check result after creation is not an alert
            if not (old == State.UNKNOWN and state == State.OK):
                events.append((svc.id, AlertEvent(device.id, device.hostname, cr.name, old, state, output, now,
                                                  f"{url}/devices/{device.id}")))
    return events


async def poll_device(session: AsyncSession, device: Device) -> list[tuple[int, AlertEvent]]:
    started = time.monotonic()
    now = datetime.now(UTC)
    snmp = SnmpClient.for_device(device)
    components = await load_components(session, device)
    ctx = DeviceContext(device, snmp, components, now)
    metrics: list[MetricSample] = []
    checks: list[CheckResult] = []
    by_key = {(c.kind, c.index): c for c in components}

    reachable = True
    for module in registry.modules:
        if not module.applies_to(device):
            continue
        try:
            res = await module.poll(ctx)
        except SnmpError as e:
            if module.name == "system":
                reachable = False
                checks.append(CheckResult("snmp", "SNMP", state=State.CRIT, output=f"SNMP unreachable: {e}"))
                break
            log.info("%s: poll module %s failed: %s", device.hostname, module.name, e)
            continue
        except Exception:
            log.exception("%s: poll module %s crashed", device.hostname, module.name)
            continue
        metrics += res.metrics
        checks += res.checks
        for key, values in res.values.items():
            if comp := by_key.get(key):
                comp.values = values

    duration = time.monotonic() - started
    if reachable:
        checks.append(CheckResult("snmp", "SNMP", state=State.OK, output=f"polled in {duration:.2f}s"))
        metrics.append(MetricSample("poll_duration", duration))
    device.status = State.OK if reachable else State.CRIT
    device.status_reason = None if reachable else checks[-1].output
    device.last_polled = now
    device.poll_duration = duration
    return await store_results(session, device, metrics, checks, now, components)
