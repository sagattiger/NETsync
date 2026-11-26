"""IP Book row values: checking each column type, editing (secrets kept when sent back empty), what a role may see,
revealing one secret, and search. Secret values live only in ``secrets_enc``; nothing here ever puts one in a
row view."""

from __future__ import annotations

import ipaddress
import re
from typing import Any
from urllib.parse import urlsplit

from netsync.plugins.builtin.ipbook.columns import secret_keys
from netsync.probing.secrets import decrypt, encrypt

TRUE = {"true", "yes", "y", "s", "sim", "1", "on"}
FALSE = {"false", "no", "n", "não", "nao", "0", "off"}
ROW_FIELDS = ("id", "sensitive", "source", "alert_when_down", "runs_on_id", "device_id", "conflicts", "manual_keys")


def _split(raw: Any) -> list[str]:
    items = raw if isinstance(raw, list) else re.split(r"[\s,;]+", str(raw))
    return [str(x).strip() for x in items if str(x).strip()]


def _url(label: str, raw: str) -> str:
    parts = urlsplit(raw)
    if parts.scheme.lower() not in ("http", "https") or not parts.netloc:
        raise ValueError(f"{label}: {raw!r} is not an http:// or https:// address")
    return raw


def clean_value(col: dict, raw: Any) -> Any:
    """The stored form of one value for this column, None when empty; ValueError("<label>: ...") when invalid."""
    label, kind = col.get("label") or col["key"], col.get("type", "text")
    if raw is None or (isinstance(raw, str) and not raw.strip()):
        return None
    if kind == "service":
        if not isinstance(raw, dict):
            raw = {"name": str(raw)}
        name = str(raw.get("name") or "").strip()
        logo = raw.get("logo") or None
        if logo:
            from netsync.api.dashboards import validate_logo

            logo = validate_logo(str(logo))
        return {"name": name, "logo": logo} if name or logo else None
    if kind == "device":
        if not isinstance(raw, dict) or not isinstance(raw.get("id"), int):
            raise ValueError(f"{label}: pick a device")
        return {"id": raw["id"], "name": str(raw.get("name") or "")}
    text = str(raw).strip() if not isinstance(raw, list) else raw
    if kind == "ip":
        out = []
        for item in _split(text):
            try:
                out.append(str(ipaddress.ip_address(item)))
            except ValueError:
                raise ValueError(f"{label}: {item!r} is not an IP address") from None
        return ", ".join(out) or None
    if kind == "urls":
        return [_url(label, u) for u in _split(text)] or None
    if kind == "url":
        return _url(label, text)
    if kind in ("port", "number"):
        try:
            num = float(text) if kind == "number" and "." in text else int(text)
        except ValueError:
            raise ValueError(f"{label}: {text!r} is not a number") from None
        if kind == "port" and not 1 <= num <= 65535:
            raise ValueError(f"{label}: a port is 1-65535")
        return num
    if kind == "bool":
        if isinstance(raw, bool):
            return raw
        low = text.lower()
        if low in TRUE or low in FALSE:
            return low in TRUE
        raise ValueError(f"{label}: {text!r} is not yes or no")
    if kind == "choice":
        if text not in (col.get("options") or []):
            raise ValueError(f"{label}: {text!r} is not one of {', '.join(col.get('options') or [])}")
        return text
    return text  # text, longtext, secret


def apply_edit(row_values: dict, row_secrets: dict, columns: list[dict], body: dict,
               manual_keys: set[str]) -> tuple[dict, dict, set[str]]:
    """New plain values, secrets and manual keys after an edit. A secret sent as "" or left out keeps the stored
    one; None clears it. Every key in ``body`` becomes a manual value (discovery won't change it)."""
    by_key = {c["key"]: c for c in columns}
    secrets = secret_keys(columns)
    vals, sec, manual = dict(row_values or {}), dict(row_secrets or {}), set(manual_keys or ())
    for key, raw in body.items():
        if key not in by_key:
            raise ValueError(f"Unknown column {key}")
        if key in secrets:
            if raw is None:
                sec.pop(key, None)
                manual.add(key)
            elif str(raw) != "":
                sec[key] = str(raw)
                manual.add(key)
            continue
        value = clean_value(by_key[key], raw)
        if value is None:
            vals.pop(key, None)
        else:
            vals[key] = value
        manual.add(key)
    return vals, sec, manual


def seal(secrets: dict, secret_key: str | None = None) -> str | None:
    return encrypt(secrets, secret_key)


def unseal(token: str | None, secret_key: str | None = None) -> dict:
    return decrypt(token, secret_key)


def reveal(row, column: str, secret_key: str | None = None) -> str | None:
    return unseal(row.secrets_enc, secret_key).get(column)


def public_row(row, columns: list[dict], is_admin: bool, secret_key: str | None = None) -> dict | None:
    """The row as a role may see it: None for a sensitive row unless admin; secrets only as {"set": bool}."""
    if row.sensitive and not is_admin:
        return None
    secrets = secret_keys(columns)
    stored = unseal(row.secrets_enc, secret_key) if row.secrets_enc else {}
    view = {f: getattr(row, f, None) for f in ROW_FIELDS}
    view["values"] = {k: v for k, v in (row.values or {}).items() if k not in secrets}
    view["secrets"] = {k: {"set": bool(stored.get(k))} for k in sorted(secrets, key=lambda k: [c["key"] for c in columns].index(k))}
    view["missing_since"] = row.missing_since.isoformat() if getattr(row, "missing_since", None) else None
    return view


def _text(v: Any) -> str:
    if isinstance(v, dict):
        return " ".join(str(x) for x in v.values() if x)
    if isinstance(v, list):
        return " ".join(str(x) for x in v)
    return str(v)


def search_matches(row_public: dict, q: str, ip_columns: set[str]) -> bool:
    """Text contains (case-insensitive) on visible values; an IP query also matches by prefix or CIDR."""
    q = q.strip()
    if not q:
        return True
    vals = row_public.get("values") or {}
    if "/" in q:
        try:
            net = ipaddress.ip_network(q, strict=False)
        except ValueError:
            net = None
        if net is not None:
            for k in ip_columns:
                for item in _split(vals.get(k) or ""):
                    try:
                        if ipaddress.ip_address(item) in net:
                            return True
                    except (ValueError, TypeError):
                        continue
            return False
    low = q.lower()
    return any(low in _text(v).lower() for v in vals.values())
