"""NETsync's own read-only tools: the facts the AI needs (devices, problems, alert history, syslog, metrics).

The numbers are computed here, in SQL, so even a small model only has to phrase them. Users only see devices of
their groups; MCP tokens see every device (an admin created them).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import func, or_, select

from netsync.db import SessionLocal
from netsync.metrics_query import bucketed_series
from netsync.models import (
    Component,
    Device,
    Role,
    Service,
    State,
    StateChange,
    SyslogMessage,
    device_group_members,
    user_groups,
)
from netsync.presets import BY_ID
from netsync.tools import hub
from netsync.tools.base import Tool, ToolContext, ToolError, schema

STATE = {0: "OK", 1: "WARN", 2: "CRIT", 3: "UNKNOWN"}
SEVERITY = ["emerg", "alert", "crit", "err", "warning", "notice", "info", "debug"]
DEVICE_ARG = {"type": "string", "description": "Hostname (or part of it, if unique) or numeric device id", "maxLength": 255}


def iso(t: datetime | None) -> str | None:
    return t.astimezone(UTC).isoformat(timespec="seconds") if t else None


def minutes(td: timedelta) -> int:
    return int(td.total_seconds() // 60)


async def allowed_devices(session, ctx: ToolContext) -> set[int] | None:
    """Device ids this caller may read; None = all (admins and MCP tokens)."""
    user = ctx.actor.user
    if user is None or user.role == Role.ADMIN:
        return None
    groups = select(user_groups.c.group_id).where(user_groups.c.user_id == user.id)
    return set(await session.scalars(select(device_group_members.c.device_id).where(
        device_group_members.c.group_id.in_(groups))))


async def resolve_device(session, ctx: ToolContext, ref: str) -> Device:
    ref = (ref or "").strip()
    allowed = await allowed_devices(session, ctx)
    q = select(Device).where(Device.device_type.is_distinct_from("probe"))
    if ref.isdigit():
        d = await session.scalar(q.where(Device.id == int(ref)))
        matches = [d] if d else []
    else:
        matches = list(await session.scalars(q.where(Device.hostname.ilike(ref))))
        if not matches:
            matches = list(await session.scalars(q.where(or_(Device.hostname.ilike(f"{ref}%"),
                                                              Device.hostname.ilike(f"%{ref}%"))).limit(20)))
    if allowed is not None:
        matches = [d for d in matches if d.id in allowed]
    if not matches:
        raise ToolError(f"no device matches {ref!r}")
    if len(matches) > 1:
        names = ", ".join(sorted(d.hostname for d in matches)[:10])
        raise ToolError(f"{ref!r} matches several devices ({names}); use the full hostname")
    return matches[0]


# --------------------------------------------------------------------------- handlers


async def find_devices(ctx: ToolContext, a: dict) -> dict:
    async with SessionLocal() as s:
        allowed = await allowed_devices(s, ctx)
        q = select(Device).where(Device.device_type.is_distinct_from("probe")).order_by(Device.hostname)
        if a.get("query"):
            q = q.where(or_(Device.hostname.ilike(f"%{a['query']}%"), Device.os.ilike(f"%{a['query']}%"),
                            Device.device_type.ilike(f"%{a['query']}%")))
        devices = [d for d in await s.scalars(q) if allowed is None or d.id in allowed]
        counts = {}
        if devices:
            rows = await s.execute(select(Service.device_id, Service.state, func.count()).where(
                Service.device_id.in_([d.id for d in devices])).group_by(Service.device_id, Service.state))
            for did, st, n in rows:
                counts.setdefault(did, {})[STATE.get(st, "UNKNOWN")] = n
    out = []
    for d in devices:
        c = counts.get(d.id, {})
        problems = c.get("WARN", 0) + c.get("CRIT", 0)
        if a.get("only_problems") and not problems and d.status == State.OK:
            continue
        out.append({"id": d.id, "hostname": d.hostname, "type": d.device_type, "os": d.os,
                    "reachable": d.status == State.OK, "services": c})
    return {"count": len(out), "devices": out[: a["limit"]]}


async def device_overview(ctx: ToolContext, a: dict) -> dict:
    async with SessionLocal() as s:
        d = await resolve_device(s, ctx, a["device"])
        comps = list(await s.scalars(select(Component).where(Component.device_id == d.id, Component.deleted.is_(False))))
        services = list(await s.scalars(select(Service).where(Service.device_id == d.id)))
    cpus = [c for c in comps if c.kind == "processor"]
    stats = next((c for c in comps if c.kind == "system_stats"), None)
    v = (stats.values if stats else {}) or {}
    loads = [c.values.get("load") for c in cpus if c.values.get("load") is not None]
    problems = sorted((sv for sv in services if sv.state in (1, 2, 3)), key=lambda sv: -sv.state)
    return {
        "hostname": d.hostname, "type": d.device_type, "os": d.os, "version": d.version, "hardware": d.hardware,
        "reachable": d.status == State.OK, "uptime_seconds": d.uptime, "last_polled": iso(d.last_polled),
        "cpu": {"model": next((c.attrs.get("model") for c in cpus if c.attrs.get("model")), None), "threads": len(cpus),
                "load_pct": round(sum(loads) / len(loads), 1) if loads else None,
                "load_avg": [v.get("load1"), v.get("load5"), v.get("load15")] if v.get("load1") is not None else None},
        "memory": {k: v.get(k) for k in ("mem_total", "mem_used", "mem_available", "swap_total", "swap_used")} if v else None,
        "filesystems": [{"mount": c.name, "used_pct": round(c.values.get("pct"), 1) if c.values.get("pct") is not None else None,
                         "size_bytes": c.values.get("size")} for c in comps if c.kind == "storage"],
        "service_counts": {name: sum(1 for sv in services if sv.state == st) for st, name in STATE.items()},
        "open_problems": [{"service": sv.name, "state": STATE.get(sv.state), "since": iso(sv.last_change),
                           "output": (sv.output or "")[:300], "acknowledged": sv.acknowledged} for sv in problems[:30]],
    }


async def list_problems(ctx: ToolContext, a: dict) -> dict:
    async with SessionLocal() as s:
        allowed = await allowed_devices(s, ctx)
        q = select(Service, Device.hostname).join(Device, Device.id == Service.device_id).where(Service.state.in_([1, 2, 3]))
        if a.get("device"):
            d = await resolve_device(s, ctx, a["device"])
            q = q.where(Service.device_id == d.id)
        if not a.get("include_acknowledged"):
            q = q.where(Service.acknowledged.is_(False))
        rows = [(sv, host) for sv, host in await s.execute(q.order_by(Service.state.desc(), Service.last_change))
                if allowed is None or sv.device_id in allowed]
    now = datetime.now(UTC)
    return {"count": len(rows), "problems": [
        {"device": host, "service": sv.name, "state": STATE.get(sv.state), "since": iso(sv.last_change),
         "minutes_open": minutes(now - sv.last_change) if sv.last_change else None,
         "acknowledged": sv.acknowledged, "output": (sv.output or "")[:300]} for sv, host in rows[: a["limit"]]]}


def episodes(changes: list[tuple[datetime, int, int]], since: datetime, now: datetime) -> list[dict]:
    """Problem episodes from state changes (oldest first): a problem starts when the state leaves OK and ends
    when it returns to OK. Each: start, end (None = still open), minutes, worst state."""
    out: list[dict] = []
    cur: dict | None = None
    for t, old, new in changes:
        if new != State.OK and cur is None:
            cur = {"start": t, "worst": new}
        elif new != State.OK and cur is not None:
            cur["worst"] = max(cur["worst"], new, key=lambda s: {0: 0, 3: 1, 1: 2, 2: 3}.get(s, 1))
        elif new == State.OK and cur is not None:
            cur["end"] = t
            out.append(cur)
            cur = None
    if cur is not None:
        cur["end"] = None
        out.append(cur)
    result = []
    for e in out:
        if (e["end"] or now) < since:
            continue
        start = max(e["start"], since)
        result.append({"start": e["start"], "end": e["end"], "minutes": minutes((e["end"] or now) - start),
                       "worst": STATE.get(e["worst"], "UNKNOWN")})
    return result


async def alert_history(ctx: ToolContext, a: dict) -> dict:
    now = datetime.now(UTC)
    since = now - timedelta(days=a["days"])
    async with SessionLocal() as s:
        d = await resolve_device(s, ctx, a["device"])
        q = select(Service).where(Service.device_id == d.id)
        if a.get("service"):
            q = q.where(Service.name.ilike(f"%{a['service']}%"))
        services = list(await s.scalars(q))
        if a.get("service") and not services:
            raise ToolError(f"{d.hostname} has no service matching {a['service']!r}")
        ids = [sv.id for sv in services]
        # one change before the window tells whether a problem was already open when it started
        rows = await s.execute(select(StateChange.service_id, StateChange.time, StateChange.old_state, StateChange.new_state)
                               .where(StateChange.device_id == d.id, StateChange.service_id.in_(ids),
                                      StateChange.time >= since - timedelta(days=30)).order_by(StateChange.time))
    by_service: dict[int, list] = {}
    for sid, t, old, new in rows:
        by_service.setdefault(sid, []).append((t, old, new))
    report = []
    for sv in services:
        eps = episodes(by_service.get(sv.id, []), since, now)
        if not eps and not a.get("service"):
            continue
        report.append({
            "service": sv.name, "current_state": STATE.get(sv.state), "times": len(eps),
            "total_minutes": sum(e["minutes"] for e in eps), "longest_minutes": max((e["minutes"] for e in eps), default=0),
            "first": iso(eps[0]["start"]) if eps else None, "last": iso(eps[-1]["start"]) if eps else None,
            "open_now": bool(eps and eps[-1]["end"] is None),
            "episodes": [{"start": iso(e["start"]), "end": iso(e["end"]), "minutes": e["minutes"], "worst": e["worst"]}
                         for e in eps[-a["max_episodes"]:]],
        })
    report.sort(key=lambda r: (-r["times"], -r["total_minutes"]))
    hit = [r for r in report if r["times"]]
    return {"device": d.hostname, "days": a["days"], "services_with_problems": len(hit),
            "alerts_total": sum(r["times"] for r in hit), "minutes_total": sum(r["total_minutes"] for r in hit),
            "longest": max(({"service": r["service"], "minutes": r["longest_minutes"]} for r in hit),
                           key=lambda x: x["minutes"], default=None),
            "services": report[:50]}


async def search_syslog(ctx: ToolContext, a: dict) -> dict:
    since = datetime.now(UTC) - timedelta(days=a["days"])
    async with SessionLocal() as s:
        allowed = await allowed_devices(s, ctx)
        q = select(SyslogMessage).where(SyslogMessage.time >= since, SyslogMessage.message.ilike(f"%{a['text']}%"))
        if a.get("device"):
            d = await resolve_device(s, ctx, a["device"])
            q = q.where(SyslogMessage.device_id == d.id)
        elif allowed is not None:
            q = q.where(SyslogMessage.device_id.in_(allowed))
        if a.get("min_severity") is not None:
            q = q.where(SyslogMessage.severity <= SEVERITY.index(a["min_severity"]))
        sub = q.subquery()
        stats = (await s.execute(select(func.count(), func.min(sub.c.time), func.max(sub.c.time)))).first()
        counts = list(await s.execute(select(sub.c.device_id, func.count()).group_by(sub.c.device_id)
                                      .order_by(func.count().desc()).limit(50)))
        sample = list(await s.scalars(q.order_by(SyslogMessage.time.desc()).limit(a["limit"])))
        ids = {did for did, _ in counts if did} | {m.device_id for m in sample if m.device_id}
        hosts = {d.id: d.hostname for d in await s.scalars(select(Device).where(Device.id.in_(ids)))} if ids else {}
        per_device = [(hosts.get(did) if did else None, n) for did, n in counts]
    return {"text": a["text"], "days": a["days"], "count": stats[0], "first": iso(stats[1]), "last": iso(stats[2]),
            "by_device": {h or "unknown sender": n for h, n in per_device},
            "latest": [{"time": iso(m.time), "device": hosts.get(m.device_id, m.hostname), "severity": SEVERITY[m.severity]
                        if 0 <= m.severity < 8 else m.severity, "program": m.program, "message": m.message[:500]}
                       for m in sample]}


async def metric_summary(ctx: ToolContext, a: dict) -> dict:
    graph = str(a["graph"]).strip().lower().replace(" ", "_").replace("-", "_")
    preset = BY_ID.get(GRAPH_ALIASES.get(graph, graph))
    if preset is None or preset.source != "device":
        raise ToolError(f"unknown graph {a['graph']!r}; graphs: {GRAPHS}")
    rng = {1: "24h", 7: "7d", 30: "30d", 365: "1y"}[a["days"]]
    async with SessionLocal() as s:
        d = await resolve_device(s, ctx, a["device"])
        comp_id = 0
        comp_name = None
        if preset.kind:
            if not a.get("component"):
                names = [c.name for c in await s.scalars(select(Component).where(
                    Component.device_id == d.id, Component.kind == preset.kind, Component.deleted.is_(False)).limit(40))]
                raise ToolError(f"graph {preset.id} needs a component ({preset.kind}): one of {', '.join(names) or 'none'}")
            comp = await s.scalar(select(Component).where(Component.device_id == d.id, Component.kind == preset.kind,
                                                          Component.deleted.is_(False), Component.name.ilike(a["component"])))
            if comp is None:
                raise ToolError(f"{d.hostname} has no {preset.kind} named {a['component']!r}")
            comp_id, comp_name = comp.id, comp.name
        data = await bucketed_series(s, d.id, comp_id, [m.name for m in preset.metrics], rng)
    series = {}
    for m in preset.metrics:
        pts = [p for p in data.get(m.name, []) if p[1] is not None]
        if not pts:
            series[m.label] = None
            continue
        peak = max(pts, key=lambda p: p[3] if p[3] is not None else p[1])
        series[m.label] = {"avg": round(sum(p[1] for p in pts) / len(pts), 3), "min": round(min(p[2] for p in pts), 3),
                           "max": round(peak[3], 3), "max_at": peak[0], "last": round(pts[-1][1], 3), "points": len(pts)}
    return {"device": d.hostname, "graph": preset.label, "component": comp_name, "unit": preset.unit, "days": a["days"],
            "series": series}


async def call_result(ctx: ToolContext, a: dict) -> dict:
    return await hub.result_of(a["call_id"], ctx.actor)


# --------------------------------------------------------------------------- definitions

GRAPHS = ", ".join(p.id for p in BY_ID.values() if p.source == "device")
GRAPH_ALIASES = {"ram": "mem_usage", "mem": "mem_usage", "memory_usage": "mem_usage", "swap": "swap_usage",
                 "traffic": "port_traffic", "bandwidth": "port_traffic", "disk": "storage", "filesystem": "storage",
                 "ping": "latency", "packet_loss": "loss", "cpu_load": "cpu", "cpu_usage": "cpu", "temp": "temperature",
                 "fan": "fanspeed", "load_average": "load"}

TOOLS = [
    Tool("netsync__find_devices", "List monitored devices with reachability and service counts per state. "
         "Use it to find a hostname or to see which devices have problems.",
         schema({"query": {"type": "string", "maxLength": 100, "description": "Part of a hostname, OS or type"},
                 "only_problems": {"type": "boolean", "default": False},
                 "limit": {"type": "integer", "minimum": 1, "maximum": 200, "default": 50}}),
         find_devices, plugin="netsync"),
    Tool("netsync__device_overview", "Everything about one device now: OS, CPU model/threads/load, memory and swap "
         "(bytes), filesystems, service counts and open problems.",
         schema({"device": DEVICE_ARG}, ["device"]), device_overview, plugin="netsync"),
    Tool("netsync__list_problems", "Open problems (WARN, CRIT, UNKNOWN services) with how long each has been open.",
         schema({"device": DEVICE_ARG, "include_acknowledged": {"type": "boolean", "default": False},
                 "limit": {"type": "integer", "minimum": 1, "maximum": 200, "default": 50}}),
         list_problems, plugin="netsync"),
    Tool("netsync__alert_history", "How many times and for how long alerts happened on a device: per service the "
         "number of problem episodes, total and longest minutes, first/last time and whether one is open now.",
         schema({"device": DEVICE_ARG, "service": {"type": "string", "maxLength": 255, "description": "Part of the service name, e.g. 'Ping' or 'Filesystem /'"},
                 "days": {"type": "integer", "minimum": 1, "maximum": 730, "default": 30},
                 "max_episodes": {"type": "integer", "minimum": 0, "maximum": 100, "default": 10}}, ["device"]),
         alert_history, plugin="netsync"),
    Tool("netsync__search_syslog", "Count and show syslog messages containing a text: total, first and last time, "
         "count per device and the latest messages.",
         schema({"text": {"type": "string", "maxLength": 200}, "device": DEVICE_ARG,
                 "days": {"type": "integer", "minimum": 1, "maximum": 365, "default": 7},
                 "min_severity": {"type": "string", "enum": SEVERITY, "description": "Only this severity or worse"},
                 "limit": {"type": "integer", "minimum": 0, "maximum": 100, "default": 20}}, ["text"]),
         search_syslog, plugin="netsync"),
    Tool("netsync__metric_summary", f"Average, minimum, maximum (with time) and latest value of a graph over 1, 7, "
         f"30 or 365 days. Graphs: {GRAPHS}. Port, disk, filesystem and sensor graphs need 'component' (its name).",
         schema({"device": DEVICE_ARG, "graph": {"type": "string", "maxLength": 64},
                 "component": {"type": "string", "maxLength": 255},
                 "days": {"type": "integer", "enum": [1, 7, 30, 365], "default": 1}}, ["device", "graph"]),
         metric_summary, plugin="netsync"),
    Tool("netsync__call_result", "Status and result of an earlier tool call that needed approval (by call_id).",
         schema({"call_id": {"type": "integer", "minimum": 1}}, ["call_id"]), call_result, plugin="netsync"),
]
