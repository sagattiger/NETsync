import re
from datetime import UTC, datetime
from typing import Literal
from urllib.parse import urlparse

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, field_validator, model_validator
from sqlalchemy import or_, select

from netsync.api.deps import CurrentUser, Session
from netsync.models import Dashboard, Role, User

router = APIRouter(prefix="/dashboards", tags=["dashboards"])

MAX_WIDGETS = 60


HEX = re.compile(r"^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})$")
LABEL_KEY = re.compile(r"^[A-Za-z0-9_. -]{1,32}$")
DI_LOGO = re.compile(r"^di:[a-z0-9]+(?:-[a-z0-9]+)*(?:\.(?:svg|png|webp))?$")
# Optional appearance fields: left out of the stored widget when unset, so old widgets serialize as before.
OPTIONAL = ("probe_id", "colors", "labels", "logo", "cols", "height", "compact",
            # UI kit widgets (kpi, gauge, rings, donut, bars) and the graph style
            "style", "metric", "stat", "window", "caption", "min", "max", "warn", "crit", "items", "count",
            "limit", "probe_ids")
WIDGET_TYPES = ("graph", "device", "problems", "services", "uptime", "kpi", "gauge", "rings", "donut", "bars")
SIZE_COLS = {"s": 4, "m": 6, "l": 12}


def validate_logo(v: str) -> str:
    """'di:<slug>' (Dashboard Icons, optionally .png/.webp) or an https:// image URL. Nothing else."""
    v = v.strip()
    if DI_LOGO.match(v) and len(v) <= 80:
        return v
    if len(v) > 512 or any(c.isspace() or c in "\"'<>\\`" for c in v):
        raise ValueError("logo must be di:<slug> or an https:// URL")
    u = urlparse(v)
    if u.scheme != "https" or not u.netloc or u.username or u.password:
        raise ValueError("logo must be di:<slug> or an https:// URL")
    return v


class RingItem(BaseModel):
    """One ring of a ``rings`` widget: a device/component metric or a probe metric, shown as 0-100 %."""
    label: str | None = Field(None, max_length=24)
    device_id: int | None = None
    component_id: int | None = None
    probe_id: int | None = None
    preset: str = Field(max_length=64)
    metric: str | None = Field(None, max_length=32)  # series key of the preset (default: the first)
    color: str | None = None

    @field_validator("color")
    @classmethod
    def _color(cls, v: str | None) -> str | None:
        if v is None or not v.strip():
            return None
        if not HEX.match(v):
            raise ValueError(f"invalid colour {v!r}: use #RGB or #RRGGBB")
        return v.upper()

    @field_validator("label")
    @classmethod
    def _label(cls, v: str | None) -> str | None:
        return " ".join(v.split()) or None if v else None


class Widget(BaseModel):
    id: str = Field(max_length=64)
    type: Literal["graph", "device", "problems", "services", "uptime", "kpi", "gauge", "rings", "donut", "bars"]
    title: str = Field("", max_length=128)
    size: Literal["s", "m", "l"] = "m"
    device_id: int | None = None
    component_id: int | None = None
    preset: str | None = Field(None, max_length=64)
    public_title: str | None = Field(None, max_length=128)  # shown on public pages instead of the internal title
    # --- optional, all default to today's look
    probe_id: int | None = None  # graph widgets of a probe preset point here instead of device_id/component_id
    colors: list[str] | None = Field(None, max_length=6)  # one per series, in order
    labels: dict[str, str] | None = None  # series key -> short label, e.g. {"in": "Rx"}
    logo: str | None = None  # "di:google" or https://...
    cols: Literal[3, 4, 6, 8, 12] | None = None  # width on a 12-column grid; missing -> from size
    height: Literal["compact", "normal", "tall"] | None = None
    compact: bool | None = None  # logo + title + current value + small chart only
    # --- UI kit widgets; unset = defaults
    style: Literal["area", "line", "spike", "range"] | None = None  # graph: glow area (default), line, spike, min-max
    metric: str | None = Field(None, max_length=32)  # kpi/gauge/bars: series key of the preset (default: the first)
    stat: Literal["last", "uptime"] | None = None  # kpi: last value (default) or probe uptime % over ``window``
    window: Literal["24h", "7d", "30d"] | None = None
    caption: str | None = Field(None, max_length=64)  # kpi: small text under the number
    min: float | None = None  # gauge scale (default 0..100)
    max: float | None = None
    warn: float | None = None  # gauge turns amber / red past these (below them when warn > crit)
    crit: float | None = None
    items: list[RingItem] | None = Field(None, max_length=4)  # rings: 1-4 percentages
    count: Literal["services", "problems"] | None = None  # donut: services by state (default) or open problems
    limit: int | None = Field(None, ge=1, le=10)  # bars: top N (default 5)
    probe_ids: list[int] | None = Field(None, max_length=10)  # bars of probe metrics

    @model_validator(mode="after")
    def _ranges(self):
        lo = 0.0 if self.min is None else self.min
        hi = 100.0 if self.max is None else self.max
        if hi <= lo:
            raise ValueError("gauge max must be greater than min")
        if self.type == "rings" and not self.items:
            raise ValueError("a rings widget needs 1-4 items")
        return self

    @field_validator("colors")
    @classmethod
    def _colors(cls, v: list[str] | None) -> list[str] | None:
        if v is None:
            return None
        for c in v:
            if not isinstance(c, str) or not HEX.match(c):
                raise ValueError(f"invalid colour {c!r}: use #RGB or #RRGGBB")
        return [c.upper() for c in v] or None

    @field_validator("labels")
    @classmethod
    def _labels(cls, v: dict[str, str] | None) -> dict[str, str] | None:
        if v is None:
            return None
        if len(v) > 12:
            raise ValueError("at most 12 labels")
        out = {}
        for k, label in v.items():
            if not LABEL_KEY.match(k):
                raise ValueError(f"invalid series key {k!r}")
            label = " ".join(str(label).split())
            if len(label) > 16:
                raise ValueError(f"label for {k!r} is longer than 16 characters")
            if label:
                out[k] = label
        return out or None

    @field_validator("logo")
    @classmethod
    def _logo(cls, v: str | None) -> str | None:
        return validate_logo(v) if v and v.strip() else None


def dump_widget(w: Widget) -> dict:
    """Stored form: the original keys always, the optional ones only when set."""
    d = w.model_dump()
    if d.get("items"):
        d["items"] = [{k: v for k, v in it.items() if v is not None} for it in d["items"]]
    for k in OPTIONAL:
        v = d.get(k)
        if v is None or v is False or (isinstance(v, (list, dict)) and not v):  # keep 0 (e.g. gauge min)
            d.pop(k, None)
    return d


class DashboardIn(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    description: str | None = Field(None, max_length=2000)
    shared: bool = False
    # Omitted -> keep the current value (so editors that don't know these fields never unpublish).
    public: bool | None = None
    public_name: str | None = Field(None, max_length=128)
    widgets: list[Widget] = Field(default_factory=list, max_length=MAX_WIDGETS)


def out(d: Dashboard, user: User) -> dict:
    return {
        "id": d.id, "name": d.name, "description": d.description, "owner": d.owner, "owner_id": d.owner_id,
        "shared": d.shared, "public": bool(d.public), "public_name": d.public_name, "widgets": d.widgets,
        "created_at": d.created_at, "updated_at": d.updated_at,
        "can_edit": d.owner_id == user.id or user.role == Role.ADMIN,
    }


async def _get(session, user: User, dashboard_id: int, edit: bool = False) -> Dashboard:
    d = await session.get(Dashboard, dashboard_id)
    if not d or not (d.shared or d.owner_id == user.id or user.role == Role.ADMIN):
        raise HTTPException(404, "Dashboard not found")
    if edit and d.owner_id != user.id and user.role != Role.ADMIN:
        raise HTTPException(403, "Only the owner can change this dashboard")
    return d


def _apply_public(d: Dashboard, body: DashboardIn, user: User) -> None:
    """Only admins may publish/unpublish; public_name is kept when not sent."""
    fields = body.model_fields_set
    if "public" in fields and body.public is not None and bool(body.public) != bool(d.public):
        if user.role != Role.ADMIN:
            raise HTTPException(403, "Only admins can make a dashboard public")
        d.public = bool(body.public)
    if "public_name" in fields:
        name = (body.public_name or "").strip() or None
        if name != d.public_name and user.role != Role.ADMIN:
            raise HTTPException(403, "Only admins can change the public name")
        d.public_name = name


@router.get("")
async def list_dashboards(user: CurrentUser, session: Session):
    q = select(Dashboard).order_by(Dashboard.name)
    if user.role != Role.ADMIN:
        q = q.where(or_(Dashboard.owner_id == user.id, Dashboard.shared.is_(True)))
    return [out(d, user) for d in await session.scalars(q)]


@router.post("")
async def create_dashboard(body: DashboardIn, user: CurrentUser, session: Session):
    d = Dashboard(name=body.name.strip(), description=body.description, shared=body.shared, public=False,
                  widgets=[dump_widget(w) for w in body.widgets], owner_id=user.id, owner=user.username)
    _apply_public(d, body, user)
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
    d.widgets = [dump_widget(w) for w in body.widgets]
    _apply_public(d, body, user)
    d.updated_at = datetime.now(UTC)
    await session.commit()
    return out(d, user)


@router.delete("/{dashboard_id}")
async def delete_dashboard(dashboard_id: int, user: CurrentUser, session: Session):
    d = await _get(session, user, dashboard_id, edit=True)
    await session.delete(d)
    await session.commit()
    return {"ok": True}
