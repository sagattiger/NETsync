"""Probes API (active monitoring). Viewers read, operators/admins change; scoped by device groups through
each probe's virtual device (see netsync/probes.py). Secrets are write-only: GET never returns them."""

import re
from datetime import UTC, datetime, timedelta
from typing import Literal

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field, ValidationError, field_validator, model_validator
from sqlalchemy import select, text

from netsync.alerting import active_downtime_device_ids
from netsync.api.deps import CurrentUser, Session, device_scope, require
from netsync.metrics_query import RANGES, bucketed_series
from netsync.models import Device, DeviceGroup, Probe, ProbeBeat, Role, Service, State, User
from netsync.probes import COUNT_RANGE, INTERVAL_RANGE, METRICS, PROBE_DEVICE_TYPE, device_hostname
from netsync.config import get_settings
from netsync.probing.base import REGISTRY, ProbeSpec, get_checker
from netsync.probing.checkers.push import hash_push_token, new_push_token
from netsync.probing.kuma import map_backup, validation_error
from netsync.probing.runner import run_check
from netsync.probing.secrets import decrypt, describe, encrypt, merge
from netsync.probing.uptime import uptimes

router = APIRouter(prefix="/probes", tags=["probes"])

SPARK_POINTS = 30
TAG = re.compile(r"^[\w .:/-]{1,32}$")
METRIC_NAME = re.compile(r"^[a-z0-9_]{1,64}$")
STATE_ORDER = {State.OK: 0, State.UNKNOWN: 1, State.WARN: 2, State.CRIT: 3}


class ProbeIn(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    kind: str = Field("icmp", max_length=8)
    target: str = Field("", max_length=2048)
    port: int | None = None
    interval_s: int = Field(60, ge=INTERVAL_RANGE[0], le=INTERVAL_RANGE[1])
    timeout_s: int = Field(10, ge=1, le=120)
    retries: int = Field(1, ge=1, le=20)
    retry_interval_s: int | None = Field(None, ge=INTERVAL_RANGE[0], le=INTERVAL_RANGE[1])
    upside_down: bool = False
    resend_every: int = Field(0, ge=0, le=1000)
    count: int = Field(5, ge=COUNT_RANGE[0], le=COUNT_RANGE[1])
    enabled: bool = True
    tags: list[str] = Field(default_factory=list, max_length=20)
    description: str | None = Field(None, max_length=2000)
    group_ids: list[int] = Field(default_factory=list)
    config: dict = Field(default_factory=dict)
    secrets: dict | None = None  # None/omitted on PUT = keep the stored secrets

    @field_validator("name")
    @classmethod
    def _name(cls, v: str) -> str:
        v = " ".join(v.split())
        if not v:
            raise ValueError("name is required")
        return v

    @field_validator("tags")
    @classmethod
    def _tags(cls, v: list[str]) -> list[str]:
        out = []
        for t in v:
            t = " ".join(str(t).split())
            if not TAG.match(t):
                raise ValueError(f"invalid tag {t!r}")
            if t not in out:
                out.append(t)
        return out

    @model_validator(mode="after")
    def _kind(self):
        checker = get_checker(self.kind)  # ValueError for unknown kinds
        self.target, self.port, self.config = checker.validate(self.target, self.port, self.config)
        if self.secrets is not None:
            self.secrets = checker.validate_secrets(self.secrets)
        if self.timeout_s >= self.interval_s:
            self.timeout_s = max(1, self.interval_s - 1)
        return self


class BulkIn(BaseModel):
    ids: list[int] = Field(min_length=1, max_length=1000)
    action: Literal["pause", "resume", "delete"]


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


def _worst(states) -> int:
    states = list(states)
    return max(states, key=lambda s: STATE_ORDER.get(s, 1)) if states else State.UNKNOWN


def probe_out(p: Probe, d: Device, services: list[Service] | None = None, spark: list | None = None,
              up: dict | None = None, maintenance: bool = False) -> dict:
    services = services or []
    by_check = {s.check: s for s in services}
    rtt, loss = by_check.get("ping_rtt"), by_check.get("ping_loss")
    checker = REGISTRY.get(p.kind)
    secrets = decrypt(p.secrets_enc) if p.secrets_enc else {}
    cert = p.cert or None
    return {
        "id": p.id, "name": p.name, "kind": p.kind, "kind_label": checker.label if checker else p.kind,
        "target": p.target, "port": p.port, "interval_s": p.interval_s, "timeout_s": p.timeout_s,
        "retries": p.retries, "retry_interval_s": p.retry_interval_s, "upside_down": p.upside_down,
        "resend_every": p.resend_every, "count": p.count, "enabled": p.enabled, "tags": p.tags or [],
        "description": p.description, "config": p.config or {}, "secrets": describe(secrets),
        "created_at": p.created_at, "last_run": p.last_run, "next_run": p.next_run, "last_error": p.last_error,
        "last_state": p.last_state, "last_message": p.last_message, "last_response_ms": p.last_response_ms,
        "fail_count": p.fail_count, "device_id": d.id, "group_ids": [g.id for g in d.groups],
        "state": _worst(s.state for s in services) if services else (p.last_state if p.last_state is not None else State.UNKNOWN),
        "rtt_ms": (rtt.perf or {}).get("value") if rtt and rtt.state != State.CRIT else p.last_response_ms,
        "loss_pct": (loss.perf or {}).get("value") if loss else None,
        "cert": cert, "cert_days_left": cert.get("days_left") if cert else None,
        "uptime": (up or {}).get("uptime", {}), "avg_ms": (up or {}).get("avg_ms", {}),
        "maintenance": maintenance, "has_push_token": bool(p.push_token_hash),
        "services": [{"id": s.id, "name": s.name, "state": s.state, "output": s.output, "last_change": s.last_change,
                      "acknowledged": s.acknowledged} for s in services],
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


def _new_push_token(p: Probe) -> dict:
    """Store only the hash; the token itself is returned once."""
    token = new_push_token()
    p.push_token_hash = hash_push_token(token)
    return {"push_token": token, "push_url": f"{get_settings().public_url.rstrip('/')}/api/push/{token}"}


def _apply(p: Probe, body: ProbeIn) -> None:
    p.name, p.kind, p.target, p.port = body.name, body.kind, body.target, body.port
    p.interval_s, p.timeout_s, p.retries, p.retry_interval_s = body.interval_s, body.timeout_s, body.retries, body.retry_interval_s
    p.upside_down, p.resend_every, p.count, p.enabled = body.upside_down, body.resend_every, body.count, body.enabled
    p.tags, p.description, p.config = body.tags, body.description, body.config
    allowed = set(get_checker(body.kind).secret_fields)
    stored = {k: v for k, v in decrypt(p.secrets_enc).items() if k in allowed}
    p.secrets_enc = encrypt(merge(stored, body.secrets))


@router.get("")
async def list_probes(user: CurrentUser, session: Session, kind: str | None = None, tag: str | None = None,
                      state: str | None = Query(None, pattern="^(OK|WARN|CRIT|UNKNOWN|PAUSED)$")):
    q = _scoped(user).order_by(Probe.name)
    if kind:
        q = q.where(Probe.kind == kind)
    rows = (await session.execute(q)).all()
    if tag:
        rows = [r for r in rows if tag in (r[0].tags or [])]
    ids = [d.id for _, d in rows]
    services: dict[int, list[Service]] = {}
    spark: dict[int, list] = {}
    if ids:
        for s in await session.scalars(select(Service).where(Service.device_id.in_(ids))):
            services.setdefault(s.device_id, []).append(s)
        res = await session.execute(text(
            "SELECT device_id, time_bucket(CAST(:b AS interval), time) AS t, avg(value) FROM metrics "
            "WHERE device_id = ANY(:ids) AND component_id = 0 AND name = 'response_ms' AND time >= :since "
            "GROUP BY device_id, t ORDER BY t"
        ), {"b": timedelta(minutes=2), "ids": ids, "since": datetime.now(UTC) - timedelta(hours=1)})
        for did, t, v in res:
            spark.setdefault(did, []).append([t.isoformat(), v])
    ups = await uptimes(session, [p.id for p, _ in rows])
    maint = await active_downtime_device_ids(session, datetime.now(UTC))
    out = [probe_out(p, d, services.get(d.id), spark.get(d.id, [])[-SPARK_POINTS:], ups.get(p.id), d.id in maint)
           for p, d in rows]
    if state == "PAUSED":
        out = [o for o in out if not o["enabled"]]
    elif state:
        out = [o for o in out if o["enabled"] and State(o["state"]).name == state]
    return out


@router.get("/kinds")
async def kinds(user: CurrentUser):
    return [{"kind": k, "label": c.label, "target_label": c.target_label, "needs_port": c.needs_port,
             "default_port": c.default_port, "secret_fields": list(c.secret_fields)} for k, c in REGISTRY.items()]


async def _create(session, user: User, body: ProbeIn) -> tuple[Probe, Device, dict]:
    await _name_free(session, body.name)
    device = Device(hostname=device_hostname(body.name), device_type=PROBE_DEVICE_TYPE, sys_name=body.name,
                    disabled=not body.enabled, status=State.UNKNOWN, snmp_community=None)
    device.groups = await _groups(session, user, body.group_ids)
    session.add(device)
    await session.flush()
    probe = Probe(device_id=device.id, fail_count=0)
    _apply(probe, body)
    extra = _new_push_token(probe) if body.kind == "push" else {}
    session.add(probe)
    await session.flush()
    return probe, device, extra


@router.post("")
async def create_probe(body: ProbeIn, session: Session, user=require(Role.OPERATOR)):
    probe, device, extra = await _create(session, user, body)
    await session.commit()
    return {**probe_out(probe, device), **extra}


# --------------------------------------------------------------------------- Uptime Kuma import

class KumaImportIn(BaseModel):
    backup: dict
    names: list[str] | None = None  # None = everything that can be imported


async def _kuma_plan(session, backup: dict) -> tuple[list[dict], list[dict], list[dict]]:
    try:
        mapped = map_backup(backup)
    except ValueError as e:
        raise HTTPException(422, str(e)) from None
    existing = set(await session.scalars(select(Probe.name)))
    create, skipped, seen = [], list(mapped["skipped"]), set()
    for item in mapped["create"]:
        payload = item["payload"]
        try:
            body = ProbeIn(**payload)
        except ValidationError as e:
            skipped.append({"name": payload["name"], "type": item["kuma_type"], "reason": validation_error(e)})
            continue
        if body.name in existing or body.name in seen:
            skipped.append({"name": body.name, "type": item["kuma_type"], "reason": "a probe with this name already exists"})
            continue
        seen.add(body.name)
        create.append({"name": body.name, "kind": body.kind, "kuma_type": item["kuma_type"], "target": body.target,
                       "port": body.port, "interval_s": body.interval_s, "retries": body.retries,
                       "enabled": body.enabled, "tags": body.tags, "warnings": item["warnings"],
                       "has_secrets": bool(payload.get("secrets")), "_body": body})
    return create, skipped, mapped["notifications"]


def _public_plan(items: list[dict]) -> list[dict]:
    return [{k: v for k, v in i.items() if k != "_body"} for i in items]


@router.post("/import/kuma/preview")
async def kuma_preview(backup: dict, session: Session, user=require(Role.OPERATOR)):
    """What an Uptime Kuma backup would create and what is skipped (and why). Nothing is saved."""
    create, skipped, notifications = await _kuma_plan(session, backup)
    return {"create": _public_plan(create), "skipped": skipped, "notifications": notifications}


@router.post("/import/kuma")
async def kuma_import(body: KumaImportIn, session: Session, user=require(Role.OPERATOR)):
    create, skipped, notifications = await _kuma_plan(session, body.backup)
    wanted = set(body.names) if body.names is not None else None
    created = []
    for item in create:
        if wanted is not None and item["name"] not in wanted:
            continue
        probe, device, extra = await _create(session, user, item["_body"])
        created.append({"id": probe.id, "name": probe.name, "kind": probe.kind, **extra})
    await session.commit()
    return {"created": created, "skipped": skipped, "notifications": notifications}


@router.post("/test")
async def test_probe(body: ProbeIn, session: Session, user=require(Role.OPERATOR), probe_id: int | None = None):
    """Run a probe configuration once without saving it. With probe_id, stored secrets fill omitted ones."""
    secrets = body.secrets or {}
    if probe_id:
        p, _ = await _get(session, user, probe_id)
        allowed = set(get_checker(body.kind).secret_fields)
        secrets = merge({k: v for k, v in decrypt(p.secrets_enc).items() if k in allowed}, body.secrets)
        last_push = p.last_push_at
    else:
        last_push = None
    spec = ProbeSpec(kind=body.kind, target=body.target, port=body.port, timeout_s=body.timeout_s, count=body.count,
                     interval_s=body.interval_s, config=body.config, secrets=secrets, last_push_at=last_push,
                     probe_id=probe_id)
    result = await run_check(spec)
    if result is None:
        return {"up": True, "state": "OK", "message": "heartbeat received in time", "response_ms": None,
                "metrics": {}, "checks": [], "cert": None, "effective_up": not body.upside_down}
    out = result.as_dict()
    out["effective_up"] = result.up != body.upside_down
    return out


@router.post("/bulk")
async def bulk(body: BulkIn, session: Session, user=require(Role.OPERATOR)):
    rows = (await session.execute(_scoped(user).where(Probe.id.in_(body.ids)))).all()
    for p, d in rows:
        if body.action == "delete":
            await session.delete(d)
        else:
            _set_enabled(p, d, body.action == "resume")
    await session.commit()
    return {"ok": True, "count": len(rows)}


def _set_enabled(p: Probe, d: Device, enabled: bool) -> None:
    p.enabled, d.disabled = enabled, not enabled
    if enabled:
        p.next_run, p.fail_count = None, 0
    else:
        d.status = State.UNKNOWN


@router.get("/{probe_id}")
async def get_probe(probe_id: int, user: CurrentUser, session: Session):
    p, d = await _get(session, user, probe_id)
    services = list(await session.scalars(select(Service).where(Service.device_id == d.id).order_by(Service.name)))
    ups = await uptimes(session, [p.id])
    maint = d.id in await active_downtime_device_ids(session, datetime.now(UTC))
    return probe_out(p, d, services, up=ups.get(p.id), maintenance=maint)


@router.put("/{probe_id}")
async def update_probe(probe_id: int, body: ProbeIn, session: Session, user=require(Role.OPERATOR)):
    p, d = await _get(session, user, probe_id)
    if body.name != p.name:
        await _name_free(session, body.name, p.id)
    if (body.kind, body.target, body.port) != (p.kind, p.target, p.port) or body.config != (p.config or {}):
        p.next_run, p.fail_count = None, 0  # check the new settings right away
    _apply(p, body)
    extra = _new_push_token(p) if body.kind == "push" and not p.push_token_hash else {}
    if body.kind != "push":
        p.push_token_hash = None
    d.hostname, d.sys_name, d.disabled = device_hostname(body.name), body.name, not body.enabled
    if not body.enabled:
        d.status = State.UNKNOWN
    d.groups = await _groups(session, user, body.group_ids)
    await session.commit()
    return {**await get_probe(probe_id, user, session), **extra}


@router.post("/{probe_id}/push-token")
async def regenerate_push_token(probe_id: int, session: Session, user=require(Role.OPERATOR)):
    """New push URL; the old one stops working immediately. Shown once."""
    p, _ = await _get(session, user, probe_id)
    if p.kind != "push":
        raise HTTPException(400, "Only push probes have a push URL")
    extra = _new_push_token(p)
    await session.commit()
    return extra


@router.post("/{probe_id}/pause")
async def pause_probe(probe_id: int, session: Session, user=require(Role.OPERATOR)):
    p, d = await _get(session, user, probe_id)
    _set_enabled(p, d, False)
    await session.commit()
    return {"ok": True, "enabled": False}


@router.post("/{probe_id}/resume")
async def resume_probe(probe_id: int, session: Session, user=require(Role.OPERATOR)):
    p, d = await _get(session, user, probe_id)
    _set_enabled(p, d, True)
    await session.commit()
    return {"ok": True, "enabled": True}


@router.delete("/{probe_id}")
async def delete_probe(probe_id: int, session: Session, user=require(Role.OPERATOR)):
    _, d = await _get(session, user, probe_id)
    await session.delete(d)  # cascades to the probe, its services and comments
    await session.commit()
    return {"ok": True}


@router.get("/{probe_id}/heartbeats")
async def heartbeats(probe_id: int, user: CurrentUser, session: Session, limit: int = Query(100, ge=1, le=1000)):
    """Newest last: [{time, state, response_ms, message, maintenance}]"""
    p, _ = await _get(session, user, probe_id)
    rows = list(await session.scalars(
        select(ProbeBeat).where(ProbeBeat.probe_id == p.id).order_by(ProbeBeat.time.desc()).limit(limit)))
    return [{"time": b.time, "state": b.state, "response_ms": b.response_ms, "message": b.message,
             "maintenance": b.maintenance} for b in reversed(rows)]


@router.get("/{probe_id}/uptime")
async def uptime(probe_id: int, user: CurrentUser, session: Session):
    p, _ = await _get(session, user, probe_id)
    return (await uptimes(session, [p.id]))[p.id]


@router.get("/{probe_id}/metrics")
async def probe_metrics(probe_id: int, user: CurrentUser, session: Session,
                        name: list[str] | None = Query(None), range: str = "24h"):
    """Same shape as /devices/{id}/metrics: {name: [[iso_time, avg, min, max], ...]}"""
    if range not in RANGES:
        raise HTTPException(422, f"range must be one of {', '.join(RANGES)}")
    p, d = await _get(session, user, probe_id)
    names = [n for n in (name or []) if METRIC_NAME.match(n)][:12]
    if not names:
        names = list(METRICS) if p.kind == "icmp" else ["response_ms", "up_pct"]
    return await bucketed_series(session, d.id, 0, names, range)
