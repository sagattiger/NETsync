"""Runs probes: scheduling (jitter, per-kind concurrency), retries, upside-down, heartbeats, metrics,
services and alerts. Checkers only answer "is it up and how fast"; everything here is common to all kinds."""

import asyncio
import logging
import random
from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from netsync.models import Device, Probe, ProbeBeat, Service, State
from netsync.plugins.base import AlertEvent, BackgroundService, CheckResult, MetricSample
from netsync.probing import checkers  # noqa: F401 - registers all kinds
from netsync.probing.base import REGISTRY, ProbeSpec, Result, get_checker, short
from netsync.probing.secrets import decrypt

log = logging.getLogger(__name__)

TICK = 2  # seconds between scheduler passes
GRACE = 5  # seconds a check may run beyond its own timeout before it is cancelled
STATUS_SERVICE = "Status"
RESPONSE_SERVICE = "Response time"


def spec_for(p: Probe, secrets: dict | None = None) -> ProbeSpec:
    return ProbeSpec(kind=p.kind, target=p.target, port=p.port, timeout_s=p.timeout_s or 10, count=p.count or 5,
                     interval_s=p.interval_s, config=dict(p.config or {}),
                     secrets=secrets if secrets is not None else decrypt(p.secrets_enc),
                     last_push_at=p.last_push_at, created_at=p.created_at, probe_id=p.id)


def decide(result: Result, upside_down: bool, retries: int, fail_count: int) -> tuple[int, int, str, bool]:
    """(beat state, new fail_count, message, pending). Pure.

    Up: OK/WARN from the checker. Down: CRIT once ``retries`` consecutive failures are reached; before that the
    run is *pending* (UNKNOWN), which neither changes services nor counts as downtime."""
    up = result.up != upside_down
    msg = result.message or ("up" if result.up else "down")
    if upside_down:
        msg = f"{msg} (expected down)" if up else f"{msg} (should be down)"
    if up:
        return (State.OK if upside_down else result.state if result.state in (State.OK, State.WARN) else State.OK), 0, msg, False
    fail_count += 1
    if fail_count < max(1, retries):
        return State.UNKNOWN, fail_count, f"{msg} (retry {fail_count}/{retries})", True
    return State.CRIT, fail_count, msg, False


def next_delay(interval_s: int, retry_interval_s: int | None, failing: bool) -> float:
    """Seconds until the next run, with ±5 % jitter (max 3 s) so probes drift apart instead of firing together."""
    base = (retry_interval_s or interval_s) if failing else interval_s
    jitter = min(base * 0.05, 3)
    return max(5.0, base + random.uniform(-jitter, jitter))


def uptime_pct(total: int | None, up: int | None) -> float | None:
    """Maintenance runs are excluded from ``total`` already; no runs -> None (not 0 % or 100 %)."""
    if not total:
        return None
    return round(100.0 * (up or 0) / total, 3)


def should_resend(state: int, fail_count: int, retries: int, resend_every: int) -> bool:
    """Re-notify every N checks while down (the first DOWN notification is the normal state change)."""
    extra = fail_count - max(1, retries)
    return state == State.CRIT and resend_every > 0 and extra > 0 and extra % resend_every == 0


async def run_check(spec: ProbeSpec) -> Result | None:
    checker = get_checker(spec.kind)
    try:
        return await asyncio.wait_for(checker.check(spec), spec.timeout_s + GRACE)
    except TimeoutError:
        return Result(False, None, State.CRIT, "timeout")
    except Exception:
        log.exception("probe %s (%s) check crashed", spec.probe_id, spec.kind)
        return Result(False, None, State.CRIT, "check failed")


async def record(session, probe: Probe, device: Device, result: Result, now: datetime | None = None) -> list:
    """Apply one check result: heartbeat, metrics, services, probe state. Returns alert events to dispatch."""
    from netsync.alerting import in_downtime
    from netsync.config import get_settings
    from netsync.poller.pipeline import store_results

    now = now or datetime.now(UTC)
    state, fails, msg, pending = decide(result, probe.upside_down, probe.retries or 1, probe.fail_count or 0)
    probe.fail_count = fails
    maintenance = await in_downtime(session, device.id, None, now)

    metrics = [MetricSample(k, float(v)) for k, v in result.metrics.items() if v is not None]
    if not pending:
        metrics.append(MetricSample("up_pct", 0.0 if state == State.CRIT else 100.0))
    if result.response_ms is not None and "response_ms" not in result.metrics:
        metrics.append(MetricSample("response_ms", float(result.response_ms)))

    checks: list[CheckResult] = []
    if not pending:
        checks.append(CheckResult("probe_status", STATUS_SERVICE, output=msg, state=state))
        if state != State.CRIT and result.response_ms is not None:
            checks.append(CheckResult("probe_response", RESPONSE_SERVICE, value=result.response_ms, unit=" ms",
                                      output=f"{result.response_ms:.0f} ms"))
        if not probe.upside_down:
            checks += result.checks
    events = await store_results(session, device, metrics, checks, now, components=[])

    session.add(ProbeBeat(time=now, probe_id=probe.id, state=state, response_ms=result.response_ms,
                          message=short(msg), maintenance=maintenance))
    if not pending:
        device.status = State.CRIT if state == State.CRIT else State.OK
        device.status_reason = msg if state == State.CRIT else None
    device.last_polled = now
    probe.last_run, probe.last_state, probe.last_message = now, state, short(msg)
    probe.last_response_ms = result.response_ms
    probe.last_error = msg if state == State.CRIT else None
    if result.cert is not None:
        probe.cert = result.cert
    probe.next_run = now + timedelta(seconds=next_delay(probe.interval_s, probe.retry_interval_s, fails > 0))

    if should_resend(state, fails, probe.retries or 1, probe.resend_every or 0):
        svc = await session.scalar(select(Service).where(Service.device_id == device.id,
                                                         Service.name == STATUS_SERVICE))
        if svc:
            url = get_settings().public_url.rstrip("/")
            events.append((svc.id, AlertEvent(device.id, device.hostname, STATUS_SERVICE, State.CRIT, State.CRIT,
                                              f"still down after {fails} checks: {msg}", now, f"{url}/probes/{probe.id}")))
    return events


async def run_one(probe_id: int) -> None:
    """Load, check (without holding a DB connection), record, dispatch."""
    from netsync.alerting import dispatch
    from netsync.db import SessionLocal

    async with SessionLocal() as s:
        probe = await s.get(Probe, probe_id)
        if not probe or not probe.enabled:
            return
        spec = spec_for(probe)
    result = await run_check(spec)
    if result is None:  # nothing to record this time (e.g. push: a heartbeat arrived in time)
        async with SessionLocal() as s:
            probe = await s.get(Probe, probe_id)
            if probe:
                probe.next_run = datetime.now(UTC) + timedelta(seconds=next_delay(probe.interval_s, None, False))
                await s.commit()
        return
    async with SessionLocal() as s:
        probe = await s.get(Probe, probe_id)
        device = await s.get(Device, probe.device_id) if probe else None
        if not probe or not device or not probe.enabled:
            return
        events = await record(s, probe, device, result)
        await s.commit()
    await dispatch(events)


class ProbeService(BackgroundService):
    name = "probes"

    async def run(self, stop: asyncio.Event) -> None:
        from netsync.db import SessionLocal

        sems = {kind: asyncio.Semaphore(c.concurrency) for kind, c in REGISTRY.items()}
        running: set[int] = set()

        async def one(pid: int, kind: str) -> None:
            try:
                async with sems.setdefault(kind, asyncio.Semaphore(20)):
                    await run_one(pid)
            except Exception:
                log.exception("probe %s failed", pid)
            finally:
                running.discard(pid)

        while not stop.is_set():
            try:
                now = datetime.now(UTC)
                async with SessionLocal() as s:
                    probes = list(await s.scalars(select(Probe).where(Probe.enabled.is_(True))))
                    changed = False
                    for p in probes:
                        if p.id in running:
                            continue
                        overdue = p.next_run is None or p.next_run < now - timedelta(seconds=p.interval_s + 30)
                        if overdue and p.last_run is not None:
                            # e.g. after a restart: spread the backlog instead of firing everything at once
                            p.next_run = now + timedelta(seconds=random.uniform(0, min(p.interval_s, 60)))
                            changed = True
                        elif p.next_run is None or p.next_run <= now:
                            running.add(p.id)
                            asyncio.create_task(one(p.id, p.kind))
                    if changed:
                        await s.commit()
            except Exception:
                log.exception("probe scheduler failed")
            try:
                await asyncio.wait_for(stop.wait(), timeout=TICK)
            except TimeoutError:
                pass
