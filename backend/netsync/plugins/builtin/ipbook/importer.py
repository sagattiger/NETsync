"""IP Book import: read a CSV or Excel sheet, find its header row under any title banner, map its columns, clean
the values (N/A, S/N, the old mixed Type column) and plan the merge with what discovery already knows.
Nothing here writes to the database; the API shows the plan as a preview and saves it on confirm."""

from __future__ import annotations

import csv
import io
import ipaddress
import re
from typing import Any

from netsync.plugins.builtin.ipbook.columns import BUILTIN
from netsync.plugins.builtin.ipbook.netlogic import is_private
from netsync.plugins.builtin.ipbook.values import clean_value

MAX_BYTES = 5 * 1024 * 1024
MAX_ROWS = 5000
MAX_COLS = 256  # Excel sheets with formatted empty columns declare 16384 of them
EMPTY = {"", "n/a", "na", "-", "--", "—"}
BY_KEY = {c["key"]: c for c in BUILTIN}
IP_KEYS = [c["key"] for c in BUILTIN if c["type"] == "ip"]


def _norm(text: str) -> str:
    return re.sub(r"[\s_/\-.]+", "", str(text or "").lower())


LABELS = {**{_norm(c["key"]): c["key"] for c in BUILTIN}, **{_norm(c["label"]): c["key"] for c in BUILTIN},
          _norm("Service"): "service", _norm("Hostname"): "hostname", _norm("Device"): "hostname",
          _norm("Telnet"): "telnet_port", _norm("SSH"): "ssh_port", _norm("Notes"): "description"}


def _cell(v: Any) -> str:
    if v is None:
        return ""
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    return str(v).strip()


def read_table(data: bytes, filename: str, sheet: str | None = None) -> tuple[list[list[str]], list[str]]:
    """All cells as text, and the workbook's sheet names ([] for CSV)."""
    if len(data) > MAX_BYTES:
        raise ValueError(f"The file is larger than {MAX_BYTES // (1024 * 1024)} MB")
    if filename.lower().endswith((".xlsx", ".xlsm")):
        from openpyxl import load_workbook

        try:
            wb = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
        except Exception as e:
            raise ValueError(f"Not a readable Excel file ({type(e).__name__})") from e
        names = list(wb.sheetnames)
        ws = wb[sheet] if sheet in names else wb[names[0]]
        rows = [_trim([_cell(v) for v in row]) for _, row in
                zip(range(MAX_ROWS), ws.iter_rows(values_only=True, max_col=MAX_COLS), strict=False)]
        wb.close()
        return rows, names
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = data.decode("latin-1")
    first = "\n".join(text.splitlines()[:20])
    sep = max((";", ",", "\t"), key=first.count)
    rows = [_trim([_cell(c) for c in r][:MAX_COLS]) for _, r in
            zip(range(MAX_ROWS), csv.reader(io.StringIO(text), delimiter=sep), strict=False)]
    return rows, []


def _trim(row: list[str]) -> list[str]:
    """Drop empty cells at the end of a row."""
    end = len(row)
    while end and not row[end - 1]:
        end -= 1
    return row[:end]


def find_header(table: list[list[str]]) -> int:
    """Index of the first row with at least three cells naming known columns."""
    for i, row in enumerate(table):
        if sum(1 for c in row if _norm(c) in LABELS) >= 3:
            return i
    raise ValueError("No header row found: the sheet needs a row with column names like Hostname, IP Mgmt, IP Lan")


def guess_mapping(header: list[str]) -> list[str | None]:
    seen: set[str] = set()
    out: list[str | None] = []
    for cell in header:
        key = LABELS.get(_norm(cell))
        out.append(key if key and key not in seen else None)
        if key:
            seen.add(key)
    return out


def split_type(raw: str) -> tuple[str | None, str | None]:
    """The old mixed Type column: a kind of machine sets Type, anything else is the OS of a Device."""
    text = str(raw or "").strip()
    low = text.lower()
    if low in EMPTY:
        return None, None
    if "lxc" in low:
        return "LXC", None
    if "docker" in low:
        return "Docker", None
    if re.search(r"\b(vm|kvm|virtual machine)\b", low) or low.startswith("vm"):
        return "VM", None
    if low in ("device", "physical", "bare metal"):
        return "Device", None
    return "Device", text


def clean_cell(key: str, raw: str) -> Any:
    """One sheet cell for a column: empty markers → None; typed columns parsed when they parse, else kept as text."""
    text = str(raw or "").strip()
    if text.lower() in EMPTY:
        return None
    col = BY_KEY.get(key, {"key": key, "label": key, "type": "text"})
    if col["type"] in ("secret", "text", "longtext"):
        return text
    if col["type"] == "ip":  # "10.0.0.5/24" and "10.0.0.5/10.0.0.6" are common in sheets
        parts = [p for p in re.split(r"[\s,;/]+", text) if p and not p.isdigit()]
        text = ", ".join(parts) or text
    try:
        return clean_value(col, text)
    except ValueError:
        return None if col["type"] in ("bool", "choice") else text


def sheet_rows(table: list[list[str]], header_row: int, mapping: list[str | None],
               custom_types: dict[str, str] | None = None) -> tuple[list[dict], int]:
    """Data rows under the header as {column key: value}; fully empty rows are skipped and counted."""
    rows, skipped = [], 0
    for raw in table[header_row + 1:]:
        if not any(str(c).strip().lower() not in EMPTY for c in raw):
            skipped += 1
            continue
        row: dict[str, Any] = {}
        for i, key in enumerate(mapping):
            if not key or i >= len(raw):
                continue
            cell = raw[i]
            if key == "type":
                kind, os_name = split_type(cell)
                if kind:
                    row["type"] = kind
                if os_name and "os" not in row:
                    row["os"] = os_name
            elif key == "service":
                if str(cell).strip().lower() not in EMPTY:
                    row["service"] = {"name": str(cell).strip(), "logo": None}
            elif key == "hypervisor":
                if str(cell).strip().lower() not in EMPTY:
                    row["hypervisor_name"] = str(cell).strip()
            elif key in BY_KEY:
                value = clean_cell(key, cell)
                if value is not None:
                    row[key] = value
            else:  # a new custom column chosen in the mapping
                ctype = (custom_types or {}).get(key, "text")
                text = str(cell).strip()
                if text.lower() not in EMPTY:
                    try:
                        row[key] = text if ctype in ("secret", "text", "longtext") else clean_value(
                            {"key": key, "label": key, "type": ctype}, text)
                    except ValueError:
                        row[key] = text
        if row:
            rows.append(row)
        else:
            skipped += 1
    return rows, skipped


def _host_names(name: str | None) -> set[str]:
    low = str(name or "").strip().lower()
    return {low, low.split(".")[0]} - {""} if low else set()


def sheet_ips(row: dict) -> list[str]:
    out = []
    for key in IP_KEYS:
        for item in re.split(r"[\s,;]+", str(row.get(key) or "")):
            try:
                out.append(str(ipaddress.ip_address(item)))
            except ValueError:
                continue
    return out


def plan_import(rows: list[dict], existing: list[dict], networks: list[str]) -> dict:
    """What an import would do. ``existing``: [{"id", "hostname", "ips", "values"}]. Match by host name (with or
    without the domain), then by IP only when that IP is in exactly one sheet row and one existing row."""
    by_name: dict[str, list[int]] = {}
    by_ip: dict[str, list[int]] = {}
    for e in existing:
        for n in _host_names(e.get("hostname")):
            by_name.setdefault(n, []).append(e["id"])
        for ip in e.get("ips") or []:
            by_ip.setdefault(ip, []).append(e["id"])
    sheet_ip_count: dict[str, int] = {}
    for r in rows:
        for ip in set(sheet_ips(r)):
            sheet_ip_count[ip] = sheet_ip_count.get(ip, 0) + 1
    known = [ipaddress.ip_network(n, strict=False) for n in networks]
    existing_by_id = {e["id"]: e for e in existing}

    plan: dict[str, Any] = {"create": [], "merge": [], "skip": 0, "networks": []}
    taken: set[int] = set()
    proposed: set[str] = set()
    for r in rows:
        ips = sheet_ips(r)
        if not (r.get("hostname") or (r.get("service") or {}).get("name") or ips):
            plan["skip"] += 1
            continue
        match = None
        for n in _host_names(r.get("hostname")):
            ids = [i for i in by_name.get(n, []) if i not in taken]
            if len(ids) == 1:
                match = ids[0]
                break
        if match is None:
            for ip in ips:
                ids = by_ip.get(ip, [])
                if sheet_ip_count.get(ip) == 1 and len(ids) == 1 and ids[0] not in taken:
                    match = ids[0]
                    break
        if match is None:
            plan["create"].append(r)
        else:
            taken.add(match)
            current = existing_by_id[match].get("values") or {}
            conflicts = {k: {"manual": v, "discovered": current[k]} for k, v in r.items()
                         if k in current and current[k] not in (None, "") and not _same(k, current[k], v)}
            plan["merge"].append({"row_id": match, "values": r, "conflicts": conflicts})
        for ip in ips:
            addr = ipaddress.ip_address(ip)
            if addr.version == 4 and is_private(ip) and not any(addr in n for n in known if n.version == 4):
                proposed.add(str(ipaddress.ip_network(f"{ip}/24", strict=False)))
    plan["networks"] = sorted(proposed, key=lambda n: ipaddress.ip_network(n))
    return plan


def _same(key: str, current: Any, sheet: Any) -> bool:
    if key == "service" and isinstance(current, dict) and isinstance(sheet, dict):
        return (current.get("name") or "") == (sheet.get("name") or "")  # a sheet has no logos
    return current == sheet


def merge_sheet_values(current: dict, sheet: dict) -> dict:
    """An entry's values after an import: the sheet's win, but a service logo the sheet doesn't have is kept."""
    out = {**current, **sheet}
    old, new = current.get("service"), sheet.get("service")
    if isinstance(old, dict) and isinstance(new, dict) and not new.get("logo") and old.get("logo"):
        out["service"] = {**new, "logo": old["logo"]}
    return out
