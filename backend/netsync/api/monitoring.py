"""Problems, acknowledgements, downtimes, threshold rules, notification rules."""

from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, HTTPException
from sqlalchemy import and_, func, or_, select

from netsync import notify_rules
from netsync.api.collab import author_avatars, comment_out
from netsync.api.deps import CurrentUser, Session, device_scope, get_device_for, require
from netsync.api.schemas import (
    AckIn,
    DowntimeIn,
    DowntimeOut,
    NotificationRuleIn,
    NotificationRuleOut,
    ProblemOut,
    RuleIn,
    RuleOut,
)
from netsync.models import (
    AIJob,
    Device,
    Downtime,
    EventComment,
    NotificationRule,
    Role,
    Service,
    State,
    StateChange,
    ThresholdRule,
    real_device,
)
from netsync.plugins.base import AlertEvent
from netsync.plugins.registry import registry
from netsync.rules import engine

router = APIRouter(tags=["monitoring"])


# --------------------------------------------------------------------------- overview

@router.get("/overview")
async def overview(user: CurrentUser, session: Session):
    devices = await session.execute(
        device_scope(select(Device.status, func.count())
                     .where(real_device()).group_by(Device.status), user)
    )
    services = await session.execute(
        device_scope(select(Service.state, func.count()).group_by(Service.state), user, Service.device_id)
    )
    unhandled = await session.scalar(
        device_scope(
            select(func.count()).select_from(Service).where(Service.state > 0, Service.acknowledged.is_(False)),
            user,
            Service.device_id,
        )
    )
    return {
        "devices": {State(s).name: n for s, n in devices},
        "services": {State(s).name: n for s, n in services},
        "unhandled": unhandled or 0,
    }


RESOLVED_VISIBLE_SECONDS = 120


def problem_episode(history: list, current_state: int):
    """Given a service's state changes (newest first), return (episode_events, started, resolved_at).

    An episode runs from the change out of OK up to now (active), or up to the change back
    to OK (resolved). ``episode_events`` are the non-OK changes in it, newest first."""
    events = list(history)
    resolved_at = None
    if current_state == State.OK:
        if not events or events[0].new_state != State.OK or events[0].old_state == State.OK:
            return [], None, None
        resolved_at = events[0].time
        events = events[1:]
    episode = []
    for ev in events:
        if ev.new_state == State.OK:
            break
        episode.append(ev)
        if ev.old_state == State.OK:
            break  # this change opened the problem
    if not episode:
        return [], None, None  # e.g. UNKNOWN -> OK on the first check is not a resolved problem
    return episode, episode[-1].time, resolved_at


@router.get("/problems", response_model=list[ProblemOut])
async def problems(user: CurrentUser, session: Session, include_acked: bool = True,
                   include_resolved: bool = True, device_id: int | None = None):
    """Open problems, plus problems resolved within the last 120 s (shown green, then dropped)."""
    now = datetime.now(UTC)
    cond = Service.state > State.OK
    if include_resolved:
        cond = or_(cond, and_(Service.state == State.OK,
                              Service.last_change >= now - timedelta(seconds=RESOLVED_VISIBLE_SECONDS)))
    q = (
        select(Service, Device.hostname)
        .join(Device, Device.id == Service.device_id)
        .where(cond)
        .order_by(Service.state.desc(), Service.last_change.desc())
    )
    if not include_acked:
        q = q.where(or_(Service.acknowledged.is_(False), Service.state == State.OK))
    if device_id:
        q = q.where(Service.device_id == device_id)
    rows = list(await session.execute(device_scope(q, user)))
    if not rows:
        return []

    service_ids = [svc.id for svc, _ in rows]
    history: dict[int, list] = {}
    for sc in await session.scalars(
        select(StateChange).where(StateChange.service_id.in_(service_ids),
                                  StateChange.time >= now - timedelta(days=30))
        .order_by(StateChange.service_id, StateChange.time.desc())
    ):
        if len(history.setdefault(sc.service_id, [])) < 50:
            history[sc.service_id].append(sc)

    comments = list(await session.scalars(
        select(EventComment).where(EventComment.service_id.in_(service_ids)).order_by(EventComment.created_at)))
    avatars = await author_avatars(session, comments)
    by_event: dict[tuple, list[dict]] = {}
    for c in comments:
        by_event.setdefault((c.service_id, c.event_time), []).append(comment_out(c, avatars))

    jobs = {(j.service_id, j.event_time): j.status for j in await session.scalars(
        select(AIJob).where(AIJob.service_id.in_(service_ids), AIJob.status.in_(["pending", "running"])))}

    out = []
    for svc, hostname in rows:
        episode, started, resolved_at = problem_episode(history.get(svc.id, []), svc.state)
        if svc.state == State.OK and resolved_at is None:
            continue  # went OK without ever being a problem (e.g. first check)
        latest = episode[0] if episode else None
        thread = [c for ev in reversed(episode) for c in by_event.get((svc.id, ev.time), [])]
        event = None
        if latest:
            event = {"time": latest.time, "service_id": svc.id, "service": svc.name, "old_state": latest.old_state,
                     "new_state": latest.new_state, "output": latest.output, "comments": thread,
                     "pinned": any(c["pinned"] for c in thread)}
        out.append(ProblemOut.model_validate(svc).model_copy(update={
            "hostname": hostname,
            "resolved": svc.state == State.OK,
            "problem_state": latest.new_state if latest else svc.state,
            "problem_since": started,
            "resolved_at": resolved_at,
            "duration": ((resolved_at or now) - started).total_seconds() if started else None,
            "event": event,
            "ai_status": jobs.get((svc.id, latest.time)) if latest else None,
        }))
    # open problems first (worst on top), recently resolved ones at the bottom
    out.sort(key=lambda p: (p.resolved, -p.problem_state, -(p.last_change.timestamp() if p.last_change else 0)))
    return out


async def _service_for(session, user, service_id: int) -> Service:
    svc = await session.get(Service, service_id)
    if not svc:
        raise HTTPException(404, "Service not found")
    await get_device_for(session, user, svc.device_id)
    return svc


@router.post("/services/{service_id}/ack")
async def acknowledge(service_id: int, body: AckIn, session: Session, user=require(Role.OPERATOR)):
    svc = await _service_for(session, user, service_id)
    svc.acknowledged, svc.ack_comment, svc.ack_by = True, body.comment, user.username
    await session.commit()
    return {"ok": True}


@router.delete("/services/{service_id}/ack")
async def remove_ack(service_id: int, session: Session, user=require(Role.OPERATOR)):
    svc = await _service_for(session, user, service_id)
    svc.acknowledged, svc.ack_comment, svc.ack_by = False, None, None
    await session.commit()
    return {"ok": True}


# --------------------------------------------------------------------------- downtimes

@router.get("/downtimes", response_model=list[DowntimeOut])
async def list_downtimes(user: CurrentUser, session: Session, active: bool = False):
    q = device_scope(select(Downtime).order_by(Downtime.start.desc()), user, Downtime.device_id)
    if active:
        now = datetime.now(UTC)
        q = q.where(Downtime.start <= now, Downtime.end >= now)
    return list(await session.scalars(q))


@router.post("/downtimes", response_model=DowntimeOut)
async def add_downtime(body: DowntimeIn, session: Session, user=require(Role.OPERATOR)):
    await get_device_for(session, user, body.device_id)
    if body.end <= body.start:
        raise HTTPException(400, "End must be after start")
    dt = Downtime(**body.model_dump(), author=user.username)
    session.add(dt)
    await session.commit()
    return dt


@router.delete("/downtimes/{downtime_id}")
async def delete_downtime(downtime_id: int, session: Session, user=require(Role.OPERATOR)):
    dt = await session.get(Downtime, downtime_id)
    if not dt:
        raise HTTPException(404)
    await get_device_for(session, user, dt.device_id)
    await session.delete(dt)
    await session.commit()
    return {"ok": True}


# --------------------------------------------------------------------------- threshold rules

@router.get("/rules", response_model=list[RuleOut])
async def list_rules(user: CurrentUser, session: Session):
    return list(await session.scalars(select(ThresholdRule).order_by(ThresholdRule.check, ThresholdRule.priority)))


@router.get("/rules/defaults")
async def rule_defaults(user: CurrentUser):
    return {k: v.__dict__ for k, v in engine.DEFAULT_LEVELS.items()}


@router.post("/rules", response_model=RuleOut, dependencies=[require(Role.ADMIN)])
async def add_rule(body: RuleIn, session: Session):
    rule = ThresholdRule(**body.model_dump())
    session.add(rule)
    await session.commit()
    engine.invalidate()
    return rule


@router.put("/rules/{rule_id}", response_model=RuleOut, dependencies=[require(Role.ADMIN)])
async def update_rule(rule_id: int, body: RuleIn, session: Session):
    rule = await session.get(ThresholdRule, rule_id)
    if not rule:
        raise HTTPException(404)
    for k, v in body.model_dump().items():
        setattr(rule, k, v)
    await session.commit()
    engine.invalidate()
    return rule


@router.delete("/rules/{rule_id}", dependencies=[require(Role.ADMIN)])
async def delete_rule(rule_id: int, session: Session):
    rule = await session.get(ThresholdRule, rule_id)
    if rule:
        await session.delete(rule)
        await session.commit()
    engine.invalidate()
    return {"ok": True}


# --------------------------------------------------------------------------- notifications

@router.get("/notifications/channels")
async def channels(user: CurrentUser):
    return [{"name": c.name, "label": c.label, "fields": c.config_fields} for c in registry.channels.values()]


@router.get("/notifications/problem-types")
async def notification_problem_types(user: CurrentUser):
    return [{"key": k, "label": label, "checks": sorted(checks)} for k, label, checks in notify_rules.PROBLEM_TYPES]


def _rule_out(rule: NotificationRule) -> NotificationRuleOut:
    ch = registry.channels.get(rule.channel)
    config, secrets_set = notify_rules.public_config(ch.config_fields if ch else [], rule.config or {})
    out = NotificationRuleOut.model_validate(rule)
    return out.model_copy(update={"config": config, "secrets_set": secrets_set})


def _apply_rule(rule: NotificationRule, body: NotificationRuleIn) -> None:
    ch = registry.channels.get(body.channel)
    if not ch:
        raise HTTPException(400, f"Unknown channel {body.channel}")
    if not body.name.strip():
        raise HTTPException(400, "Name is required")
    old = rule.config if rule.channel == body.channel else None
    try:
        config = notify_rules.clean_config(ch.config_fields, body.config, old)
        types = notify_rules.clean_types(body.problem_types)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    rule.name, rule.channel, rule.config = body.name.strip(), body.channel, config
    rule.min_state, rule.notify_recovery = body.min_state, body.notify_recovery
    rule.device_group_id, rule.enabled, rule.problem_types = body.device_group_id, body.enabled, types


@router.get("/notifications", response_model=list[NotificationRuleOut], dependencies=[require(Role.ADMIN)])
async def list_notification_rules(session: Session):
    return [_rule_out(r) for r in await session.scalars(select(NotificationRule).order_by(NotificationRule.name))]


@router.post("/notifications", response_model=NotificationRuleOut, dependencies=[require(Role.ADMIN)])
async def add_notification_rule(body: NotificationRuleIn, session: Session):
    rule = NotificationRule(config={}, sent_alert=0, sent_recovery=0, sent_failed=0)
    _apply_rule(rule, body)
    session.add(rule)
    await session.commit()
    return _rule_out(rule)


@router.put("/notifications/{rule_id}", response_model=NotificationRuleOut, dependencies=[require(Role.ADMIN)])
async def update_notification_rule(rule_id: int, body: NotificationRuleIn, session: Session):
    rule = await session.get(NotificationRule, rule_id)
    if not rule:
        raise HTTPException(404)
    _apply_rule(rule, body)
    await session.commit()
    return _rule_out(rule)


@router.delete("/notifications/{rule_id}", dependencies=[require(Role.ADMIN)])
async def delete_notification_rule(rule_id: int, session: Session):
    rule = await session.get(NotificationRule, rule_id)
    if rule:
        await session.delete(rule)
        await session.commit()
    return {"ok": True}


@router.post("/notifications/{rule_id}/test", dependencies=[require(Role.ADMIN)])
async def test_notification(rule_id: int, session: Session):
    rule = await session.get(NotificationRule, rule_id)
    if not rule or rule.channel not in registry.channels:
        raise HTTPException(404)
    ev = AlertEvent(0, "netsync-test", "Test notification", State.OK, State.CRIT,
                    "This is a test notification from NETsync", datetime.now(UTC), "")
    try:
        await registry.channels[rule.channel].send(ev, rule.config)
    except Exception as e:
        raise HTTPException(502, f"Sending failed: {notify_rules.error_text(e, rule.config)}") from e
    return {"ok": True}


# --------------------------------------------------------------------------- problem history

HISTORY_BUCKETS = {"1h": 60, "6h": 300, "24h": 900, "7d": 3600, "30d": 6 * 3600, "1y": 86400}
HISTORY_SPAN = {"1h": 3600, "6h": 6 * 3600, "24h": 86400, "7d": 7 * 86400, "30d": 30 * 86400, "1y": 365 * 86400}


def problem_series(start_states: dict[int, int], changes: list[tuple[datetime, int, int]], start: datetime,
                   end: datetime, step: int) -> list[dict]:
    """Open problems at the end of each bucket, plus problems opened and resolved in it.

    Each service's state is followed from ``start_states`` (its state when the window starts; OK when it had no
    change before) through ``changes`` = (time, service_id, new_state) sorted by time. A problem opens when a service
    goes from OK to WARN/CRIT/UNKNOWN and is resolved when it goes back to OK; WARN <-> CRIT is not a new one, and a
    brand-new service settling from UNKNOWN to OK is not a resolution."""
    state = dict(start_states)
    open_now = sum(1 for v in state.values() if v != State.OK)
    out = []
    n = max(1, int((end - start).total_seconds() // step) + 1)
    i = 0
    for b in range(n):
        b_start = start + timedelta(seconds=b * step)
        b_end = b_start + timedelta(seconds=step)
        new = resolved = 0
        peak = open_now
        while i < len(changes) and changes[i][0] < b_end:
            _, sid, new_state = changes[i]
            was = state.get(sid, State.OK)
            if was == State.OK and new_state != State.OK:
                new += 1
                open_now += 1
            elif was != State.OK and new_state == State.OK:
                resolved += 1
                open_now -= 1
            state[sid] = new_state
            peak = max(peak, open_now)
            i += 1
        out.append({"t": b_start.isoformat(), "open": open_now, "peak": peak, "new": new, "resolved": resolved})
    return out


@router.get("/problems/history")
async def problem_history(user: CurrentUser, session: Session, range: str = "24h", device_id: int | None = None):
    """How many problems were open over time (1h-1y), with counters for the Problems page and Home."""
    if range not in HISTORY_SPAN:
        raise HTTPException(400, f"range must be one of {', '.join(HISTORY_SPAN)}")
    now = datetime.now(UTC)
    step = HISTORY_BUCKETS[range]
    start = datetime.fromtimestamp((now.timestamp() - HISTORY_SPAN[range]) // step * step, UTC)
    scope = device_scope(select(Service.id).join(Device, Device.id == Service.device_id), user)
    if device_id:
        scope = scope.where(Service.device_id == device_id)
    ids = select(scope.subquery().c.id)

    # open at the start: services whose last change before the window left them in a problem state
    last = (select(StateChange.service_id, StateChange.new_state)
            .where(StateChange.service_id.in_(ids), StateChange.time < start)
            .distinct(StateChange.service_id).order_by(StateChange.service_id, StateChange.time.desc())).subquery()
    start_states = dict((await session.execute(select(last.c.service_id, last.c.new_state))).all())
    changes = [(t, sid, n) for t, sid, n in await session.execute(
        select(StateChange.time, StateChange.service_id, StateChange.new_state)
        .where(StateChange.service_id.in_(ids), StateChange.time >= start).order_by(StateChange.time))]
    series = problem_series(start_states, changes, start, now, step)

    active_q = select(func.count()).select_from(Service).where(Service.id.in_(ids), Service.state > State.OK)
    return {
        "range": range, "step": step, "series": series,
        "active": await session.scalar(active_q) or 0,
        "unhandled": await session.scalar(active_q.where(Service.acknowledged.is_(False))) or 0,
        "critical": await session.scalar(active_q.where(Service.state == State.CRIT)) or 0,
        "new": sum(b["new"] for b in series),
        "resolved": sum(b["resolved"] for b in series),
    }
