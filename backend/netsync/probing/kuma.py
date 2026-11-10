"""Uptime Kuma backup import (Settings -> Backup -> Export, a JSON file with monitorList / notificationList).

``map_backup`` is pure: it turns monitors into ProbeIn payloads, lists what is skipped (and why) and lists the
notifications that need to be set up again in NETsync. Notification secrets are never imported."""

import json
from typing import Any

from pydantic import ValidationError

from netsync.probes import INTERVAL_RANGE
from netsync.probing.checkers.json_api import parse_path

SUPPORTED = {"http", "keyword", "json-query", "port", "ping", "dns", "push"}
MAX_MONITORS = 2000


def _clamp(v: Any, lo: int, hi: int, default: int) -> tuple[int, bool]:
    try:
        n = int(v)
    except (TypeError, ValueError):
        return default, False
    return min(hi, max(lo, n)), not lo <= n <= hi


def _headers(raw: Any) -> dict | None:
    if not raw:
        return None
    if isinstance(raw, dict):
        data = raw
    else:
        try:
            data = json.loads(raw)
        except (TypeError, ValueError):
            return None
    if not isinstance(data, dict):
        return None
    return {str(k): str(v) for k, v in data.items()}


def map_monitor(m: dict) -> tuple[dict | None, list[str], str | None]:
    """(ProbeIn payload or None, warnings, skip reason)."""
    mtype = str(m.get("type") or "")
    if mtype not in SUPPORTED:
        return None, [], f"type '{mtype or 'unknown'}' is not supported yet"
    warnings: list[str] = []
    interval, clamped = _clamp(m.get("interval"), *INTERVAL_RANGE, 60)
    if clamped:
        warnings.append(f"interval {m.get('interval')}s changed to {interval}s")
    retry_interval, _ = _clamp(m.get("retryInterval") or interval, *INTERVAL_RANGE, interval)
    retries = min(20, max(1, int(m.get("maxretries") or 0) + 1))  # Kuma: retries *after* the first failure
    timeout, _ = _clamp(m.get("timeout") or 10, 1, 120, 10)
    timeout = min(timeout, interval - 1)
    tags = []
    for t in m.get("tags") or []:
        name = (t.get("name") if isinstance(t, dict) else str(t)) or ""
        value = t.get("value") if isinstance(t, dict) else None
        label = f"{name}:{value}" if value else name
        if label and len(label) <= 32 and label not in tags:
            tags.append(label)
    body: dict[str, Any] = {
        "name": " ".join(str(m.get("name") or "").split())[:64] or f"kuma-{m.get('id')}",
        "interval_s": interval, "timeout_s": max(1, timeout), "retries": retries,
        "retry_interval_s": retry_interval if retry_interval != interval else None,
        "upside_down": bool(m.get("upsideDown")), "enabled": bool(m.get("active", True)),
        "tags": tags[:20], "description": (m.get("description") or None) and str(m["description"])[:2000],
        "config": {}, "secrets": {},
    }

    if mtype in ("http", "keyword", "json-query"):
        body["kind"] = "json" if mtype == "json-query" else "http"
        body["target"] = str(m.get("url") or "")
        cfg = body["config"]
        cfg["method"] = str(m.get("method") or "GET").upper()
        codes = m.get("accepted_statuscodes") or ["200-299"]
        cfg["accepted_codes"] = ",".join(str(c) for c in (codes if isinstance(codes, list) else [codes]))
        cfg["ignore_tls"] = bool(m.get("ignoreTls"))
        redirects, _ = _clamp(m.get("maxredirects", 10), 0, 10, 10)
        cfg["max_redirects"] = redirects
        cfg["follow_redirects"] = redirects > 0
        if m.get("body"):
            cfg["body"] = str(m["body"])[:65536]
            enc = str(m.get("httpBodyEncoding") or "json").lower()
            cfg["body_type"] = "json" if enc == "json" else "form" if enc in ("form", "x-www-form-urlencoded") else "raw"
            if cfg["body_type"] == "json":
                try:
                    json.loads(cfg["body"])
                except ValueError:
                    cfg["body_type"] = "raw"
        if headers := _headers(m.get("headers")):
            body["secrets"]["headers"] = headers
            warnings.append("request headers are stored encrypted")
        auth = m.get("authMethod")
        if auth == "basic" or (not auth and m.get("basic_auth_user")):
            cfg["auth"], cfg["auth_user"] = "basic", str(m.get("basic_auth_user") or "")
            if m.get("basic_auth_pass"):
                body["secrets"]["password"] = str(m["basic_auth_pass"])
            warnings.append("basic auth password is stored encrypted")
        elif auth:
            warnings.append(f"authentication '{auth}' is not supported: imported without it")
        if mtype == "keyword":
            if m.get("keyword"):
                cfg["keyword"] = str(m["keyword"])[:1024]
                cfg["keyword_absent"] = bool(m.get("invertKeyword"))
            else:
                warnings.append("keyword monitor without a keyword")
        if mtype == "json-query":
            path, expected = str(m.get("jsonPath") or "").strip(), m.get("expectedValue")
            try:
                if not path:
                    raise ValueError
                parse_path(path)
                op = str(m.get("jsonPathOperator") or "==")
                op = op if op in ("==", "!=", "<", "<=", ">", ">=", "contains") else "=="
                cfg["assertions"] = [{"path": path, "op": op, "value": None if expected is None else str(expected)}]
            except ValueError:
                warnings.append(f"JSON query {path!r} (JSONata) can't be converted: add an assertion by hand")
        if m.get("expiryNotification") and body["target"].lower().startswith("https://"):
            warnings.append("certificate expiry is checked automatically for https (WARN 21 / CRIT 7 days)")
    elif mtype == "port":
        body.update(kind="tcp", target=str(m.get("hostname") or ""), port=m.get("port"))
    elif mtype == "ping":
        body.update(kind="icmp", target=str(m.get("hostname") or ""))
        if m.get("packetSize") and m.get("packetSize") != 56:
            warnings.append("custom packet size ignored")
    elif mtype == "dns":
        server = str(m.get("dns_resolve_server") or "").split(",")[0].strip()
        body.update(kind="dns", target=str(m.get("hostname") or ""))
        body["config"] = {"record_type": str(m.get("dns_resolve_type") or "A").upper(),
                          "resolver": server or None, "resolver_port": int(m.get("port") or 53)}
    elif mtype == "push":
        body.update(kind="push", target="")
        body["config"] = {"grace_s": 30}
        warnings.append("gets a new push URL: update the job that calls it")
    if not body["secrets"]:
        body.pop("secrets")
    return body, warnings, None


def map_backup(data: Any) -> dict:
    """{"create": [{"payload", "warnings"}], "skipped": [{"name", "type", "reason"}],
    "notifications": [{"name", "type"}]} - validation happens in the API (ProbeIn)."""
    if not isinstance(data, dict) or not isinstance(data.get("monitorList"), list):
        raise ValueError("not an Uptime Kuma backup (monitorList missing)")
    monitors = data["monitorList"]
    if len(monitors) > MAX_MONITORS:
        raise ValueError(f"too many monitors ({len(monitors)} > {MAX_MONITORS})")
    out: dict = {"create": [], "skipped": [], "notifications": [], "version": data.get("version")}
    for m in monitors:
        if not isinstance(m, dict):
            continue
        payload, warnings, reason = map_monitor(m)
        name = str(m.get("name") or f"monitor {m.get('id')}")
        if reason:
            out["skipped"].append({"name": name, "type": m.get("type"), "reason": reason})
        else:
            out["create"].append({"payload": payload, "warnings": warnings, "kuma_type": m.get("type")})
    for n in data.get("notificationList") or []:
        if not isinstance(n, dict):
            continue
        ntype = None
        try:
            cfg = json.loads(n.get("config") or "{}") if isinstance(n.get("config"), str) else (n.get("config") or {})
            ntype = cfg.get("type")
        except ValueError:
            pass
        out["notifications"].append({"name": str(n.get("name") or "notification"), "type": ntype or "unknown"})
    return out


def validation_error(e: ValidationError) -> str:
    first = e.errors()[0] if e.errors() else {}
    return str(first.get("msg") or e).removeprefix("Value error, ")
