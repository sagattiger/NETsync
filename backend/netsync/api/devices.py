from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import case, func, select, text

from netsync.api.collab import author_avatars, comment_out, comments_for
from netsync.api.deps import CurrentUser, Session, device_scope, get_device_for, require
from netsync.api.schemas import (
    ComponentOut,
    DeviceIn,
    DeviceOut,
    DeviceSummary,
    DeviceUpdate,
    ServiceOut,
)
from netsync.models import Component, Device, DeviceGroup, Role, Service, State, StateChange
from netsync.poller.worker import enqueue_job

router = APIRouter(prefix="/devices", tags=["devices"])

# range -> (span, time_bucket width). asyncpg needs timedelta objects for interval parameters.
RANGES = {
    "1h": (timedelta(hours=1), timedelta(minutes=1)),
    "6h": (timedelta(hours=6), timedelta(minutes=2)),
    "24h": (timedelta(hours=24), timedelta(minutes=5)),
    "7d": (timedelta(days=7), timedelta(minutes=30)),
    "30d": (timedelta(days=30), timedelta(hours=2)),
    "1y": (timedelta(days=365), timedelta(days=1)),
}


@router.get("", response_model=list[DeviceSummary])
async def list_devices(user: CurrentUser, session: Session, q: str | None = None, group_id: int | None = None):
    query = device_scope(select(Device).order_by(Device.hostname), user)
    if q:
        like = f"%{q}%"
        query = query.where(Device.hostname.ilike(like) | Device.ip.ilike(like) | Device.sys_name.ilike(like))
    if group_id:
        query = query.where(Device.groups.any(DeviceGroup.id == group_id))
    devices = list(await session.scalars(query))
    ids = [d.id for d in devices]

    counts: dict[int, dict] = {}
    if ids:
        rows = await session.execute(
            select(
                Service.device_id,
                *[func.sum(case((Service.state == s, 1), else_=0)).label(s.name) for s in State],
            ).where(Service.device_id.in_(ids)).group_by(Service.device_id)
        )
        for r in rows:
            counts[r.device_id] = {f"services_{s.name.lower()}": getattr(r, s.name) or 0 for s in State}
        ports = await session.execute(
            select(Component.device_id, func.count()).where(
                Component.device_id.in_(ids), Component.kind == "port", Component.deleted.is_(False)
            ).group_by(Component.device_id)
        )
        for did, n in ports:
            counts.setdefault(did, {})["ports"] = n
    return [DeviceSummary.model_validate(d).model_copy(update=counts.get(d.id, {})) for d in devices]


async def _set_groups(session, device: Device, group_ids: list[int]) -> None:
    device.groups = list(await session.scalars(select(DeviceGroup).where(DeviceGroup.id.in_(group_ids))))


@router.post("", response_model=DeviceOut, dependencies=[require(Role.OPERATOR)])
async def add_device(body: DeviceIn, session: Session):
    if await session.scalar(select(Device.id).where(Device.hostname == body.hostname)):
        raise HTTPException(409, "Device already exists")
    device = Device(**body.model_dump(exclude={"group_ids"}))
    await _set_groups(session, device, body.group_ids)
    session.add(device)
    await session.commit()
    await enqueue_job(device.id, "discover")
    return device


@router.get("/{device_id}", response_model=DeviceOut)
async def get_device(device_id: int, user: CurrentUser, session: Session):
    return await get_device_for(session, user, device_id)


@router.patch("/{device_id}", response_model=DeviceOut)
async def update_device(device_id: int, body: DeviceUpdate, session: Session, user=require(Role.OPERATOR)):
    device = await get_device_for(session, user, device_id)
    data = body.model_dump(exclude_unset=True)
    if (group_ids := data.pop("group_ids", None)) is not None:
        await _set_groups(session, device, group_ids)
    for k, v in data.items():
        setattr(device, k, v)
    await session.commit()
    return device


@router.delete("/{device_id}")
async def delete_device(device_id: int, session: Session, user=require(Role.ADMIN)):
    device = await get_device_for(session, user, device_id)
    await session.delete(device)
    await session.commit()
    return {"ok": True}


@router.post("/{device_id}/discover")
async def discover_now(device_id: int, session: Session, user=require(Role.OPERATOR)):
    await get_device_for(session, user, device_id)
    await enqueue_job(device_id, "discover")
    return {"queued": True}


@router.post("/{device_id}/poll")
async def poll_now(device_id: int, session: Session, user=require(Role.OPERATOR)):
    await get_device_for(session, user, device_id)
    await enqueue_job(device_id, "poll")
    return {"queued": True}


@router.get("/{device_id}/components", response_model=list[ComponentOut])
async def components(device_id: int, user: CurrentUser, session: Session, kind: str | None = None):
    await get_device_for(session, user, device_id)
    q = select(Component).where(Component.device_id == device_id, Component.deleted.is_(False))
    if kind:
        q = q.where(Component.kind == kind)
    rows = list(await session.scalars(q))
    # natural-ish sort by numeric index when possible
    return sorted(rows, key=lambda c: (c.kind, int(c.index) if c.index.isdigit() else 0, c.index))


@router.get("/{device_id}/services", response_model=list[ServiceOut])
async def services(device_id: int, user: CurrentUser, session: Session):
    await get_device_for(session, user, device_id)
    q = select(Service).where(Service.device_id == device_id).order_by(Service.state.desc(), Service.name)
    return list(await session.scalars(q))


@router.get("/{device_id}/metrics")
async def metrics(
    device_id: int,
    user: CurrentUser,
    session: Session,
    name: list[str] = Query(...),
    component_id: int = 0,
    range: str = "24h",
):
    """Time-bucketed series: {name: [[iso_time, avg, min, max], ...]}"""
    await get_device_for(session, user, device_id)
    span, bucket = RANGES.get(range, RANGES["24h"])
    since = datetime.now(UTC) - span
    rows = await session.execute(
        text(
            "SELECT name, time_bucket(CAST(:bucket AS interval), time) AS t, avg(value), min(value), max(value) "
            "FROM metrics WHERE device_id = :d AND component_id = :c AND name = ANY(:names) AND time >= :since "
            "GROUP BY name, t ORDER BY t"
        ),
        {"bucket": bucket, "d": device_id, "c": component_id, "names": name, "since": since},
    )
    out: dict[str, list] = {n: [] for n in name}
    for n, t, avg, mn, mx in rows:
        out[n].append([t.isoformat(), avg, mn, mx])
    return out


@router.get("/{device_id}/history")
async def history(device_id: int, user: CurrentUser, session: Session, limit: int = 100):
    await get_device_for(session, user, device_id)
    q = (
        select(StateChange, Service.name)
        .join(Service, Service.id == StateChange.service_id, isouter=True)
        .where(StateChange.device_id == device_id)
        .order_by(StateChange.time.desc())
        .limit(min(limit, 1000))
    )
    events = list(await session.execute(q))
    comments = await comments_for(session, [device_id])
    avatars = await author_avatars(session, comments)
    by_event: dict[tuple, list] = {}
    for c in comments:
        by_event.setdefault((c.service_id, c.event_time), []).append(comment_out(c, avatars))
    return [
        {
            "time": sc.time, "service_id": sc.service_id, "service": name, "old_state": sc.old_state,
            "new_state": sc.new_state, "output": sc.output,
            "comments": (cs := by_event.get((sc.service_id, sc.time), [])),
            "pinned": any(c["pinned"] for c in cs),
        }
        for sc, name in events
    ]
