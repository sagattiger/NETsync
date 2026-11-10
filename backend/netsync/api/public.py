"""Read-only public dashboards API for external status pages (e.g. the Paymenter extension).

Authentication: ``Authorization: Bearer nst_...`` API tokens only (see api/tokens.py).
Only dashboards flagged ``public`` are visible, and responses are built from an allow-list:
never hostnames, IPs, SNMP data, sysDescr, syslog, users, comments or service output text.
"""

from datetime import UTC, datetime
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Response
from sqlalchemy import select

from netsync.api.deps import Session
from netsync.api.tokens import PublicToken
from netsync.metrics_query import bucketed_series
from netsync.models import Component, Dashboard, Device, Service, State
from netsync.presets import BY_ID, Preset

router = APIRouter(prefix="/public", tags=["public"])

CACHE_HEADERS = {"Cache-Control": "public, max-age=30"}
RangeName = Literal["1h", "6h", "24h", "7d", "30d", "1y"]
STATE_NAMES = {s.value: s.name for s in State}
DEVICE_TYPE_TITLES = {
    "router": "Router", "switch": "Switch", "firewall": "Firewall", "server": "Server",
    "container": "Container", "network": "Network device",
}


def state_name(value: int | None) -> str:
    return STATE_NAMES.get(value if value is not None else State.UNKNOWN, "UNKNOWN")


def worst(states) -> int:
    """Worst of a set of states; CRIT > WARN > UNKNOWN > OK (UNKNOWN shouldn't hide a CRIT)."""
    order = {State.OK: 0, State.UNKNOWN: 1, State.WARN: 2, State.CRIT: 3}
    states = list(states)
    return max(states, key=lambda s: order.get(s, 1)) if states else State.UNKNOWN


SORT = {State.CRIT: 0, State.WARN: 1, State.UNKNOWN: 2, State.OK: 3}  # worst first


def dashboard_devices(widgets: list[dict]) -> set[int]:
    return {w["device_id"] for w in widgets if w.get("device_id")}


def graph_title(w: dict, preset: Preset | None, component: Component | None) -> str:
    if w.get("public_title"):
        return w["public_title"]
    label = preset.label if preset else "Graph"
    return f"{label} · {component.name}" if preset and preset.kind == "port" and component else label


def service_counts(services) -> dict[str, int]:
    counts = {name: 0 for name in ("OK", "WARN", "CRIT", "UNKNOWN")}
    for s in services:
        counts[state_name(s.state)] += 1
    return counts


def build_payload(d: Dashboard, range_: str, devices: dict[int, Device], services: list[Service],
                  components: dict[int, Component], series: dict[str, dict[str, list]]) -> dict[str, Any]:
    """Pure: everything public about a dashboard. ``series`` maps widget id -> {metric: points}."""
    used = dashboard_devices(d.widgets or [])
    dash_services = [s for s in services if s.device_id in used]
    by_device: dict[int, list[Service]] = {}
    for s in dash_services:
        by_device.setdefault(s.device_id, []).append(s)

    widgets = []
    for w in d.widgets or []:
        kind, dev_id = w.get("type"), w.get("device_id")
        base = {"id": w.get("id"), "type": kind, "size": w.get("size", "m")}
        device = devices.get(dev_id) if dev_id else None

        if kind == "graph":
            preset = BY_ID.get(w.get("preset") or "")
            comp = components.get(w.get("component_id")) if preset and preset.kind else None
            if comp is not None and comp.device_id != dev_id:
                comp = None  # never follow a component of another device
            relevant = [s for s in by_device.get(dev_id, []) if comp is None or s.component_id == comp.id]
            data = series.get(w.get("id"), {})
            out_series = [{"name": m.label, "points": data.get(m.name, [])} for m in (preset.metrics if preset else ())]
            widgets.append({
                **base, "title": graph_title(w, preset, comp), "state": state_name(worst(s.state for s in relevant)),
                "unit": preset.unit if preset else "count", "area": preset.area if preset else True,
                "series": out_series,
                "last": {s["name"]: (s["points"][-1][1] if s["points"] else None) for s in out_series},
            })
        elif kind == "device":
            own = by_device.get(dev_id, [])
            default_title = DEVICE_TYPE_TITLES.get(device.device_type or "", "Device") if device else "Device"
            widgets.append({
                **base,
                "title": w.get("public_title") or default_title,
                "state": state_name(worst(s.state for s in own)) if device else "UNKNOWN",
                "status": "up" if device and device.status == State.OK else "down",
                "uptime_seconds": device.uptime if device else None,
                "services": service_counts(own),
            })
        elif kind == "services":
            own = sorted(by_device.get(dev_id, []), key=lambda s: (SORT.get(s.state, 2), s.name))
            widgets.append({
                **base, "title": w.get("public_title") or "Services",
                "items": [{"name": s.name, "state": state_name(s.state), "since": s.last_change} for s in own],
            })
        elif kind == "problems":
            pool = by_device.get(dev_id, []) if dev_id else dash_services
            probs = sorted((s for s in pool if s.state != State.OK), key=lambda s: (SORT.get(s.state, 2), s.name))
            widgets.append({
                **base, "title": w.get("public_title") or "Problems",
                "items": [{"name": s.name, "state": state_name(s.state), "since": s.last_change,
                           "acknowledged": bool(s.acknowledged)} for s in probs],
            })

    dash_devices = [devices[i] for i in used if i in devices]
    up = sum(1 for dv in dash_devices if dv.status == State.OK)
    return {
        "id": d.id, "name": d.public_name or d.name, "description": d.description, "range": range_,
        "generated_at": datetime.now(UTC),
        "summary": {
            "state": state_name(worst(s.state for s in dash_services)) if dash_services else "UNKNOWN",
            "devices": {"up": up, "down": len(dash_devices) - up},
            "services": service_counts(dash_services),
        },
        "widgets": widgets,
    }


async def _public_dashboard(session, dashboard_id: int) -> Dashboard:
    d = await session.get(Dashboard, dashboard_id)
    if not d or not d.public:
        raise HTTPException(404, "Dashboard not found")  # 404, not 403: don't reveal private ids
    return d


@router.get("/dashboards")
async def list_public_dashboards(token: PublicToken, session: Session, response: Response):
    response.headers.update(CACHE_HEADERS)
    rows = await session.scalars(select(Dashboard).where(Dashboard.public.is_(True)).order_by(Dashboard.name))
    return [{"id": d.id, "name": d.public_name or d.name, "description": d.description, "updated_at": d.updated_at}
            for d in rows]


@router.get("/dashboards/{dashboard_id}")
async def get_public_dashboard(dashboard_id: int, token: PublicToken, session: Session, response: Response,
                               range: RangeName = "24h"):  # noqa: A002 - matches the public query parameter
    d = await _public_dashboard(session, dashboard_id)
    widgets = d.widgets or []
    used = dashboard_devices(widgets)
    devices = {dv.id: dv for dv in await session.scalars(select(Device).where(Device.id.in_(used)))} if used else {}
    services = list(await session.scalars(select(Service).where(Service.device_id.in_(used)))) if used else []
    comp_ids = {w["component_id"] for w in widgets if w.get("component_id")}
    components = {c.id: c for c in await session.scalars(select(Component).where(Component.id.in_(comp_ids)))} if comp_ids else {}

    series: dict[str, dict[str, list]] = {}
    for w in widgets:
        preset = BY_ID.get(w.get("preset") or "")
        if w.get("type") != "graph" or not preset or w.get("device_id") not in devices:
            continue
        comp_id = 0
        if preset.kind:
            comp = components.get(w.get("component_id"))
            if not comp or comp.device_id != w["device_id"]:
                continue  # misconfigured widget: no data rather than an error
            comp_id = comp.id
        series[w["id"]] = await bucketed_series(session, w["device_id"], comp_id, [m.name for m in preset.metrics], range)

    response.headers.update(CACHE_HEADERS)
    return build_payload(d, range, devices, services, components, series)

