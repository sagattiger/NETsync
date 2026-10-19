"""Problems, acknowledgements, downtimes, threshold rules, notification rules."""

from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException
from sqlalchemy import func, select

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
from netsync.models import Device, Downtime, NotificationRule, Role, Service, State, ThresholdRule
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


@router.get("/problems", response_model=list[ProblemOut])
async def problems(user: CurrentUser, session: Session, include_acked: bool = True):
    q = (
        select(Service, Device.hostname)
        .join(Device, Device.id == Service.device_id)
        .where(Service.state > State.OK)
        .order_by(Service.state.desc(), Service.last_change.desc())
    )
    if not include_acked:
        q = q.where(Service.acknowledged.is_(False))
    q = device_scope(q, user)
    return [
        ProblemOut.model_validate(svc).model_copy(update={"hostname": hostname})
        for svc, hostname in await session.execute(q)
    ]


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
