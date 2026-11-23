"""Docker containers of a host, through an SNMP extend (no Docker API access from NETsync, no agent).

On the Docker host, root's cron runs ``agents/netsync-docker`` every minute; it writes ``docker ps -a`` and
``docker stats`` (selected fields only) to /var/lib/netsync/docker.txt, and snmpd serves that file with
``extend netsync-docker /bin/cat /var/lib/netsync/docker.txt``. NETsync walks the extend's output lines
(nsExtendOutLine: one varbind per line, so a long list never needs one huge SNMP packet). See docs/DOCKER.md.

Each container is a ``container`` component keyed by its name (IDs change when a container is recreated, names
don't). Per poll: state, health, CPU % and memory, and a "Container <name>" service:
  OK running (or health "starting"), or created and never started; WARN restarting, paused, or exited with code 0
  (stopped on purpose or a finished job); CRIT unhealthy, dead, or exited with another code.
"Docker data" turns WARN when the file is older than 5 minutes (the cron job stopped).
"""

from __future__ import annotations

import re
import time

from netsync.models import State
from netsync.plugins.base import CheckResult, ComponentSpec, DeviceContext, MetricSample, Module, PollResult
from netsync.snmp.client import text

EXTEND = "netsync-docker"
NS_EXTEND_OUT_LINE = "1.3.6.1.4.1.8072.1.3.4.1.2"  # nsExtendOutLine.<name as length-prefixed bytes>.<line>
KIND = "container"
STALE_AFTER = 300  # seconds

_HEADER = re.compile(r"^# netsync-docker (\d+) (\d+)\s*$")
_EXIT = re.compile(r"^Exited \((-?\d+)\)")
_UNITS = {"b": 1, "kb": 1e3, "mb": 1e6, "gb": 1e9, "tb": 1e12, "kib": 1024, "mib": 1024 ** 2, "gib": 1024 ** 3,
          "tib": 1024 ** 4}


def extend_index(name: str) -> str:
    return ".".join(str(b) for b in [len(name), *name.encode()])


def size_bytes(s: str) -> float | None:
    """'123.4MiB' -> bytes; '0B' -> 0; anything else None."""
    m = re.match(r"^\s*([\d.]+)\s*([A-Za-z]+)\s*$", s or "")
    if not m or m[2].lower() not in _UNITS:
        return None
    try:
        return float(m[1]) * _UNITS[m[2].lower()]
    except ValueError:
        return None


def pct(s: str) -> float | None:
    try:
        return float((s or "").strip().rstrip("%"))
    except ValueError:
        return None


def health(status: str) -> str | None:
    s = status or ""
    if "(unhealthy)" in s:
        return "unhealthy"
    if "(healthy)" in s:
        return "healthy"
    if "(health: starting)" in s:
        return "starting"
    return None


def parse(output: str) -> dict:
    """{"time": unix | None, "containers": {name: {...}}} from the extend output."""
    lines = (output or "").splitlines()
    at = None
    if lines and (m := _HEADER.match(lines[0])):
        at = int(m[2])
        lines = lines[1:]
    stats: dict[str, dict] = {}
    rows: list[list[str]] = []
    in_stats = False
    for line in lines:
        if line.strip() == "---":
            in_stats = True
            continue
        parts = line.split("\t")
        if in_stats:
            if len(parts) >= 3:
                used, _, limit = parts[2].partition("/")
                stats[parts[0].strip()] = {"cpu_pct": pct(parts[1]), "mem_bytes": size_bytes(used),
                                           "mem_limit": size_bytes(limit), "mem_pct": pct(parts[3]) if len(parts) > 3 else None}
        elif len(parts) >= 5 and parts[1].strip():
            rows.append(parts + [""] * (9 - len(parts)))
    out = {}
    for p in rows:
        cid, name, image, state, status, ports, project, service, coolify = (x.strip() for x in p[:9])
        exit_code = int(m[1]) if (m := _EXIT.match(status)) else None
        out[name] = {
            "id": cid[:12], "image": image, "state": state.lower(), "status": status, "health": health(status),
            "exit_code": exit_code, "ports": ports, "project": project or None, "service": service or None,
            "coolify": coolify or None, **(stats.get(cid) or stats.get(cid[:12]) or {}),
        }
    return {"time": at, "containers": out}


def container_state(c: dict) -> tuple[int, str]:
    """(state, output) of a container's service."""
    st, hl, code = c.get("state"), c.get("health"), c.get("exit_code")
    if st == "running":
        if hl == "unhealthy":
            return State.CRIT, f"running but unhealthy ({c.get('status')})"
        return State.OK, c.get("status") or "running"
    if st == "created":
        return State.OK, "created, never started"
    if st in ("restarting", "paused"):
        return State.WARN, c.get("status") or st
    if st == "exited" and code == 0:
        return State.WARN, f"stopped ({c.get('status')})"
    return State.CRIT, c.get("status") or st or "unknown"


async def read_output(snmp) -> str | None:
    """The extend's output, or None when this host has no netsync-docker extend."""
    try:
        rows = await snmp.walk(f"{NS_EXTEND_OUT_LINE}.{extend_index(EXTEND)}")
    except Exception:  # noqa: BLE001 - agents without NET-SNMP-EXTEND-MIB
        return None
    if not rows:
        return None
    return "\n".join(text(v) or "" for _, v in sorted(rows.items(), key=lambda kv: int(kv[0]) if kv[0].isdigit() else 0))


class DockerModule(Module):
    name = "docker"
    kinds = (KIND,)
    order = 50

    async def discover(self, ctx: DeviceContext):
        out = await read_output(ctx.snmp)
        if out is None:
            return []
        data = parse(out)
        return [ComponentSpec(KIND, name[:128], name, descr=c["image"][:255] or None,
                              attrs={"image": c["image"], "ports": c["ports"], "project": c["project"],
                                     "service": c["service"], "coolify": c["coolify"]})
                for name, c in data["containers"].items()]

    async def poll(self, ctx: DeviceContext):
        comps = ctx.components(KIND)
        if not comps:
            return PollResult()
        out = await read_output(ctx.snmp)
        result = PollResult()
        if out is None:
            result.checks.append(CheckResult("docker_data", "Docker data", state=State.CRIT,
                                             output="the netsync-docker SNMP extend did not answer"))
            return result
        data = parse(out)
        age = time.time() - data["time"] if data["time"] else None
        stale = age is None or age > STALE_AFTER
        result.checks.append(CheckResult(
            "docker_data", "Docker data", state=State.WARN if stale else State.OK,
            output=(f"container list is {int(age // 60)} min old: is the netsync-docker cron job running?"
                    if age is not None and stale else "no time in the container list (old script?)" if stale
                    else f"{len(data['containers'])} containers, listed {int(age)} s ago")))
        running = 0
        for comp in comps:
            c = data["containers"].get(comp.index)
            if c is None:
                continue  # removed: discovery drops the component after two misses
            running += c["state"] == "running"
            state, output = container_state(c)
            vals = {k: c.get(k) for k in ("id", "state", "status", "health", "exit_code", "ports", "cpu_pct",
                                          "mem_bytes", "mem_limit", "mem_pct")}
            result.values[(KIND, comp.index)] = vals
            for metric in ("cpu_pct", "mem_bytes", "mem_pct"):
                if c.get(metric) is not None:
                    result.metrics.append(MetricSample(metric, float(c[metric]), KIND, comp.index))
            result.metrics.append(MetricSample("running", 1.0 if c["state"] == "running" else 0.0, KIND, comp.index))
            result.checks.append(CheckResult("docker_container", f"Container {comp.name}", state=state, output=output,
                                             kind=KIND, index=comp.index))
        result.metrics.append(MetricSample("containers_running", float(running)))
        result.metrics.append(MetricSample("containers_total", float(len(data["containers"]))))
        return result
