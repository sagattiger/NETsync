"""IP Book API (/api/plugins/ipbook). Everyone signed in reads non-sensitive rows without secret values; only admins
write, see sensitive rows and reveal secrets (one at a time, audited). Any role may press Ping."""

from __future__ import annotations

import base64
import ipaddress
import re
import time
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sqlalchemy import select

from netsync.alerting import redis
from netsync.api.deps import CurrentUser, Session, require
from netsync.models import Device, IpbColumn, IpbNetwork, IpbReveal, IpbRow, Role, real_device
from netsync.plugins.builtin.ipbook import columns as colmod
from netsync.plugins.builtin.ipbook import health, importer, netlogic
from netsync.plugins.builtin.ipbook.values import apply_edit, public_row, reveal, seal, search_matches, unseal

router = APIRouter()
NET_FIELDS = ("id", "cidr", "title", "description", "icon", "vlan", "gateway", "dns", "alert_when_down", "source",
              "hidden")
RESTRICTED = "Conflict with a restricted entry"
PING_EVERY_S = 5
_last_ping: dict[str, float] = {}


# ------------------------------------------------------------------------------- pure helpers (tested)


def can_see(row, role: str) -> bool:
    return not row.sensitive or role == Role.ADMIN


def custom_key(label: str, taken: set[str]) -> str:
    base = "c_" + (re.sub(r"[^a-z0-9]+", "_", label.lower()).strip("_") or "column")[:40]
    key, n = base, 2
    while key in taken:
        key, n = f"{base}_{n}", n + 1
    return key


def delete_column_check(col, rows) -> int:
    """How many rows have a value in this column; built-in columns can't be deleted."""
    if col.builtin:
        raise ValueError("Built-in columns can't be deleted, only hidden")
    return sum(1 for r in rows if (r.values or {}).get(col.key) not in (None, "", []))


def _filter_warnings(ws: list[dict], hidden_ids: set[int]) -> list[dict]:
    out = []
    for w in ws:
        if hidden_ids & set(w["rows"]):
            w = {**w, "text": RESTRICTED, "rows": [i for i in w["rows"] if i not in hidden_ids]}
        out.append(w)
    return out


def net_out(n) -> dict:
    return {f: getattr(n, f, None) for f in NET_FIELDS}


def network_view(network, networks, rows, columns, is_admin: bool, states: dict, device_ips: dict, row_devices: dict,
                 now: datetime, secret_key: str | None = None) -> dict:
    """A network (or None for "all rows") with usage, grid, warnings and the rows a role may see."""
    ip_cols = colmod.ip_keys(columns)
    found = netlogic.warnings(networks, rows, ip_cols, device_ips, row_devices, now)
    hidden_ids = set() if is_admin else {r.id for r in rows if r.sensitive}
    if network is not None:
        members = netlogic.rows_in_network(network, rows, ip_cols)
        net = ipaddress.ip_network(network.cidr, strict=False)
        used = {ip for r, _ in members for _, ip in netlogic.row_ips(r, ip_cols) if ipaddress.ip_address(ip) in net}
    else:
        members = [(r, []) for r in rows]
        used = set()
    grid_states: dict[str, str] = {}
    out_rows = []
    for r, keys in members:
        r_ips = netlogic.row_ips(r, ip_cols)
        for _, ip in r_ips:
            if ip in used and grid_states.get(ip) != "used":
                grid_states[ip] = "down" if (states.get(health.key(r.id, ip)) or {}).get("state") == "down" else "used"
        if r.id in hidden_ids:
            continue
        pub = public_row(r, columns, is_admin, secret_key)
        pub["match_keys"] = keys
        pub["health"] = {ip: states[health.key(r.id, ip)] for _, ip in r_ips if health.key(r.id, ip) in states}
        pub["warnings"] = _filter_warnings(found["rows"].get(r.id, []), hidden_ids)
        out_rows.append(pub)
    view: dict[str, Any] = {"network": net_out(network) if network is not None else None, "rows": out_rows}
    if network is not None:
        view["usage"] = netlogic.usage(network.cidr, used)
        view["grid"] = netlogic.grid(network.cidr, grid_states)
        view["warnings"] = _filter_warnings(found["networks"].get(network.id, []), hidden_ids)
    return view


# ------------------------------------------------------------------------------- loading


async def _columns(session) -> list[dict]:
    await colmod.seed(session)
    cols = list(await session.scalars(select(IpbColumn).order_by(IpbColumn.position, IpbColumn.id)))
    return [{"id": c.id, "key": c.key, "label": c.label, "type": c.type, "icon": c.icon, "options": c.options,
             "position": c.position, "hidden": c.hidden, "builtin": c.builtin} for c in cols]


async def _context(session):
    cols = await _columns(session)
    nets = list(await session.scalars(select(IpbNetwork).order_by(IpbNetwork.cidr)))
    rows = list(await session.scalars(select(IpbRow).order_by(IpbRow.id)))
    device_ips: dict[str, int] = {}
    for d in await session.scalars(select(Device).where(real_device())):
        for ip in [d.ip, *(d.ip_addresses or [])]:
            if ip:
                device_ips.setdefault(str(ip).split("/")[0], d.id)
    row_devices = {r.id: r.device_id for r in rows}
    return cols, nets, rows, device_ips, row_devices


def _admin(user) -> bool:
    return user.role == Role.ADMIN


async def _row_for(session, user, row_id: int) -> IpbRow:
    row = await session.get(IpbRow, row_id)
    if row is None or not can_see(row, user.role):
        raise HTTPException(404, "Entry not found")
    return row


# ------------------------------------------------------------------------------- reads


@router.get("/overview")
async def overview(session: Session, user: CurrentUser):
    cols, nets, rows, device_ips, row_devices = await _context(session)
    await session.commit()  # seeded columns
    admin = _admin(user)
    ip_cols = colmod.ip_keys(cols)
    found = netlogic.warnings(nets, rows, ip_cols, device_ips, row_devices, datetime.now(UTC))
    out = []
    in_any: set[int] = set()
    for n in nets:
        members = netlogic.rows_in_network(n, rows, ip_cols)
        in_any |= {r.id for r, _ in members}
        if n.hidden and not admin:
            continue
        net = ipaddress.ip_network(n.cidr, strict=False)
        used = {ip for r, _ in members for _, ip in netlogic.row_ips(r, ip_cols) if ipaddress.ip_address(ip) in net}
        out.append({**net_out(n), "usage": netlogic.usage(n.cidr, used),
                    "warning_count": len(found["networks"].get(n.id, [])) + sum(
                        1 for r, _ in members if found["rows"].get(r.id))})
    visible = [r for r in rows if can_see(r, user.role)]
    return {"networks": out, "columns": cols, "is_admin": admin,
            "counts": {"all": len(visible), "no_network": sum(1 for r in visible if r.id not in in_any)}}


@router.get("/networks/{network_id}")
async def network(network_id: str, session: Session, user: CurrentUser):
    cols, nets, rows, device_ips, row_devices = await _context(session)
    states = await health.read(redis())
    admin = _admin(user)
    now = datetime.now(UTC)
    if network_id == "all":
        return network_view(None, nets, rows, cols, admin, states, device_ips, row_devices, now)
    if network_id == "none":
        ip_cols = colmod.ip_keys(cols)
        in_any = {r.id for n in nets for r, _ in netlogic.rows_in_network(n, rows, ip_cols)}
        view = network_view(None, nets, rows, cols, admin, states, device_ips, row_devices, now)
        view["rows"] = [r for r in view["rows"] if r["id"] not in in_any]
        return view
    n = next((x for x in nets if str(x.id) == network_id), None)
    if n is None or (n.hidden and not admin):
        raise HTTPException(404, "Network not found")
    return network_view(n, nets, rows, cols, admin, states, device_ips, row_devices, now)


@router.get("/search")
async def search(q: str, session: Session, user: CurrentUser):
    cols, nets, rows, device_ips, row_devices = await _context(session)
    view = network_view(None, nets, rows, cols, _admin(user), await health.read(redis()), device_ips, row_devices,
                        datetime.now(UTC))
    ip_cols = colmod.ip_keys(cols)
    return {"rows": [r for r in view["rows"] if search_matches(r, q, ip_cols)][:500]}


# ------------------------------------------------------------------------------- networks


class NetworkIn(BaseModel):
    cidr: str
    title: str = ""
    description: str | None = None
    icon: str | None = None
    vlan: str | None = None
    gateway: str | None = None
    dns: str | None = None
    alert_when_down: bool = False
    hidden: bool = False


def _cidr(text: str) -> str:
    try:
        return str(ipaddress.ip_network(text.strip(), strict=False))
    except ValueError:
        raise HTTPException(400, f"{text!r} is not a network like 10.0.0.0/24") from None


@router.post("/networks", dependencies=[require(Role.ADMIN)])
async def add_network(body: NetworkIn, session: Session):
    cidr = _cidr(body.cidr)
    if await session.scalar(select(IpbNetwork.id).where(IpbNetwork.cidr == cidr)):
        raise HTTPException(409, f"{cidr} is already in IP Book")
    n = IpbNetwork(**{**body.model_dump(), "cidr": cidr, "title": body.title.strip() or cidr}, source="manual")
    session.add(n)
    await session.commit()
    return net_out(n)


@router.put("/networks/{network_id}", dependencies=[require(Role.ADMIN)])
async def update_network(network_id: int, body: NetworkIn, session: Session):
    n = await session.get(IpbNetwork, network_id)
    if n is None:
        raise HTTPException(404)
    cidr = _cidr(body.cidr)
    if n.source == "learned" and cidr != n.cidr:
        raise HTTPException(400, "A learned network's address can't change")
    if cidr != n.cidr and await session.scalar(select(IpbNetwork.id).where(IpbNetwork.cidr == cidr)):
        raise HTTPException(409, f"{cidr} is already in IP Book")
    for k, v in {**body.model_dump(), "cidr": cidr, "title": body.title.strip() or cidr}.items():
        setattr(n, k, v)
    n.updated_at = datetime.now(UTC)
    await session.commit()
    return net_out(n)


@router.delete("/networks/{network_id}", dependencies=[require(Role.ADMIN)])
async def delete_network(network_id: int, session: Session):
    """A manual network is deleted; a learned one is hidden, so discovery doesn't bring it back."""
    n = await session.get(IpbNetwork, network_id)
    if n is None:
        raise HTTPException(404)
    if n.source == "learned":
        n.hidden = True
    else:
        await session.delete(n)
    await session.commit()
    return {"ok": True}


# ------------------------------------------------------------------------------- columns


class ColumnIn(BaseModel):
    label: str
    type: str = "text"
    icon: str | None = None
    options: list[str] | None = None
    hidden: bool = False


@router.post("/columns", dependencies=[require(Role.ADMIN)])
async def add_column(body: ColumnIn, session: Session):
    cols = await _columns(session)
    if body.type not in colmod.TYPES or body.type in ("service", "device"):
        raise HTTPException(400, "Unknown column type")
    if body.type == "choice" and not [o for o in body.options or [] if o.strip()]:
        raise HTTPException(400, "A choice column needs options")
    label = body.label.strip()
    if not label:
        raise HTTPException(400, "A column needs a name")
    c = IpbColumn(key=custom_key(label, {c["key"] for c in cols}), label=label, type=body.type, icon=body.icon,
                  options=[o.strip() for o in body.options or [] if o.strip()] or None,
                  position=max((c["position"] for c in cols), default=0) + 1, hidden=body.hidden, builtin=False)
    session.add(c)
    await session.commit()
    return {"key": c.key, "id": c.id}


@router.put("/columns/{column_id}", dependencies=[require(Role.ADMIN)])
async def update_column(column_id: int, body: ColumnIn, session: Session):
    c = await session.get(IpbColumn, column_id)
    if c is None:
        raise HTTPException(404)
    c.label, c.icon, c.hidden = body.label.strip() or c.label, body.icon, body.hidden
    if c.type == "choice" and body.options is not None:
        c.options = [o.strip() for o in body.options if o.strip()] or c.options
    await session.commit()
    return {"ok": True}


class OrderIn(BaseModel):
    ids: list[int]


@router.put("/columns-order", dependencies=[require(Role.ADMIN)])
async def order_columns(body: OrderIn, session: Session):
    for pos, cid in enumerate(body.ids):
        c = await session.get(IpbColumn, cid)
        if c is not None:
            c.position = pos
    await session.commit()
    return {"ok": True}


@router.delete("/columns/{column_id}", dependencies=[require(Role.ADMIN)])
async def delete_column(column_id: int, session: Session, confirm: bool = False):
    c = await session.get(IpbColumn, column_id)
    if c is None:
        raise HTTPException(404)
    rows = list(await session.scalars(select(IpbRow)))
    try:
        count = delete_column_check(c, rows)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    if c.type == "secret":
        count = sum(1 for r in rows if unseal(r.secrets_enc).get(c.key))
    if count and not confirm:
        raise HTTPException(409, f"{count} entries have a value in {c.label}; deleting the column deletes them")
    for r in rows:
        if c.key in (r.values or {}):
            r.values = {k: v for k, v in r.values.items() if k != c.key}
        if c.type == "secret" and r.secrets_enc:
            sec = unseal(r.secrets_enc)
            if c.key in sec:
                sec.pop(c.key)
                r.secrets_enc = seal(sec)
    await session.delete(c)
    await session.commit()
    return {"ok": True, "cleared": count}


# ------------------------------------------------------------------------------- rows


class RowIn(BaseModel):
    values: dict[str, Any] = {}
    sensitive: bool = False
    alert_when_down: bool | None = None
    runs_on_id: int | None = None


def _check_runs_on(row_id: int | None, runs_on_id: int | None, rows_by_id: dict) -> None:
    if runs_on_id is None:
        return
    if runs_on_id == row_id or runs_on_id not in rows_by_id:
        raise HTTPException(400, "Runs on: pick another entry")


@router.post("/rows", dependencies=[require(Role.ADMIN)])
async def add_row(body: RowIn, session: Session, user: CurrentUser):
    cols = await _columns(session)
    rows_by_id = {r.id: r for r in await session.scalars(select(IpbRow))}
    _check_runs_on(None, body.runs_on_id, rows_by_id)
    try:
        vals, sec, manual = apply_edit({}, {}, cols, body.values, set())
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    r = IpbRow(values=vals, secrets_enc=seal(sec), manual_keys=sorted(manual), sensitive=body.sensitive,
               alert_when_down=body.alert_when_down, runs_on_id=body.runs_on_id, source="manual", learned={},
               conflicts={}, updated_by=user.username)
    session.add(r)
    await session.commit()
    return public_row(r, cols, True)


@router.put("/rows/{row_id}", dependencies=[require(Role.ADMIN)])
async def update_row(row_id: int, body: RowIn, session: Session, user: CurrentUser):
    cols = await _columns(session)
    r = await session.get(IpbRow, row_id)
    if r is None:
        raise HTTPException(404)
    rows_by_id = {x.id: x for x in await session.scalars(select(IpbRow))}
    _check_runs_on(row_id, body.runs_on_id, rows_by_id)
    try:
        vals, sec, manual = apply_edit(r.values, unseal(r.secrets_enc), cols, body.values, set(r.manual_keys or []))
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    r.values, r.secrets_enc, r.manual_keys = vals, seal(sec), sorted(manual)
    r.sensitive, r.alert_when_down, r.runs_on_id = body.sensitive, body.alert_when_down, body.runs_on_id
    r.updated_at, r.updated_by = datetime.now(UTC), user.username
    await session.commit()
    return public_row(r, cols, True)


@router.delete("/rows/{row_id}", dependencies=[require(Role.ADMIN)])
async def delete_row(row_id: int, session: Session):
    r = await session.get(IpbRow, row_id)
    if r is not None:
        await session.delete(r)
        await session.commit()
    return {"ok": True}


class KeepIn(BaseModel):
    keep: str  # manual | discovered


@router.post("/rows/{row_id}/conflicts/{key}", dependencies=[require(Role.ADMIN)])
async def resolve_conflict(row_id: int, key: str, body: KeepIn, session: Session):
    r = await session.get(IpbRow, row_id)
    if r is None or key not in (r.conflicts or {}):
        raise HTTPException(404)
    if body.keep == "discovered":
        r.values = {**(r.values or {}), key: r.conflicts[key]["discovered"]}
        r.manual_keys = [k for k in r.manual_keys or [] if k != key]
    r.conflicts = {k: v for k, v in r.conflicts.items() if k != key}
    await session.commit()
    return {"ok": True}


class RevealIn(BaseModel):
    column: str
    action: str = "reveal"  # reveal | copy


@router.post("/rows/{row_id}/reveal")
async def reveal_secret(row_id: int, body: RevealIn, session: Session, user=require(Role.ADMIN)):  # noqa: B008
    r = await _row_for(session, user, row_id)
    cols = await _columns(session)
    if body.column not in colmod.secret_keys(cols):
        raise HTTPException(400, "Not a secret column")
    session.add(IpbReveal(username=user.username, row_id=r.id, column=body.column,
                          action="copy" if body.action == "copy" else "reveal"))
    await session.commit()
    return {"value": reveal(r, body.column)}


@router.post("/rows/{row_id}/ping")
async def ping_row(row_id: int, session: Session, user: CurrentUser):
    r = await _row_for(session, user, row_id)
    now = time.monotonic()
    if now - _last_ping.get(user.username, 0) < PING_EVERY_S:
        raise HTTPException(429, "Wait a few seconds between pings")
    _last_ping[user.username] = now
    cols = await _columns(session)
    ips = sorted({ip for _, ip in netlogic.row_ips(r, colmod.ip_keys(cols))})
    results = await health.ping(ips)
    states = await health.read(redis())
    at = datetime.now(UTC)
    new = {health.key(r.id, ip): health.next_state(states.get(health.key(r.id, ip)), *results.get(ip, (False, None)), at)
           for ip in ips}
    # the button answers at once, but only an answer counts: a missed ping here doesn't add to the 3 misses
    await health.write(redis(), {k: v for k, v in new.items() if v["state"] == "up"})
    return {"ips": [{"ip": ip, "up": results.get(ip, (False, None))[0], "rtt_ms": results.get(ip, (False, None))[1]}
                    for ip in ips]}


# ------------------------------------------------------------------------------- import


class ImportIn(BaseModel):
    filename: str
    content_b64: str
    sheet: str | None = None
    mapping: list[str | None] | None = None
    new_columns: dict[str, dict] = {}  # key from the mapping → {"label", "type"} for columns to create
    networks: list[str] | None = None  # the proposed networks the admin kept (commit only)


async def _existing(session, cols) -> list[dict]:
    ip_cols = colmod.ip_keys(cols)
    return [{"id": r.id, "hostname": (r.values or {}).get("hostname"),
             "ips": [ip for _, ip in netlogic.row_ips(r, ip_cols)], "values": r.values or {}}
            for r in await session.scalars(select(IpbRow))]


def _read(body: ImportIn):
    try:
        data = base64.b64decode(body.content_b64, validate=True)
        table, sheets = importer.read_table(data, body.filename, body.sheet)
        header_row = importer.find_header(table)
    except (ValueError, TypeError) as e:
        raise HTTPException(400, str(e)) from e
    header = table[header_row]
    mapping = body.mapping if body.mapping is not None else importer.guess_mapping(header)
    if len(mapping) != len(header):
        raise HTTPException(400, "The mapping doesn't match the sheet's columns")
    custom_types = {k: v.get("type", "text") for k, v in body.new_columns.items()}
    rows, skipped = importer.sheet_rows(table, header_row, mapping, custom_types)
    return sheets, header_row, header, mapping, rows, skipped


def _safe_plan(plan: dict, secret_keys: set[str]) -> dict:
    """The preview never shows secret values: they are replaced by a marker."""
    def mask(vals: dict) -> dict:
        return {k: ("••••••" if k in secret_keys and v else v) for k, v in vals.items()}

    return {**plan, "create": [mask(r) for r in plan["create"]],
            "merge": [{**m, "values": mask(m["values"]),
                       "conflicts": {k: v for k, v in m["conflicts"].items() if k not in secret_keys}}
                      for m in plan["merge"]]}


@router.post("/import/preview", dependencies=[require(Role.ADMIN)])
async def import_preview(body: ImportIn, session: Session):
    cols = await _columns(session)
    sheets, header_row, header, mapping, rows, skipped = _read(body)
    nets = [n.cidr for n in await session.scalars(select(IpbNetwork))]
    plan = importer.plan_import(rows, await _existing(session, cols), nets)
    plan["skip"] += skipped
    secrets = colmod.secret_keys(cols) | {k for k, v in body.new_columns.items() if v.get("type") == "secret"}
    return {"sheets": sheets, "header_row": header_row, "header": header, "mapping": mapping,
            "columns": [{"key": c["key"], "label": c["label"]} for c in cols], "plan": _safe_plan(plan, secrets)}


async def _hypervisor(session, name: str) -> dict | None:
    low = name.strip().lower()
    for d in await session.scalars(select(Device).where(real_device())):
        if low in {d.hostname.lower(), d.hostname.lower().split(".")[0], (d.sys_name or "").lower()}:
            return {"id": d.id, "name": d.hostname}
    return None


@router.post("/import/commit", dependencies=[require(Role.ADMIN)])
async def import_commit(body: ImportIn, session: Session, user: CurrentUser):
    cols = await _columns(session)
    taken = {c["key"] for c in cols}
    for key, spec in body.new_columns.items():  # columns the admin chose to create from the sheet
        if key in taken or not key.startswith("c_"):
            continue
        ctype = spec.get("type", "text") if spec.get("type") in colmod.TYPES else "text"
        session.add(IpbColumn(key=key, label=str(spec.get("label") or key)[:128], type=ctype, builtin=False,
                              position=len(taken) + 1))
        taken.add(key)
    await session.flush()
    cols = await _columns(session)
    secrets = colmod.secret_keys(cols)
    _, _, _, _, rows, skipped = _read(body)
    nets = [n.cidr for n in await session.scalars(select(IpbNetwork))]
    plan = importer.plan_import(rows, await _existing(session, cols), nets)

    async def split(sheet: dict) -> tuple[dict, dict]:
        vals, sec = {}, {}
        for k, v in sheet.items():
            if k == "hypervisor_name":
                hyp = await _hypervisor(session, v)
                if hyp:
                    vals["hypervisor"] = hyp
                continue
            (sec if k in secrets else vals)[k] = v
        return vals, sec

    for sheet in plan["create"]:
        vals, sec = await split(sheet)
        session.add(IpbRow(values=vals, secrets_enc=seal(sec), manual_keys=sorted(vals) + sorted(sec), source="imported",
                           learned={}, conflicts={}, updated_by=user.username))
    for m in plan["merge"]:
        r = await session.get(IpbRow, m["row_id"])
        vals, sec = await split(m["values"])
        r.values = {**(r.values or {}), **vals}
        r.secrets_enc = seal({**unseal(r.secrets_enc), **sec})
        r.manual_keys = sorted(set(r.manual_keys or []) | set(vals) | set(sec))
        r.conflicts = {**(r.conflicts or {}), **{k: v for k, v in m["conflicts"].items() if k not in secrets}}
        r.updated_at, r.updated_by = datetime.now(UTC), user.username
    keep = plan["networks"] if body.networks is None else body.networks
    have = set(nets)
    added = 0
    for text in keep:
        cidr = _cidr(text)
        if cidr not in have:
            session.add(IpbNetwork(cidr=cidr, title=cidr, source="manual"))
            have.add(cidr)
            added += 1
    await session.commit()
    return {"created": len(plan["create"]), "merged": len(plan["merge"]), "skipped": plan["skip"] + skipped,
            "networks": added}

