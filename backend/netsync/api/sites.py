"""Sites and data centers, and the world map: where each device is and how it is doing."""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import case, func, select

from netsync.api.deps import CurrentUser, Session, device_scope, require
from netsync.models import Device, Role, Service, Site, State

router = APIRouter(tags=["sites"])


class SiteIn(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    kind: str = Field("site", pattern="^(site|datacenter)$")
    lat: float | None = Field(None, ge=-90, le=90)
    lon: float | None = Field(None, ge=-180, le=180)
    address: str | None = Field(None, max_length=255)
    description: str | None = Field(None, max_length=2000)
    device_ids: list[int] | None = None  # devices to place at this site (others keep theirs)


def site_out(s: Site, count: int = 0) -> dict:
    return {"id": s.id, "name": s.name, "kind": s.kind, "lat": s.lat, "lon": s.lon, "address": s.address,
            "description": s.description, "devices": count}


async def _counts(session) -> dict[int, int]:
    rows = await session.execute(select(Device.site_id, func.count()).where(Device.site_id.is_not(None)).group_by(Device.site_id))
    return dict(rows.all())


@router.get("/sites")
async def list_sites(user: CurrentUser, session: Session):
    counts = await _counts(session)
    return [site_out(s, counts.get(s.id, 0)) for s in await session.scalars(select(Site).order_by(Site.name))]


async def _place(session, user, site: Site, device_ids: list[int] | None) -> None:
    if device_ids is None:
        return
    q = device_scope(select(Device), user)
    for d in await session.scalars(q.where(Device.id.in_(device_ids))):
        d.site_id = site.id
    # devices taken off the list leave the site
    for d in await session.scalars(q.where(Device.site_id == site.id, Device.id.not_in(device_ids or [0]))):
        d.site_id = None


@router.post("/sites")
async def add_site(body: SiteIn, session: Session, user=require(Role.OPERATOR)):
    if await session.scalar(select(Site.id).where(Site.name == body.name.strip())):
        raise HTTPException(409, "A site with this name exists")
    s = Site(**body.model_dump(exclude={"device_ids"}))
    s.name = s.name.strip()
    session.add(s)
    await session.flush()
    await _place(session, user, s, body.device_ids)
    await session.commit()
    return site_out(s, len(body.device_ids or []))


@router.put("/sites/{site_id}")
async def update_site(site_id: int, body: SiteIn, session: Session, user=require(Role.OPERATOR)):
    s = await session.get(Site, site_id)
    if s is None:
        raise HTTPException(404, "Site not found")
    for k, v in body.model_dump(exclude={"device_ids"}).items():
        setattr(s, k, v.strip() if isinstance(v, str) and k == "name" else v)
    await _place(session, user, s, body.device_ids)
    await session.commit()
    return site_out(s, (await _counts(session)).get(s.id, 0))


@router.delete("/sites/{site_id}")
async def delete_site(site_id: int, session: Session, user=require(Role.OPERATOR)):
    s = await session.get(Site, site_id)
    if s is not None:
        await session.delete(s)
        await session.commit()
    return {"ok": True}


@router.get("/map")
async def world_map(user: CurrentUser, session: Session):
    """Devices with a position (their site's, or their own) and their state, plus the sites."""
    sites = {s.id: s for s in await session.scalars(select(Site))}
    counts = select(
        Service.device_id,
        func.sum(case((Service.state == State.WARN, 1), else_=0)).label("warn"),
        func.sum(case((Service.state == State.CRIT, 1), else_=0)).label("crit"),
        func.sum(case((Service.state == State.UNKNOWN, 1), else_=0)).label("unknown"),
    ).where(Service.acknowledged.is_(False)).group_by(Service.device_id).subquery()
    q = device_scope(select(Device, counts.c.warn, counts.c.crit, counts.c.unknown)
                     .outerjoin(counts, counts.c.device_id == Device.id)
                     .where(Device.device_type.is_distinct_from("probe")), user)
    devices, unplaced = [], 0
    for d, warn, crit, unknown in await session.execute(q):
        site = sites.get(d.site_id) if d.site_id else None
        lat, lon = (site.lat, site.lon) if site and site.lat is not None else (d.lat, d.lon)
        if lat is None or lon is None:
            unplaced += 1
            continue
        devices.append({
            "id": d.id, "hostname": d.hostname, "status": d.status, "disabled": d.disabled, "os": d.os,
            "device_type": d.device_type, "site_id": site.id if site else None, "lat": lat, "lon": lon,
            "warn": int(warn or 0), "crit": int(crit or 0), "unknown": int(unknown or 0),
            "location": d.sys_location,
        })
    return {
        "devices": devices,
        "unplaced": unplaced,
        "sites": [site_out(s) for s in sites.values() if s.lat is not None and s.lon is not None],
    }
