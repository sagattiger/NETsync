"""Probes API: ping any IP/FQDN. Viewers read, operators change; scoped by device groups
through each probe's virtual device (see netsync/probes.py)."""

from datetime import UTC, datetime, timedelta
from typing import Literal

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select, text

from netsync.api.deps import CurrentUser, Session, device_scope, require
from netsync.metrics_query import RANGES, bucketed_series
from netsync.models import Device, DeviceGroup, Probe, Role, Service, State, User
from netsync.probes import COUNT_RANGE, INTERVAL_RANGE, METRICS, PROBE_DEVICE_TYPE, device_hostname, validate_target

router = APIRouter(prefix="/probes", tags=["probes"])

SPARK_POINTS = 30


class ProbeIn(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    target: str = Field(min_length=1, max_length=253)
    kind: Literal["icmp"] = "icmp"
    interval_s: int = Field(60, ge=INTERVAL_RANGE[0], le=INTERVAL_RANGE[1])
    count: int = Field(5, ge=COUNT_RANGE[0], le=COUNT_RANGE[1])
    enabled: bool = True
    group_ids: list[int] = Field(default_factory=list)

    @field_validator("target")
    @classmethod
    def _target(cls, v: str) -> str:
        return validate_target(v)

    @field_validator("name")
    @classmethod
    def _name(cls, v: str) -> str:
        v = " ".join(v.split())
        if not v:
            raise ValueError("name is required")
        return v


def _scoped(user: User):
    return device_scope(select(Probe, Device).join(Device, Device.id == Probe.device_id), user, Probe.device_id)


async def _get(session, user: User, probe_id: int) -> tuple[Probe, Device]:
    row = (await session.execute(_scoped(user).where(Probe.id == probe_id))).first()
    if not row:
        raise HTTPException(404, "Probe not found")
    return row[0], row[1]


async def _groups(session, user: User, group_ids: list[int]) -> list[DeviceGroup]:
    if user.role != Role.ADMIN:
        own = {g.id for g in user.groups}
        if not set(group_ids) <= own:
            raise HTTPException(403, "You can only use your own device groups")
        group_ids = group_ids or list(own)  # otherwise the operator couldn't see their own probe
    return list(await session.scalars(select(DeviceGroup).where(DeviceGroup.id.in_(group_ids)))) if group_ids else []


def _out(p: Probe, d: Device, services: list[Service] | None = None, spark: list | None = None) -> dict:
    by_check = {s.check: s for s in services or []}
    rtt, loss = by_check.get("ping_rtt"), by_check.get("ping_loss")
    states = [s.state for s in services or []]
    return {
        "id": p.id, "name": p.name, "target": p.target, "kind": p.kind, "interval_s": p.interval_s,
        "count": p.count, "enabled": p.enabled, "created_at": p.created_at, "last_run": p.last_run,
        "last_error": p.last_error, "device_id": d.id, "group_ids": [g.id for g in d.groups],
        "state": max(states, key=lambda s: {0: 0, 3: 1, 1: 2, 2: 3}.get(s, 1)) if states else State.UNKNOWN,
        "rtt_ms": (rtt.perf or {}).get("value") if rtt and rtt.state != State.CRIT else None,
        "loss_pct": (loss.perf or {}).get("value") if loss else None,
        "services": [{"id": s.id, "name": s.name, "state": s.state, "output": s.output, "last_change": s.last_change,
                      "acknowledged": s.acknowledged} for s in services or []],
        "spark": spark or [],
    }


async def _name_free(session, name: str, probe_id: int | None = None) -> None:
    q = select(Probe.id).where(Probe.name == name)
    if probe_id:
        q = q.where(Probe.id != probe_id)
    if await session.scalar(q) or await session.scalar(
        select(Device.id).where(Device.hostname == device_hostname(name), Device.device_type != PROBE_DEVICE_TYPE)
    ):
        raise HTTPException(409, "A probe with this name already exists")


@router.get("")
async def list_probes(user: CurrentUser, session: Session):
    rows = (await session.execute(_scoped(user).order_by(Probe.name))).all()
    ids = [d.id for _, d in rows]
    services: dict[int, list[Service]] = {}
    spark: dict[int, list] = {}
    if ids:
        for s in await session.scalars(select(Service).where(Service.device_id.in_(ids))):
            services.setdefault(s.device_id, []).append(s)
        res = await session.execute(text(
            "SELECT device_id, time_bucket(CAST(:b AS interval), time) AS t, avg(value) FROM metrics "
            "WHERE device_id = ANY(:ids) AND component_id = 0 AND name = 'ping_avg' AND time >= :since "
            "GROUP BY device_id, t ORDER BY t"
        ), {"b": timedelta(minutes=2), "ids": ids, "since": datetime.now(UTC) - timedelta(hours=1)})
        for did, t, v in res:
            spark.setdefault(did, []).append([t.isoformat(), v])
    return [_out(p, d, services.get(d.id), spark.get(d.id, [])[-SPARK_POINTS:]) for p, d in rows]


@router.post("")
async def create_probe(body: ProbeIn, session: Session, user=require(Role.OPERATOR)):
    await _name_free(session, body.name)
    device = Device(hostname=device_hostname(body.name), device_type=PROBE_DEVICE_TYPE, sys_name=body.name,
                    disabled=not body.enabled, status=State.UNKNOWN, snmp_community=None)
    device.groups = await _groups(session, user, body.group_ids)
    session.add(device)
    await session.flush()
    probe = Probe(device_id=device.id, name=body.name, target=body.target, kind=body.kind,
                  interval_s=body.interval_s, count=body.count, enabled=body.enabled)
    session.add(probe)
    await session.commit()
    return _out(probe, device)


@router.get("/{probe_id}")
async def get_probe(probe_id: int, user: CurrentUser, session: Session):
    p, d = await _get(session, user, probe_id)
    services = list(await session.scalars(select(Service).where(Service.device_id == d.id).order_by(Service.name)))
    return _out(p, d, services)


@router.put("/{probe_id}")
async def update_probe(probe_id: int, body: ProbeIn, session: Session, user=require(Role.OPERATOR)):
    p, d = await _get(session, user, probe_id)
    if body.name != p.name:
        await _name_free(session, body.name, p.id)
    if body.target != p.target:
        p.last_run = None  # ping the new target right away
    p.name, p.target, p.kind, p.interval_s, p.count, p.enabled = (
        body.name, body.target, body.kind, body.interval_s, body.count, body.enabled)
    d.hostname, d.sys_name, d.disabled = device_hostname(body.name), body.name, not body.enabled
    if not body.enabled:
        d.status = State.UNKNOWN
    d.groups = await _groups(session, user, body.group_ids)
    await session.commit()
    return await get_probe(probe_id, user, session)


@router.delete("/{probe_id}")
async def delete_probe(probe_id: int, session: Session, user=require(Role.OPERATOR)):
    _, d = await _get(session, user, probe_id)
    await session.delete(d)  # cascades to the probe, its services and comments
    await session.commit()
    return {"ok": True}


@router.get("/{probe_id}/metrics")
async def probe_metrics(probe_id: int, user: CurrentUser, session: Session,
                        name: list[str] | None = Query(None), range: str = "24h"):  # noqa: A002
    """Same shape as /devices/{id}/metrics: {name: [[iso_time, avg, min, max], ...]}"""
    if range not in RANGES:
        raise HTTPException(422, f"range must be one of {', '.join(RANGES)}")
    _, d = await _get(session, user, probe_id)
    names = [n for n in (name or METRICS) if n in METRICS] or list(METRICS)
    return await bucketed_series(session, d.id, 0, names, range)
