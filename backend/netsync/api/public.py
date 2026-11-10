"""Read-only public dashboards API for external status pages (e.g. the Paymenter extension).

Authentication: ``Authorization: Bearer nst_...`` API tokens only (see api/tokens.py).
Only dashboards flagged ``public`` are visible, and responses are built from an allow-list:
never hostnames, IPs, probe targets, SNMP data, sysDescr, syslog, users, comments or service
output text. The only free text is what admins typed: public names/titles, series labels, logos.
"""

import re
from datetime import UTC, datetime
from typing import Any, Literal
from urllib.parse import urlsplit

from fastapi import APIRouter, HTTPException, Response
from sqlalchemy import select

from netsync.api.deps import Session
from netsync.api.icons import logo_alt, logo_src
from netsync.api.tokens import PublicToken
from netsync.metrics_query import bucketed_series
from netsync.models import Component, Dashboard, Device, Probe, ProbeBeat, Service, State
from netsync.presets import BY_ID, Preset
from netsync.probing.uptime import uptimes

router = APIRouter(prefix="/public", tags=["public"])

CACHE_HEADERS = {"Cache-Control": "public, max-age=30"}
RangeName = Literal["1h", "6h", "24h", "7d", "30d", "1y"]
STATE_NAMES = {s.value: s.name for s in State}
DEVICE_TYPE_TITLES = {
    "router": "Router", "switch": "Switch", "firewall": "Firewall", "server": "Server",
    "container": "Container", "network": "Network device",
}
# Probe latency widgets draw avg plus a min/max band built from the real per-round min and max.
PROBE_BAND = ("ping_avg", "ping_min", "ping_max")


def state_name(value: int | None) -> str:
    return STATE_NAMES.get(value if value is not None else State.UNKNOWN, "UNKNOWN")


def worst(states) -> int:
    """Worst of a set of states; CRIT > WARN > UNKNOWN > OK (UNKNOWN shouldn't hide a CRIT)."""
    order = {State.OK: 0, State.UNKNOWN: 1, State.WARN: 2, State.CRIT: 3}
    states = list(states)
    return max(states, key=lambda s: order.get(s, 1)) if states else State.UNKNOWN


SORT = {State.CRIT: 0, State.WARN: 1, State.UNKNOWN: 2, State.OK: 3}  # worst first


def dashboard_devices(widgets: list[dict]) -> set[int]:
    """Real devices used by the dashboard (probe widgets don't count)."""
    return {w["device_id"] for w in widgets if w.get("device_id") and not w.get("probe_id")}


def probe_ids(widgets: list[dict]) -> set[int]:
    return {w["probe_id"] for w in widgets if w.get("type") in ("graph", "uptime") and w.get("probe_id")}


UPTIME_WINDOWS = ("24h", "7d", "30d")
BEATS_MAX = 100
# Generic message categories that may be shown publicly; anything else becomes up / down / pending.
_PUBLIC_MESSAGES = re.compile(
    r"^(?:HTTP \d{3}(?:, (?:keyword (?:found|absent)|\d+ assertions? passed))?"
    r"|timeout|connection (?:refused|reset|failed)|name resolution failed|(?:host|network|port) unreachable"
    r"|TLS (?:certificate invalid|handshake failed)|keyword (?:not )?found|too many redirects"
    r"|invalid (?:JSON|HTTP) response|NXDOMAIN|SERVFAIL|no [A-Z]+ records|answer mismatch|\d+ [A-Z]+ records?"
    r"|no reply|unexpected (?:reply|response)|reply (?:matched|received)|connected|response matched"
    r"|sent, no error \(no reply expected\)|certificate (?:expires in -?\d+ days|expired|untrusted|hostname mismatch)"
    r"|no certificate presented|no push received|push received|push reported down|no reply|check failed"
    r"|\d+(?:\.\d+)? ms(?:, \d+% loss)?)$"
)
_SUFFIX = re.compile(r" \((?:retry \d+/\d+|expected down|should be down)\)$")


def public_message(msg: str | None, state: int | None, secrets_: tuple[str, ...] = ()) -> str:
    """Only generic categories ("timeout", "HTTP 503", "certificate expires in 5 days") leave NETsync."""
    text = (msg or "").strip()
    while _SUFFIX.search(text):
        text = _SUFFIX.sub("", text)
    if text.startswith("assertion failed"):
        text = "assertion failed"
    elif not _PUBLIC_MESSAGES.match(text) or any(x and x.lower() in text.lower() for x in secrets_):
        text = ""
    if not text:
        text = {State.CRIT: "down", State.UNKNOWN: "pending"}.get(state, "up")
    return text


def probe_secrets(p) -> tuple[str, ...]:
    """Strings that must never appear publicly for this probe: target, URL host, port-less host."""
    target = (p.target or "").strip()
    out = {target}
    try:
        host = urlsplit(target).hostname
        if host:
            out.add(host)
    except ValueError:
        pass
    return tuple(x for x in out if x)


def is_probe_widget(w: dict) -> bool:
    preset = BY_ID.get(w.get("preset") or "")
    return w.get("type") == "graph" and (bool(w.get("probe_id")) or bool(preset and preset.source == "probe"))


def probe_public_name(p) -> str | None:
    """The probe's name, unless it would reveal the target (e.g. a probe named '8.8.8.8' or 'example.com')."""
    name = (p.name or "").strip()
    return None if not name or any(x.lower() in name.lower() for x in probe_secrets(p)) else name


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


def appearance(w: dict) -> dict[str, Any]:
    """Optional layout/appearance fields, only when the admin set them (old widgets stay unchanged)."""
    out: dict[str, Any] = {}
    if w.get("cols") in (3, 4, 6, 8, 12):
        out["cols"] = w["cols"]
    if w.get("height") in ("compact", "normal", "tall"):
        out["height"] = w["height"]
    if w.get("compact"):
        out["compact"] = True
    if w.get("logo") and (src := logo_src(w["logo"])):
        out["logo"] = {"src": src, "alt": logo_alt(w["logo"]) or w.get("public_title") or ""}
    return out


def merge_band(data: dict[str, list]) -> list:
    """[t, avg(ping_avg), min(ping_min), max(ping_max)] per bucket: a true min/max band."""
    mins = {p[0]: p[2] for p in data.get("ping_min", [])}
    maxs = {p[0]: p[3] for p in data.get("ping_max", [])}
    return [[t, avg, mins.get(t, mn), maxs.get(t, mx)] for t, avg, mn, mx in data.get("ping_avg", [])]


def graph_series(w: dict, preset: Preset | None, data: dict[str, list], default_name=None,
                 band: bool = False) -> list[dict]:
    labels = w.get("labels") or {}
    series = []
    for m in preset.metrics if preset else ():
        points = merge_band(data) if band and m.name == "ping_avg" else data.get(m.name, [])
        name = labels.get(m.label) or (default_name if default_name and len(preset.metrics) == 1 else None) or m.label
        series.append({"key": m.label, "name": name, "points": points})
    return series


def probe_extras(probe, ups: dict) -> dict[str, Any]:
    out: dict[str, Any] = {"kind": probe.kind}
    up = (ups.get(probe.id) or {}).get("uptime") or {}
    if any(up.get(k) is not None for k in UPTIME_WINDOWS):
        out["uptime"] = {k: up.get(k) for k in UPTIME_WINDOWS}
    cert = getattr(probe, "cert", None)
    if cert and cert.get("days_left") is not None:
        out["cert_days_left"] = int(cert["days_left"] // 1)
    return out


def build_payload(d: Dashboard, range_: str, devices: dict[int, Device], services: list[Service],
                  components: dict[int, Component], series: dict[str, dict[str, list]],
                  probes: dict[int, Probe] | None = None, only: str | None = None,
                  ups: dict[int, dict] | None = None, beats: dict[int, list] | None = None) -> dict[str, Any]:
    """Pure: everything public about a dashboard. ``series`` maps widget id -> {metric: points}.
    ``probes`` maps probe id -> Probe (their services are in ``services``), ``ups`` probe id -> uptimes(),
    ``beats`` probe id -> [(time, state, response_ms)] oldest first.
    ``only``: build just that widget (the summary is still computed over the whole dashboard)."""
    probes, ups, beats = probes or {}, ups or {}, beats or {}
    all_widgets = d.widgets or []
    used = dashboard_devices(all_widgets)
    probe_devs = {p.device_id for pid, p in probes.items() if pid in probe_ids(all_widgets)}
    by_device: dict[int, list[Service]] = {}
    for s in services:
        by_device.setdefault(s.device_id, []).append(s)
    dash_services = [s for s in services if s.device_id in used or s.device_id in probe_devs]

    widgets = []
    for w in all_widgets:
        if only is not None and w.get("id") != only:
            continue
        kind, dev_id = w.get("type"), w.get("device_id")
        base = {"id": w.get("id"), "type": kind, "size": w.get("size", "m"), **appearance(w)}
        device = devices.get(dev_id) if dev_id else None

        if kind == "graph" and is_probe_widget(w):
            preset = BY_ID.get(w.get("preset") or "")
            preset = preset if preset and preset.source == "probe" else BY_ID["probe_latency"]
            probe = probes.get(w.get("probe_id"))
            own = by_device.get(probe.device_id, []) if probe else []
            pname = probe_public_name(probe) if probe else None
            out_series = graph_series(w, preset, series.get(w.get("id"), {}), default_name=pname, band=True)
            loss = next((s for s in own if s.name == "Ping loss"), None)
            ping = preset.id in ("probe_latency", "probe_loss")
            default_title = (f"Ping · {pname}" if ping else f"{preset.label} · {pname}") if pname else preset.label
            widgets.append({
                **base, "source": "probe", "title": w.get("public_title") or default_title,
                "state": state_name(worst(s.state for s in own)) if own else "UNKNOWN",
                "unit": preset.unit, "area": preset.area, "series": out_series,
                "last": {s["name"]: (s["points"][-1][1] if s["points"] else None) for s in out_series},
                "loss_pct": (getattr(loss, "perf", None) or {}).get("value") if loss else None,
                **({"colors": w["colors"]} if w.get("colors") else {}),
                **(probe_extras(probe, ups) if probe else {}),
                **({"message": public_message(probe.last_message, probe.last_state, probe_secrets(probe))}
                   if probe and getattr(probe, "last_run", None) else {}),
            })
        elif kind == "uptime":
            probe = probes.get(w.get("probe_id"))
            own = by_device.get(probe.device_id, []) if probe else []
            pname = probe_public_name(probe) if probe else None
            up = (ups.get(probe.id) or {}).get("uptime") or {} if probe else {}
            widgets.append({
                **base, "title": w.get("public_title") or pname or "Uptime",
                "state": state_name(worst(s.state for s in own)) if own else "UNKNOWN",
                "kind": probe.kind if probe else None,
                "uptime": {k: up.get(k) for k in UPTIME_WINDOWS},
                "beats": [[t, state_name(st), ms] for t, st, ms in (beats.get(probe.id, []) if probe else [])][-BEATS_MAX:],
                **({"colors": w["colors"]} if w.get("colors") else {}),
                **({"message": public_message(probe.last_message, probe.last_state, probe_secrets(probe))}
                   if probe and getattr(probe, "last_run", None) else {}),
                **({"cert_days_left": probe_extras(probe, ups)["cert_days_left"]}
                   if probe and "cert_days_left" in probe_extras(probe, ups) else {}),
            })
        elif kind == "graph":
            preset = BY_ID.get(w.get("preset") or "")
            comp = components.get(w.get("component_id")) if preset and preset.kind else None
            if comp is not None and comp.device_id != dev_id:
                comp = None  # never follow a component of another device
            relevant = [s for s in by_device.get(dev_id, []) if dev_id in used and (comp is None or s.component_id == comp.id)]
            out_series = graph_series(w, preset, series.get(w.get("id"), {}))
            widgets.append({
                **base, "title": graph_title(w, preset, comp), "state": state_name(worst(s.state for s in relevant)),
                "unit": preset.unit if preset else "count", "area": preset.area if preset else True,
                "series": out_series,
                "last": {s["name"]: (s["points"][-1][1] if s["points"] else None) for s in out_series},
                **({"colors": w["colors"]} if w.get("colors") else {}),
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


async def _build(session, d: Dashboard, range_: str, only: str | None = None) -> dict[str, Any]:
    widgets = d.widgets or []
    used = dashboard_devices(widgets)
    pids = probe_ids(widgets)
    probes = {p.id: p for p in await session.scalars(select(Probe).where(Probe.id.in_(pids)))} if pids else {}
    devices = {dv.id: dv for dv in await session.scalars(select(Device).where(Device.id.in_(used)))} if used else {}
    svc_devs = used | {p.device_id for p in probes.values()}
    services = list(await session.scalars(select(Service).where(Service.device_id.in_(svc_devs)))) if svc_devs else []
    comp_ids = {w["component_id"] for w in widgets if w.get("component_id")}
    components = {c.id: c for c in await session.scalars(select(Component).where(Component.id.in_(comp_ids)))} if comp_ids else {}

    series: dict[str, dict[str, list]] = {}
    for w in widgets:
        if w.get("type") != "graph" or (only is not None and w.get("id") != only):
            continue
        preset = BY_ID.get(w.get("preset") or "")
        if is_probe_widget(w):
            probe = probes.get(w.get("probe_id"))
            if not probe:
                continue
            names = list(PROBE_BAND) if not preset or preset.id == "probe_latency" else [m.name for m in preset.metrics]
            series[w["id"]] = await bucketed_series(session, probe.device_id, 0, names, range_,
                                                    preset.bucket(range_) if preset else None)
            continue
        if not preset or w.get("device_id") not in devices:
            continue
        comp_id = 0
        if preset.kind:
            comp = components.get(w.get("component_id"))
            if not comp or comp.device_id != w["device_id"]:
                continue  # misconfigured widget: no data rather than an error
            comp_id = comp.id
        series[w["id"]] = await bucketed_series(session, w["device_id"], comp_id, [m.name for m in preset.metrics], range_)
    wanted = [w for w in widgets if only is None or w.get("id") == only]
    ups = await uptimes(session, list(probes)) if probes else {}
    beats: dict[int, list] = {}
    for pid in {w.get("probe_id") for w in wanted if w.get("type") == "uptime" and w.get("probe_id") in probes}:
        rows = await session.execute(select(ProbeBeat.time, ProbeBeat.state, ProbeBeat.response_ms)
                                     .where(ProbeBeat.probe_id == pid).order_by(ProbeBeat.time.desc()).limit(BEATS_MAX))
        beats[pid] = [(t, st, ms) for t, st, ms in rows][::-1]
    return build_payload(d, range_, devices, services, components, series, probes, only, ups, beats)


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
    payload = await _build(session, d, range)
    response.headers.update(CACHE_HEADERS)
    return payload


@router.get("/dashboards/{dashboard_id}/widgets/{widget_id}")
async def get_public_widget(dashboard_id: int, widget_id: str, token: PublicToken, session: Session,
                            response: Response, range: RangeName = "24h"):  # noqa: A002
    """One widget in the same format as in the dashboard (for a small section on a website)."""
    d = await _public_dashboard(session, dashboard_id)
    if not any(w.get("id") == widget_id for w in d.widgets or []):
        raise HTTPException(404, "Widget not found")
    payload = await _build(session, d, range, only=widget_id)
    if not payload["widgets"]:
        raise HTTPException(404, "Widget not found")
    response.headers.update(CACHE_HEADERS)
    return payload["widgets"][0]
