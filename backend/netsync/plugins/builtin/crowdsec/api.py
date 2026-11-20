"""REST endpoints of the CrowdSec plugin, mounted at /api/plugins/crowdsec.

Admins add, change, test and remove sources. Bouncer keys are write-only: they are encrypted on save and no
endpoint ever returns them (only ``has_key``). Everyone signed in sees the totals; LAPI addresses are shown to
admins only, masked recent bans (203.0.113.x) to operators and admins.
"""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select

from netsync.api.deps import CurrentUser, Session, require
from netsync.models import CrowdSecSource, Device, Role, Service, State
from netsync.plugins import settings as plugin_settings
from netsync.plugins.builtin.crowdsec import service, summary
from netsync.probing.checkers.http import validate_url
from netsync.probing.secrets import MASK, decrypt, encrypt

router = APIRouter()
DEVICE_TYPE = "crowdsec"


def device_hostname(name: str) -> str:
    return f"{name} (CrowdSec)"


class SourceIn(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    url: str = Field(min_length=1, max_length=512)
    api_key: str | None = Field(None, max_length=512)  # None or the mask on update = keep the stored key
    enabled: bool = True

    @field_validator("name")
    @classmethod
    def _name(cls, v: str) -> str:
        v = " ".join(v.split())
        if not v:
            raise ValueError("name is required")
        return v

    @field_validator("url")
    @classmethod
    def _url(cls, v: str) -> str:
        return validate_url(v.strip()).rstrip("/")

    @field_validator("api_key")
    @classmethod
    def _key(cls, v: str | None) -> str | None:
        if v is None or v == MASK:
            return v
        v = v.strip()
        if any(c.isspace() or ord(c) < 32 for c in v):
            raise ValueError("the bouncer key can't contain spaces or line breaks")
        return v


def source_out(src: CrowdSecSource, user, services: list[Service]) -> dict:
    st = src.state or {}
    role = Role(user.role)
    return {
        "id": src.id, "name": src.name, "enabled": src.enabled, "device_id": src.device_id,
        **({"url": src.url, "has_key": bool(src.key_enc)} if role == Role.ADMIN else {}),
        "last_run": src.last_run, "last_ok": src.last_ok, "last_error": src.last_error, "last_ms": src.last_ms,
        "stats": st.get("stats"), "since": (st.get("tracking") or {}).get("since"),
        "recent": st.get("recent", []) if role in (Role.ADMIN, Role.OPERATOR) else [],
        "services": [{"id": s.id, "name": s.name, "state": State(s.state).name, "output": s.output,
                      "value": (s.perf or {}).get("value"), "since": s.last_change} for s in services],
    }


async def _cfg(session) -> dict:
    from netsync.plugins.builtin.crowdsec import plugin

    return (await plugin_settings.get_settings(session, plugin))[1]


async def _services(session, sources) -> dict[int, list[Service]]:
    ids = [s.device_id for s in sources]
    out: dict[int, list[Service]] = {i: [] for i in ids}
    if ids:
        for svc in await session.scalars(select(Service).where(Service.device_id.in_(ids)).order_by(Service.name)):
            out[svc.device_id].append(svc)
    return out


@router.get("/overview")
async def overview(user: CurrentUser, session: Session):
    """Every source with its latest totals, plus the combined totals and new bans per day."""
    sources = list(await session.scalars(select(CrowdSecSource).order_by(CrowdSecSource.name)))
    svcs = await _services(session, sources)
    cfg = await _cfg(session)
    enabled = [s for s in sources if s.enabled]
    return {
        "sources": [source_out(s, user, svcs.get(s.device_id, [])) for s in sources],
        "combined": await summary.combined(session, enabled, svcs, cfg),
        "interval_s": int(cfg.get("interval_s") or 300),
    }


async def _name_free(session, name: str, own_id: int | None = None) -> None:
    clash = await session.scalar(select(CrowdSecSource.id).where(CrowdSecSource.name == name))
    if clash and clash != own_id:
        raise HTTPException(409, "A CrowdSec source with this name already exists")
    dev = await session.scalar(select(Device.id).where(Device.hostname == device_hostname(name)))
    own_dev = await session.scalar(select(CrowdSecSource.device_id).where(CrowdSecSource.id == own_id)) if own_id else None
    if dev and dev != own_dev:
        raise HTTPException(409, "This name is already used by a device")


@router.post("/sources", status_code=201)
async def create_source(body: SourceIn, session: Session, user=require(Role.ADMIN)):
    if not body.api_key or body.api_key == MASK:
        raise HTTPException(422, "The bouncer key is required")
    await _name_free(session, body.name)
    device = Device(hostname=device_hostname(body.name), device_type=DEVICE_TYPE, sys_name=body.name,
                    vendor="CrowdSec", os="crowdsec", disabled=not body.enabled, status=State.UNKNOWN,
                    snmp_community=None)
    session.add(device)
    await session.flush()
    src = CrowdSecSource(device_id=device.id, name=body.name, url=body.url, enabled=body.enabled,
                         key_enc=encrypt({"api_key": body.api_key}), state={})
    session.add(src)
    await session.commit()
    return source_out(src, user, [])


@router.put("/sources/{source_id}")
async def update_source(source_id: int, body: SourceIn, session: Session, user=require(Role.ADMIN)):
    src = await session.get(CrowdSecSource, source_id)
    if not src:
        raise HTTPException(404, "CrowdSec source not found")
    await _name_free(session, body.name, src.id)
    device = await session.get(Device, src.device_id)
    if body.url != src.url:
        src.state = {}  # another LAPI: its decision ids mean something else, start counting again
    src.name, src.url, src.enabled = body.name, body.url, body.enabled
    if body.api_key and body.api_key != MASK:
        src.key_enc = encrypt({"api_key": body.api_key})
    if device:
        device.hostname, device.sys_name, device.disabled = device_hostname(body.name), body.name, not body.enabled
    await session.commit()
    return source_out(src, user, (await _services(session, [src])).get(src.device_id, []))


@router.delete("/sources/{source_id}", status_code=204)
async def delete_source(source_id: int, session: Session, user=require(Role.ADMIN)):
    src = await session.get(CrowdSecSource, source_id)
    if not src:
        raise HTTPException(404, "CrowdSec source not found")
    device = await session.get(Device, src.device_id)
    await session.delete(src)
    if device:
        await session.delete(device)  # its metrics, services and components go with it
    await session.commit()


class TestIn(BaseModel):
    url: str = Field(min_length=1, max_length=512)
    api_key: str | None = Field(None, max_length=512)
    source_id: int | None = None  # use the stored key when api_key is left out


@router.post("/test")
async def test_connection(body: TestIn, session: Session, user=require(Role.ADMIN)):
    """Read the LAPI once without saving anything. Answers totals only, never addresses or the key."""
    from netsync.plugins.builtin.crowdsec import logic

    try:
        url = validate_url(body.url.strip()).rstrip("/")
    except ValueError as e:
        raise HTTPException(422, str(e)) from None
    key = body.api_key if body.api_key and body.api_key != MASK else ""
    if not key and body.source_id:
        src = await session.get(CrowdSecSource, body.source_id)
        key = decrypt(src.key_enc).get("api_key", "") if src else ""
    if not key:
        raise HTTPException(422, "The bouncer key is required")
    cfg = await _cfg(session)
    res = await service.fetch(url, key, float(cfg.get("timeout_s") or 10))
    out = {"ok": res["ok"], "status": res["status"], "ms": res["ms"], "message": res["message"]}
    if res["ok"]:
        try:
            agg = logic.aggregate(res["json"])
            out.update({k: agg[k] for k in ("local", "community", "total", "other", "simulated")})
        except logic.BadAnswer:
            out.update({"ok": False, "message": "unexpected response (not a list of decisions)"})
    return out


@router.post("/sources/{source_id}/run")
async def run_now(source_id: int, session: Session, user=require(Role.ADMIN)):
    """Read this source now (also stores the result, like a scheduled read)."""
    src = await session.get(CrowdSecSource, source_id)
    if not src:
        raise HTTPException(404, "CrowdSec source not found")
    res = await service.poll_source(source_id, await _cfg(session))
    return {"ok": bool(res and res["ok"]), "message": (res or {}).get("message", ""), "ms": (res or {}).get("ms"),
            "at": datetime.now(UTC)}


@router.get("/widget")
async def widget(user: CurrentUser, session: Session, ids: str = "", limit: int = 5):
    """A dashboard widget's data, in exactly the public shape (so the NETsync UI draws what the website gets)."""
    try:
        wanted = [int(x) for x in ids.split(",") if x.strip()][:10]
    except ValueError:
        raise HTTPException(422, "ids must be source ids separated by commas") from None
    w = {"id": "w", "crowdsec_ids": wanted, "limit": limit}
    data = (await summary.for_widgets(session, [w]))["w"]
    return summary.public_widget({"id": "w", "type": "crowdsec"}, w, data)
