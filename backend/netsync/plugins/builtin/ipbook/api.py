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
from netsync.models import Device, IpbAddress, IpbBook, IpbColumn, IpbReveal, IpbRow, Role, real_device
from netsync.plugins.builtin.ipbook import addrlogic, health, importer, netlogic
from netsync.plugins.builtin.ipbook import columns as colmod
from netsync.plugins.builtin.ipbook.values import apply_edit, public_row, reveal, seal, search_matches, unseal

router = APIRouter()
NET_FIELDS = ("id", "cidr", "title", "description", "icon", "vlan", "gateway", "dns", "alert_when_down")
BOOK_FIELDS = ("id", "kind", "title", "heading", "description", "icon", "cidr", "vlan", "gateway", "dns",
               "alert_when_down", "scan", "position")
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


def resolve_new_columns(mapping: list[str | None], new_columns: dict[str, dict],
                        existing: list[dict]) -> tuple[list[str | None], dict[str, dict]]:
    """New columns from an import get keys chosen here (never the client's, which may name an existing column of
    another type); the mapping is rewritten to them. Unknown types become text."""
    taken = {c["key"] for c in existing}
    keys: dict[str, str] = {}
    specs: dict[str, dict] = {}
    for client_key, spec in new_columns.items():
        label = str(spec.get("label") or client_key).strip()[:128] or "Column"
        ctype = spec.get("type") if spec.get("type") in colmod.TYPES and spec.get("type") not in ("service", "device", "choice") else "text"
        key = custom_key(label, taken)[:64]
        taken.add(key)
        keys[client_key] = key
        specs[key] = {"label": label, "type": ctype}
    return [keys.get(m, m) if m else None for m in mapping], specs


def _filter_warnings(ws: list[dict], hidden_ids: set[int]) -> list[dict]:
    out = []
    for w in ws:
        if hidden_ids & set(w["rows"]):
            w = {**w, "text": RESTRICTED, "rows": [i for i in w["rows"] if i not in hidden_ids]}
        out.append(w)
    return out


def book_out(b) -> dict:
    return {f: getattr(b, f, None) for f in BOOK_FIELDS}


def book_fields(kind: str, body: dict) -> dict:
    """The stored fields of a new or edited book; ValueError with a message for the admin."""
    if kind not in ("ip", "service"):
        raise ValueError("A book is an IP book or a service book")
    def text(k):
        v = str(body.get(k) or "").strip()
        return v or None
    out = {"title": text("title"), "heading": text("heading"), "description": text("description"),
           "icon": text("icon"), "alert_when_down": bool(body.get("alert_when_down")), "cidr": None, "vlan": None,
           "gateway": None, "dns": None}
    if kind == "service":
        if not out["title"]:
            raise ValueError("A service book needs a name")
        return out
    if not body.get("cidr"):
        raise ValueError("An IP book needs a network, like 10.0.0.0/24")
    cidr = addrlogic.book_cidr(body["cidr"])
    out.update(cidr=cidr, vlan=text("vlan"), dns=text("dns"), title=out["title"] or cidr, scan=body.get("scan", True) is not False)
    gw = text("gateway")
    if gw:
        try:
            ok = ipaddress.ip_address(gw) in ipaddress.ip_network(cidr)
        except ValueError:
            ok = False
        if not ok:
            raise ValueError(f"The gateway {gw} is not in {cidr}")
    out["gateway"] = gw
    return out


DEVICE_FIELDS = ("id", "hostname", "os", "vendor", "sys_descr", "device_type", "virtualization")


def device_out(d) -> dict:
    return {f: getattr(d, f, None) for f in DEVICE_FIELDS}


def ip_book_view(book, stored: dict, states: dict, devices: dict[int, dict] | None = None) -> dict:
    """An IP book: its header, every address with status, values, last ping and device, and how it's used."""
    by_ip = {k.split(":", 1)[1]: v for k, v in states.items() if k.startswith(f"a{book.id}:")}
    rows = addrlogic.address_rows(book.cidr, book.gateway, stored, by_ip, devices)
    return {"book": book_out(book), "addresses": rows, "counts": addrlogic.counts(rows)}


def net_out(n) -> dict:
    return {f: getattr(n, f, None) for f in NET_FIELDS}


def network_view(network, networks, rows, columns, is_admin: bool, states: dict, device_ips: dict, row_devices: dict,
                 now: datetime, secret_key: str | None = None) -> dict:
    """A network (or None for "all rows") with usage, grid, warnings and the rows a role may see."""
    ip_cols = colmod.ip_keys(columns)
    idx = netlogic.index(networks, rows, ip_cols)
    found = netlogic.warnings(networks, rows, ip_cols, device_ips, row_devices, now, idx)
    hidden_ids = set() if is_admin else {r.id for r in rows if r.sensitive}
    if network is not None and not network.hidden:
        members = idx["members"].get(network.id, [])
        used = idx["used"].get(network.id, set())
    elif network is not None:  # a hidden network (admins only): not in the index
        members = netlogic.rows_in_network(network, rows, ip_cols)
        net = ipaddress.ip_network(network.cidr, strict=False)
        used = {ip for r, _ in members for _, ip in netlogic.row_ips(r, ip_cols) if ipaddress.ip_address(ip) in net}
    else:
        members = [(r, []) for r in rows]
        used = set()
    grid_states: dict[str, str] = {}
    out_rows = []
    for r, keys in members:
        r_ips = idx["parsed"].get(r.id, [])
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


async def _columns(session, kind: str = "service") -> list[dict]:
    await colmod.seed(session)
    cols = list(await session.scalars(select(IpbColumn).where(IpbColumn.kind == kind)
                                      .order_by(IpbColumn.position, IpbColumn.id)))
    return [{"id": c.id, "key": c.key, "label": c.label, "type": c.type, "icon": c.icon, "options": c.options,
             "position": c.position, "hidden": c.hidden, "builtin": c.builtin, "kind": c.kind} for c in cols]


async def _context(session):
    cols = await _columns(session)
    nets = list(await session.scalars(select(IpbBook).where(IpbBook.kind == "ip").order_by(IpbBook.position, IpbBook.id)))
    rows = list(await session.scalars(select(IpbRow).where(IpbRow.book_id.is_not(None)).order_by(IpbRow.id)))
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
    """Every book (IP books with how they're used, service books with their entry count) and the columns."""
    cols, ip_cols_ = await _columns(session, "service"), await _columns(session, "ip")
    await session.commit()  # seeded columns
    books = list(await session.scalars(select(IpbBook).order_by(IpbBook.kind, IpbBook.position, IpbBook.id)))
    states = await health.read(redis())
    stored: dict[int, dict] = {}
    for a in await session.scalars(select(IpbAddress)):
        stored.setdefault(a.book_id, {})[a.ip] = a
    rows = [r for r in await session.scalars(select(IpbRow).where(IpbRow.book_id.is_not(None))) if can_see(r, user.role)]
    out = []
    for b in books:
        item = book_out(b)
        if b.kind == "ip":
            item["counts"] = ip_book_view(b, stored.get(b.id, {}), states)["counts"]
        else:
            item["entries"] = sum(1 for r in rows if r.book_id == b.id)
        out.append(item)
    return {"books": out, "columns": {"service": cols, "ip": ip_cols_}, "is_admin": _admin(user)}


async def _book(session, book_id: int) -> IpbBook:
    book = await session.get(IpbBook, book_id)
    if book is None:
        raise HTTPException(404, "Book not found")
    return book


@router.get("/books/{book_id}")
async def book_view(book_id: int, session: Session, user: CurrentUser):
    book = await _book(session, book_id)
    states = await health.read(redis())
    if book.kind == "ip":
        stored = {a.ip: a for a in await session.scalars(select(IpbAddress).where(IpbAddress.book_id == book.id))}
        ids = {a.device_id for a in stored.values() if a.device_id}
        devices = {d.id: device_out(d) for d in await session.scalars(select(Device).where(Device.id.in_(ids)))} if ids else {}
        return ip_book_view(book, stored, states, devices)
    cols, nets, rows, device_ips, row_devices = await _context(session)
    view = network_view(None, nets, rows, cols, _admin(user), states, device_ips, row_devices, datetime.now(UTC))
    in_book = {r.id for r in rows if r.book_id == book.id}
    # "outside every network" isn't shown for services: IP books cover only the networks the admin added
    view["rows"] = [{**r, "warnings": [w for w in r["warnings"] if w["kind"] != "outside"]}
                    for r in view["rows"] if r["id"] in in_book]
    view["book"] = book_out(book)
    return view


@router.get("/search")
async def search(q: str, session: Session, user: CurrentUser):
    """Service entries and IP book addresses matching an IP, host name or any visible text."""
    cols, nets, rows, device_ips, row_devices = await _context(session)
    view = network_view(None, nets, rows, cols, _admin(user), await health.read(redis()), device_ips, row_devices,
                        datetime.now(UTC))
    ip_cols = colmod.ip_keys(cols)
    books = {b.id: b for b in await session.scalars(select(IpbBook))}
    book_of = {r.id: r.book_id for r in rows}
    found = [{**r, "book_id": book_of[r["id"]]} for r in view["rows"] if search_matches(r, q, ip_cols)]
    addresses = []
    for a in await session.scalars(select(IpbAddress)):
        pub = {"values": {"ip": a.ip, **(a.values or {})}}
        if search_matches(pub, q, {"ip", "addr_private_ip"}):
            b = books.get(a.book_id)
            addresses.append({"book_id": a.book_id, "book": b.title if b else "", "ip": a.ip, "values": a.values or {}})
    return {"rows": found[:500], "addresses": addresses[:500]}


# ------------------------------------------------------------------------------- books


class BookIn(BaseModel):
    kind: str = "service"
    title: str = ""
    heading: str | None = None
    description: str | None = None
    icon: str | None = None
    cidr: str | None = None
    vlan: str | None = None
    gateway: str | None = None
    dns: str | None = None
    alert_when_down: bool = False
    scan: bool = True


@router.post("/books", dependencies=[require(Role.ADMIN)])
async def add_book(body: BookIn, session: Session):
    try:
        fields = book_fields(body.kind, body.model_dump())
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    if fields["cidr"] and await session.scalar(select(IpbBook.id).where(IpbBook.cidr == fields["cidr"])):
        raise HTTPException(409, f"{fields['cidr']} already has an IP book")
    last = await session.scalar(select(IpbBook.position).where(IpbBook.kind == body.kind).order_by(IpbBook.position.desc()))
    book = IpbBook(kind=body.kind, position=(last or 0) + 1, **fields)
    session.add(book)
    await session.commit()
    return book_out(book)


@router.put("/books/{book_id}", dependencies=[require(Role.ADMIN)])
async def update_book(book_id: int, body: BookIn, session: Session):
    book = await _book(session, book_id)
    try:
        fields = book_fields(book.kind, {**body.model_dump(), "cidr": book.cidr if book.kind == "ip" else None})
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    for k, v in fields.items():
        if k != "cidr":
            setattr(book, k, v)
    await session.commit()
    return book_out(book)


@router.delete("/books/{book_id}", dependencies=[require(Role.ADMIN)])
async def delete_book(book_id: int, session: Session):
    """Deletes the book with its entries or addresses (and their passwords)."""
    book = await _book(session, book_id)
    await session.delete(book)
    await session.commit()
    return {"ok": True}


# ------------------------------------------------------------------------------- IP book addresses


class AddressIn(BaseModel):
    values: dict[str, Any] = {}
    reserved: bool = False
    alert_when_down: bool | None = None


@router.put("/books/{book_id}/addresses/{ip}", dependencies=[require(Role.ADMIN)])
async def update_address(book_id: int, ip: str, body: AddressIn, session: Session, user: CurrentUser):
    book = await _book(session, book_id)
    if book.kind != "ip" or not addrlogic.books_for(ip, [book]):
        raise HTTPException(404, "Address not in this book")
    ip = str(ipaddress.ip_address(ip))
    cols = await _columns(session, "ip")
    addr = await session.scalar(select(IpbAddress).where(IpbAddress.book_id == book.id, IpbAddress.ip == ip))
    if addr is None:
        addr = IpbAddress(book_id=book.id, ip=ip, values={}, learned={}, manual_keys=[], source="manual")
        session.add(addr)
    try:
        vals, _, manual = apply_edit(addr.values, {}, cols, body.values, set(addr.manual_keys or []))
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    addr.values, addr.manual_keys = vals, sorted(manual)
    addr.reserved, addr.alert_when_down = body.reserved, body.alert_when_down
    addr.updated_at, addr.updated_by = datetime.now(UTC), user.username
    if not vals and not addr.reserved and addr.alert_when_down is None and not addr.learned:
        await session.delete(addr)  # nothing left on it: available again
    await session.commit()
    return {"ok": True}


@router.post("/books/{book_id}/addresses/{ip}/ping")
async def ping_address(book_id: int, ip: str, session: Session, user: CurrentUser):
    book = await _book(session, book_id)
    if book.kind != "ip" or not addrlogic.books_for(ip, [book]):
        raise HTTPException(404, "Address not in this book")
    _rate_limit(user.username)
    await session.close()  # no database connection held while pinging
    up, rtt = (await health.ping([ip])).get(ip, (False, None))
    return {"ips": [{"ip": ip, "up": up, "rtt_ms": rtt}]}


MAX_PING = 256


class PingIn(BaseModel):
    ips: list[str]


@router.post("/books/{book_id}/ping")
async def ping_addresses(book_id: int, body: PingIn, session: Session, user: CurrentUser):
    """Ping the chosen addresses of an IP book now (up to 256); their health on the sheet is updated too."""
    book = await _book(session, book_id)
    if book.kind != "ip":
        raise HTTPException(400, "Only IP books have addresses to ping")
    ips = sorted({ip.strip() for ip in body.ips if addrlogic.books_for(ip.strip(), [book])})
    if not ips:
        raise HTTPException(400, "Choose addresses of this book")
    if len(ips) > MAX_PING:
        raise HTTPException(400, f"Ping up to {MAX_PING} addresses at a time")
    _rate_limit(user.username)
    await session.close()  # no database connection held while pinging
    results = await health.ping(ips, count=1, timeout=2)
    rd = redis()
    prev = await health.read(rd)
    now = datetime.now(UTC)
    states = {}
    for ip in ips:
        key = f"a{book.id}:{ip}"
        up, rtt = results.get(ip, (False, None))
        new = health.next_state(prev.get(key), up, rtt, now)
        states[key] = {**{k: v for k, v in (prev.get(key) or {}).items() if k in ("name", "name_at")}, **new}
    await health.write(rd, states)
    return {"ips": [{"ip": ip, "up": results.get(ip, (False, None))[0], "rtt_ms": results.get(ip, (False, None))[1]} for ip in ips]}


def _rate_limit(username: str) -> None:
    now = time.monotonic()
    if now - _last_ping.get(username, 0) < PING_EVERY_S:
        raise HTTPException(429, "Wait a few seconds between pings")
    _last_ping[username] = now


# ------------------------------------------------------------------------------- columns


class ColumnIn(BaseModel):
    label: str
    kind: str = "service"  # service | ip
    type: str = "text"
    icon: str | None = None
    options: list[str] | None = None
    hidden: bool = False


@router.post("/columns", dependencies=[require(Role.ADMIN)])
async def add_column(body: ColumnIn, session: Session):
    if body.kind not in ("service", "ip"):
        raise HTTPException(400, "Unknown book kind")
    cols = await _columns(session, body.kind)
    taken_all = set(await session.scalars(select(IpbColumn.key)))
    if body.type not in colmod.TYPES or body.type in ("service", "device"):
        raise HTTPException(400, "Unknown column type")
    if body.kind == "ip" and body.type == "secret":
        raise HTTPException(400, "Passwords belong in a service book (IP books hold no secrets)")
    if body.type == "choice" and not [o for o in body.options or [] if o.strip()]:
        raise HTTPException(400, "A choice column needs options")
    label = body.label.strip()
    if not label:
        raise HTTPException(400, "A column needs a name")
    c = IpbColumn(key=custom_key(label, taken_all), label=label, type=body.type, icon=body.icon, kind=body.kind,
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
    rows = list(await session.scalars(select(IpbRow))) if c.kind == "service" else list(
        await session.scalars(select(IpbAddress)))
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
        if c.type == "secret" and getattr(r, "secrets_enc", None):
            sec = unseal(r.secrets_enc)
            if c.key in sec:
                sec.pop(c.key)
                r.secrets_enc = seal(sec)
    await session.delete(c)
    await session.commit()
    return {"ok": True, "cleared": count}


# ------------------------------------------------------------------------------- rows


class RowIn(BaseModel):
    book_id: int | None = None  # required when adding; a service book
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
    book = await session.get(IpbBook, body.book_id) if body.book_id else None
    if book is None or book.kind != "service":
        raise HTTPException(400, "Pick a service book for the entry")
    cols = await _columns(session)
    rows_by_id = {r.id: r for r in await session.scalars(select(IpbRow))}
    _check_runs_on(None, body.runs_on_id, rows_by_id)
    try:
        vals, sec, manual = apply_edit({}, {}, cols, body.values, set())
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    r = IpbRow(values=vals, secrets_enc=seal(sec), manual_keys=sorted(manual), sensitive=body.sensitive,
               alert_when_down=body.alert_when_down, runs_on_id=body.runs_on_id, source="manual", learned={}, book_id=book.id,
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
    _rate_limit(user.username)
    cols = await _columns(session)
    ips = sorted({ip for _, ip in netlogic.row_ips(r, colmod.ip_keys(cols))})
    await session.close()  # no database connection held while pinging
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
    book_id: int  # the service book the entries go into
    filename: str
    content_b64: str
    sheet: str | None = None
    mapping: list[str | None] | None = None
    new_columns: dict[str, dict] = {}  # key from the mapping → {"label", "type"} for columns to create
    networks: list[str] | None = None  # the proposed networks the admin kept (commit only)


async def _existing(session, cols, book_id: int) -> list[dict]:
    ip_cols = colmod.ip_keys(cols)
    return [{"id": r.id, "hostname": (r.values or {}).get("hostname"),
             "ips": [ip for _, ip in netlogic.row_ips(r, ip_cols)], "values": r.values or {}}
            for r in await session.scalars(select(IpbRow).where(IpbRow.book_id == book_id))]


async def _service_book(session, book_id: int) -> IpbBook:
    book = await session.get(IpbBook, book_id)
    if book is None or book.kind != "service":
        raise HTTPException(400, "Pick a service book to import into")
    return book


def _read(body: ImportIn, cols: list[dict]):
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
    mapping, specs = resolve_new_columns(mapping, body.new_columns, cols)
    known = {c["key"] for c in cols} | set(specs)
    mapping = [m if m in known else None for m in mapping]  # only real columns can be written
    rows, skipped = importer.sheet_rows(table, header_row, mapping, {k: v["type"] for k, v in specs.items()})
    return sheets, header_row, header, mapping, rows, skipped, specs


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
    sheets, header_row, header, _, rows, skipped, specs = _read(body, cols)
    await _service_book(session, body.book_id)
    nets = [b.cidr for b in await session.scalars(select(IpbBook).where(IpbBook.kind == "ip"))]
    plan = importer.plan_import(rows, await _existing(session, cols, body.book_id), nets)
    plan["skip"] += skipped
    secrets = colmod.secret_keys(cols) | {k for k, v in specs.items() if v["type"] == "secret"}
    mapping = body.mapping if body.mapping is not None else importer.guess_mapping(header)
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
    _, _, _, _, rows, skipped, specs = _read(body, cols)
    pos = max((c["position"] for c in cols), default=0)
    for key, spec in specs.items():  # columns the admin chose to create from the sheet (keys chosen by the server)
        pos += 1
        session.add(IpbColumn(key=key, label=spec["label"], type=spec["type"], builtin=False, position=pos))
    await session.flush()
    cols = await _columns(session)
    secrets = colmod.secret_keys(cols)
    await _service_book(session, body.book_id)
    nets = [b.cidr for b in await session.scalars(select(IpbBook).where(IpbBook.kind == "ip"))]
    plan = importer.plan_import(rows, await _existing(session, cols, body.book_id), nets)

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
                           book_id=body.book_id,
                           learned={}, conflicts={}, updated_by=user.username))
    for m in plan["merge"]:
        r = await session.get(IpbRow, m["row_id"])
        vals, sec = await split(m["values"])
        r.values = importer.merge_sheet_values(r.values or {}, vals)
        r.secrets_enc = seal({**unseal(r.secrets_enc), **sec})
        r.manual_keys = sorted(set(r.manual_keys or []) | set(vals) | set(sec))
        r.conflicts = {**(r.conflicts or {}), **{k: v for k, v in m["conflicts"].items() if k not in secrets}}
        r.updated_at, r.updated_by = datetime.now(UTC), user.username
    added = 0  # IP books are only created by the admin
    await session.commit()
    return {"created": len(plan["create"]), "merged": len(plan["merge"]), "skipped": plan["skip"] + skipped,
            "networks": added}

