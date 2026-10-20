"""Problems, acknowledgements, downtimes, threshold rules, notification rules."""

from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, HTTPException
from sqlalchemy import and_, func, or_, select

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
from netsync.api.collab import author_avatars, comment_out
from netsync.models import (
    AIJob, Device, Downtime, EventComment, NotificationRule, Role, Service, State, StateChange, ThresholdRule,
)
from netsync.plugins.base import AlertEvent
from netsync.plugins.registry import registry
from netsync.rules import engine

router = APIRouter(tags=["monitoring"])


# --------------------------------------------------------------------------- overview

@router.get("/overview")
async def overview(user: CurrentUser, session: Session):
    devices = await session.execute(
        device_scope(select(Device.status, func.count()).group_by(Device.status), user)
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


@router.get("/notifications", response_model=list[NotificationRuleOut], dependencies=[require(Role.ADMIN)])
async def list_notification_rules(session: Session):
    return list(await session.scalars(select(NotificationRule).order_by(NotificationRule.name)))


@router.post("/notifications", response_model=NotificationRuleOut, dependencies=[require(Role.ADMIN)])
async def add_notification_rule(body: NotificationRuleIn, session: Session):
    if body.channel not in registry.channels:
        raise HTTPException(400, f"Unknown channel {body.channel}")
    rule = NotificationRule(**body.model_dump())
    session.add(rule)
    await session.commit()
    return rule


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
        raise HTTPException(502, f"Sending failed: {e}") from e
    return {"ok": True}
