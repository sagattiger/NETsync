"""CrowdSec decisions -> totals. Pure functions, no I/O (tests: tests/test_crowdsec.py).

Source: the CrowdSec Local API, ``GET /v1/decisions`` with a bouncer API key (``X-Api-Key``). A bouncer key can only
read decisions, so NETsync can never add or remove a ban. The answer is a JSON array of decisions (``null`` when there
are none on some versions). Each decision has ``id``, ``uuid``, ``origin``, ``type``, ``scope``, ``value``,
``duration``, ``until``, ``scenario`` and ``simulated``. Decisions carry no country: that is only on alerts, which a
bouncer key can't read, so NETsync has no per-country numbers.

What the numbers mean:
  * local / community: addresses (or ranges) banned right now, deduplicated. "local" = decided by our own CrowdSec
    (origins crowdsec, cscli, appsec, console...); "community" = the CrowdSec community blocklist (CAPI) and
    subscribed lists (lists:*). They count banned IPs, not attacks or blocked requests.
  * new bans: local decisions that appeared since the previous read (decision ids only grow). The first read only
    sets the starting point; a ban that starts and ends between two reads is not seen.
  * scenarios: why the locally banned addresses are banned (crowdsecurity/ssh-bf...).

Addresses never leave this module except masked (203.0.113.x) for the admin page. Public output has no address at all.
"""

from __future__ import annotations

import ipaddress
import re
from typing import Any

TOP_SCENARIOS = 30  # scenarios kept per read (each one is a component with its own graph)
RECENT = 20  # masked recent local bans kept for the admin page

_SCENARIO_CHARS = re.compile(r"[^A-Za-z0-9_/.:-]")


class BadAnswer(ValueError):
    """The LAPI answered something that isn't a list of decisions."""


def is_community(origin: str) -> bool:
    o = (origin or "").strip().lower()
    return o == "capi" or o.startswith("lists")


def origin_group(origin: str) -> str:
    """lists:firehol_xyz -> lists; everything else as is (lower case)."""
    o = (origin or "").strip().lower()
    return "lists" if o.startswith("lists") else (o or "unknown")


def scenario_key(s: str) -> str:
    """crowdsecurity/http-probing; manual cscli bans ("manual 'ban' from 'localhost'") become "manual"."""
    s = (s or "").strip()
    if not s or s.lower().startswith("manual "):
        return "manual"
    return _SCENARIO_CHARS.sub("", s)[:80] or "other"


def mask(value: str) -> str:
    """203.0.113.7 -> 203.0.113.x; 2001:db8:1:2::7 -> 2001:db8:1::x; ranges keep their prefix length."""
    value = (value or "").strip()
    prefix = ""
    if "/" in value:
        value, length = value.split("/", 1)
        prefix = f"/{int(length)}" if length.isdigit() else ""
    try:
        ip = ipaddress.ip_address(value)
    except ValueError:
        return "x"  # not an address (country, AS...): show nothing
    if ip.version == 4:
        return ".".join(str(ip).split(".")[:3]) + ".x" + prefix
    groups = ip.exploded.split(":")[:3]
    return ":".join(g.lstrip("0") or "0" for g in groups) + "::x" + prefix


def aggregate(decisions: Any) -> dict:
    """Totals from one /v1/decisions answer. Raises BadAnswer when it isn't a decision list."""
    if decisions is None:
        decisions = []  # some LAPI versions answer null when nothing is banned
    if not isinstance(decisions, list):
        raise BadAnswer("not a list of decisions")
    local: set[str] = set()
    community: set[str] = set()
    other = simulated = 0
    by_origin: dict[str, int] = {}
    scenarios: dict[str, int] = {}
    local_ids: list[int] = []
    recent: list[dict] = []
    for d in decisions:
        if not isinstance(d, dict) or not isinstance(d.get("value"), str | int) or isinstance(d.get("value"), bool):
            continue
        if d.get("simulated") is True:
            simulated += 1  # simulation mode: nothing is actually blocked
            continue
        value = str(d["value"]).strip().lower()
        origin = d.get("origin") if isinstance(d.get("origin"), str) else "unknown"
        if str(d.get("type") or "ban").lower() != "ban":
            other += 1  # captcha, throttle...: not counted as blocked
            continue
        group = origin_group(origin)
        by_origin[group] = by_origin.get(group, 0) + 1
        if is_community(origin):
            community.add(value)
            continue
        local.add(value)
        key = scenario_key(d.get("scenario") if isinstance(d.get("scenario"), str) else "")
        scenarios[key] = scenarios.get(key, 0) + 1
        if isinstance(d.get("id"), int) and not isinstance(d.get("id"), bool):
            local_ids.append(d["id"])
            recent.append({"id": d["id"], "ip": mask(value), "scenario": key, "origin": group})
    recent.sort(key=lambda r: -r["id"])
    top = dict(sorted(scenarios.items(), key=lambda kv: (-kv[1], kv[0]))[:TOP_SCENARIOS])
    return {
        "local": len(local), "community": len(community), "total": len(local | community), "other": other,
        "simulated": simulated, "by_origin": by_origin, "scenarios": top, "local_ids": local_ids,
        "recent": recent[:RECENT],
    }


def track(state: dict | None, local_ids: list[int], now: float) -> tuple[dict, int | None]:
    """(new tracking state, new local bans since the last read); None on the first read, which only sets the start.

    ``new_total`` is a running count of new local bans. It is stored as a metric, so the bans of any period are
    ``max - previous max``, even from the hourly and daily rollups (which keep min / avg / max)."""
    st = {"max_id": None, "since": None, "new_total": 0, **(state or {})}
    top = max(local_ids) if local_ids else None
    if st["max_id"] is None:
        st["max_id"] = top or 0
        st["since"] = st["since"] or now
        return st, None
    new = sum(1 for i in local_ids if i > st["max_id"])
    if top is not None:
        st["max_id"] = top  # follow the newest active id: survives a CrowdSec database reset (ids start over)
    st["new_total"] = int(st["new_total"]) + new
    return st, new


def metrics(agg: dict, new: int | None, new_total: int) -> dict[str, float]:
    out = {"cs_local": agg["local"], "cs_community": agg["community"], "cs_total": agg["total"],
           "cs_other": agg["other"], "cs_new_total": new_total}
    if new is not None:
        out["cs_new"] = new
    return {k: float(v) for k, v in out.items()}


def scrub(text: str, *secrets: str) -> str:
    """Remove secrets (the API key) from an error text."""
    for s in secrets:
        if s:
            text = text.replace(s, "***")
    return text


# ---------------------------------------------------------------------------------------------------- public view

def merge_scenarios(items: list[dict[str, int]], limit: int = 5) -> list[dict]:
    total: dict[str, int] = {}
    for sc in items:
        for k, v in (sc or {}).items():
            total[k] = total.get(k, 0) + int(v)
    return [{"key": k, "value": v} for k, v in sorted(total.items(), key=lambda kv: (-kv[1], kv[0]))[:limit]]


def daily_new(days: list[tuple[float, float] | None], before: float | None) -> list[int | None]:
    """New bans per day from each day's (lowest, highest) running count; ``before`` is the last value before the
    first day. Days without a sample (not tracking yet, LAPI down all day) are None."""
    out: list[int | None] = []
    prev = before
    for day in days:
        if day is None:
            out.append(None)
            continue
        mn, mx = day
        start = prev if prev is not None else mn  # tracking started that day: count from its first sample
        out.append(max(0, round(mx - start)))
        prev = mx
    return out
