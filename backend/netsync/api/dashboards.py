from datetime import UTC, datetime
from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import or_, select

from netsync.api.deps import CurrentUser, Session
from netsync.models import Dashboard, Role, User

router = APIRouter(prefix="/dashboards", tags=["dashboards"])

MAX_WIDGETS = 60


class Widget(BaseModel):
    id: str = Field(max_length=64)
    type: Literal["graph", "device", "problems", "services"]
    title: str = Field("", max_length=128)
    size: Literal["s", "m", "l"] = "m"
    device_id: int | None = None
    component_id: int | None = None
    preset: str | None = Field(None, max_length=64)


class DashboardIn(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    description: str | None = Field(None, max_length=2000)
    shared: bool = False
    widgets: list[Widget] = Field(default_factory=list, max_length=MAX_WIDGETS)


def out(d: Dashboard, user: User) -> dict:
    return {
        "id": d.id, "name": d.name, "description": d.description, "owner": d.owner, "owner_id": d.owner_id,
        "shared": d.shared, "widgets": d.widgets, "created_at": d.created_at, "updated_at": d.updated_at,
        "can_edit": d.owner_id == user.id or user.role == Role.ADMIN,
    }


async def _get(session, user: User, dashboard_id: int, edit: bool = False) -> Dashboard:
    d = await session.get(Dashboard, dashboard_id)
    if not d or not (d.shared or d.owner_id == user.id or user.role == Role.ADMIN):
        raise HTTPException(404, "Dashboard not found")
    if edit and d.owner_id != user.id and user.role != Role.ADMIN:
        raise HTTPException(403, "Only the owner can change this dashboard")
    return d


@router.get("")
async def list_dashboards(user: CurrentUser, session: Session):
    q = select(Dashboard).order_by(Dashboard.name)
    if user.role != Role.ADMIN:
        q = q.where(or_(Dashboard.owner_id == user.id, Dashboard.shared.is_(True)))
    return [out(d, user) for d in await session.scalars(q)]


@router.post("")
async def create_dashboard(body: DashboardIn, user: CurrentUser, session: Session):
    d = Dashboard(name=body.name.strip(), description=body.description, shared=body.shared,
                  widgets=[w.model_dump() for w in body.widgets], owner_id=user.id, owner=user.username)
    session.add(d)
    await session.commit()
    return out(d, user)


@router.get("/{dashboard_id}")
async def get_dashboard(dashboard_id: int, user: CurrentUser, session: Session):
    return out(await _get(session, user, dashboard_id), user)


@router.put("/{dashboard_id}")
async def update_dashboard(dashboard_id: int, body: DashboardIn, user: CurrentUser, session: Session):
    d = await _get(session, user, dashboard_id, edit=True)
    d.name, d.description, d.shared = body.name.strip(), body.description, body.shared
    d.widgets = [w.model_dump() for w in body.widgets]
    d.updated_at = datetime.now(UTC)
    await session.commit()
    return out(d, user)


@router.delete("/{dashboard_id}")
async def delete_dashboard(dashboard_id: int, user: CurrentUser, session: Session):
    d = await _get(session, user, dashboard_id, edit=True)
    await session.delete(d)
    await session.commit()
    return {"ok": True}
