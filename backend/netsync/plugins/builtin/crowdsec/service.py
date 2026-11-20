"""Reads every enabled CrowdSec source on its interval and stores the results the NETsync way.

Per source (its virtual device):
  * metrics: cs_local, cs_community, cs_total, cs_other, cs_new (new local bans since the last read), cs_new_total
    (running count, for "bans per day" from any rollup) and, per scenario component (kind ``cs_scenario``), ``bans``;
  * services: "LAPI" (CRIT when unreachable, the key is refused or the answer is not a decision list) and
    "New bans" (value = new local bans since the last read; WARN past the plugin's threshold, plus any rule).

The key is decrypted only to build the request header and is scrubbed from every error text.
"""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
from sqlalchemy import select

from netsync.models import Component, CrowdSecSource, Device, State
from netsync.plugins.base import BackgroundService, CheckResult, MetricSample
from netsync.plugins.builtin.crowdsec import logic

log = logging.getLogger(__name__)

TICK = 10  # seconds between scheduler passes
SCENARIO_KIND = "cs_scenario"
LAPI_SERVICE = "LAPI"
NEW_BANS_SERVICE = "New bans"
USER_AGENT = "NETsync-crowdsec/1.0"


def decisions_url(base: str) -> str:
    return base.rstrip("/") + "/v1/decisions"


async def fetch(base_url: str, api_key: str, timeout_s: float = 10, transport=None) -> dict[str, Any]:
    """One GET /v1/decisions. Never raises. {"ok", "status", "json", "message", "ms"}; ``message`` is generic and
    never contains the key."""
    from netsync.probing.base import error_message

    started = time.monotonic()
    out: dict[str, Any] = {"ok": False, "status": None, "json": None, "message": "", "ms": None}
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(timeout_s, connect=min(4.0, timeout_s)),
                                     follow_redirects=False, transport=transport) as client:
            r = await client.get(decisions_url(base_url), headers={"X-Api-Key": api_key, "User-Agent": USER_AGENT,
                                                                   "Accept": "application/json"})
        out["ms"] = round((time.monotonic() - started) * 1000, 1)
        out["status"] = r.status_code
        if r.status_code in (401, 403):
            out["message"] = f"HTTP {r.status_code} (bouncer key refused)"
        elif r.status_code == 404:
            out["message"] = "HTTP 404 (is this a CrowdSec LAPI address?)"
        elif r.status_code != 200:
            out["message"] = f"HTTP {r.status_code}"
        else:
            try:
                out["json"] = r.json()
                out["ok"] = True
            except ValueError:
                out["message"] = "invalid JSON response"
    except httpx.TimeoutException:
        out["message"] = "timeout"
    except httpx.HTTPError as e:
        cause = e.__cause__ or e.__context__ or e
        out["message"] = error_message(cause) if isinstance(cause, OSError | TimeoutError) else "connection failed"
    except Exception:  # noqa: BLE001 - a bad URL must not stop the loop
        out["message"] = "connection failed"
    out["message"] = logic.scrub(out["message"], api_key)
    return out


def evaluate(state: dict | None, res: dict, now: float, warn_new: int = 0) -> dict[str, Any]:
    """Pure: one read -> new source state, metrics, scenario counts and checks. On failure the previous totals stay
    (so pages keep the last good numbers) and only the LAPI check goes CRIT."""
    state = dict(state or {})
    if res.get("ok"):
        try:
            agg = logic.aggregate(res.get("json"))
        except logic.BadAnswer:
            res = {**res, "ok": False, "message": "unexpected response (not a list of decisions)"}
    if not res.get("ok"):
        msg = res.get("message") or "connection failed"
        return {"ok": False, "state": state, "metrics": {}, "scenarios": None, "message": msg,
                "checks": [CheckResult("crowdsec_lapi", LAPI_SERVICE, state=State.CRIT, output=msg)]}
    tracking, new = logic.track(state.get("tracking"), agg["local_ids"], now)
    stats = {k: agg[k] for k in ("local", "community", "total", "other", "simulated", "by_origin", "scenarios")}
    state.update({"tracking": tracking, "stats": stats, "recent": agg["recent"], "ok_at": now})
    checks = [CheckResult("crowdsec_lapi", LAPI_SERVICE, state=State.OK,
                          output=f"{agg['local']} local and {agg['community']} community bans active")]
    if new is not None:
        level = State.WARN if warn_new and new >= warn_new else State.OK
        checks.append(CheckResult("crowdsec_new_bans", NEW_BANS_SERVICE, value=float(new), unit="", state=level,
                                  output=f"{new} new local bans since the last read"
                                  + (f" (warning from {warn_new})" if level == State.WARN else "")))
    return {"ok": True, "state": state, "metrics": logic.metrics(agg, new, tracking["new_total"]),
            "scenarios": agg["scenarios"], "message": "", "checks": checks}


async def record(session, src: CrowdSecSource, device: Device, res: dict, cfg: dict, now: datetime) -> list:
    """Store one read: metrics, scenario components, services, source state. Returns alert events."""
    from netsync.poller.pipeline import store_results

    ev = evaluate(src.state, res, now.timestamp(), int(cfg.get("warn_new_bans") or 0))
    comps = list(await session.scalars(select(Component).where(Component.device_id == device.id)))
    metrics = [MetricSample(k, v) for k, v in ev["metrics"].items()]
    if res.get("ms") is not None:
        metrics.append(MetricSample("response_ms", float(res["ms"])))
    if ev["scenarios"] is not None:
        by_key = {c.index: c for c in comps if c.kind == SCENARIO_KIND}
        for key, n in ev["scenarios"].items():
            c = by_key.get(key)
            if c is None:
                c = Component(device_id=device.id, kind=SCENARIO_KIND, index=key, name=key, module="crowdsec",
                              attrs={}, values={})
                session.add(c)
                by_key[key] = c
                comps.append(c)
            c.deleted, c.last_seen, c.values = False, now, {"bans": n}
        for key, c in by_key.items():
            if key not in ev["scenarios"] and not c.deleted:
                c.values = {"bans": 0}  # no active ban for this reason any more: the graph drops to 0
            if not c.deleted:
                metrics.append(MetricSample("bans", float(c.values.get("bans", 0)), SCENARIO_KIND, key))
        await session.flush()
    events = await store_results(session, device, metrics, ev["checks"], now, components=comps)
    src.state = ev["state"]
    src.last_run = now
    src.last_ms = res.get("ms")
    if ev["ok"]:
        src.last_ok, src.last_error = now, None
    else:
        src.last_error = ev["message"][:200]
    device.status = State.OK if ev["ok"] else State.CRIT
    device.status_reason = None if ev["ok"] else ev["message"][:200]
    device.last_polled = now
    return events


async def poll_source(source_id: int, cfg: dict) -> dict | None:
    """Read one source now (no DB connection held during the request) and store the result."""
    from netsync.alerting import dispatch
    from netsync.db import SessionLocal
    from netsync.probing.secrets import decrypt

    async with SessionLocal() as s:
        src = await s.get(CrowdSecSource, source_id)
        if not src:
            return None
        url, key = src.url, decrypt(src.key_enc).get("api_key", "")
    res = await fetch(url, key, float(cfg.get("timeout_s") or 10))
    async with SessionLocal() as s:
        src = await s.get(CrowdSecSource, source_id)
        device = await s.get(Device, src.device_id) if src else None
        if not src or not device:
            return None
        events = await record(s, src, device, res, cfg, datetime.now(UTC))
        await s.commit()
    await dispatch(events)
    return res


class CrowdSecService(BackgroundService):
    name = "crowdsec"

    async def run(self, stop: asyncio.Event) -> None:
        from netsync.db import SessionLocal
        from netsync.plugins.builtin.crowdsec import plugin
        from netsync.plugins.settings import cached_settings

        while not stop.is_set():
            try:
                enabled, cfg = await cached_settings(plugin)
                if enabled:
                    every = timedelta(seconds=int(cfg.get("interval_s") or 300))
                    now = datetime.now(UTC)
                    async with SessionLocal() as s:
                        due = [src.id for src in await s.scalars(
                            select(CrowdSecSource).where(CrowdSecSource.enabled.is_(True)))
                               if src.last_run is None or now - src.last_run >= every]
                    for sid in due:
                        try:
                            await poll_source(sid, cfg)
                        except Exception:
                            log.exception("crowdsec source %s failed", sid)
            except Exception:
                log.exception("crowdsec scheduler failed")
            try:
                await asyncio.wait_for(stop.wait(), timeout=TICK)
            except TimeoutError:
                pass
