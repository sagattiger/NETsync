"""NETsync plugin installer: the only NETsync container with access to Docker.

The API asks it to build and run store plugins; it applies the same locked-down settings to every plugin no
matter what it is asked: no privileges, no capabilities, no host folders, memory and process limits, one named
volume for /data, on the NETsync network only. Ports are published only when the catalog declares them (TCP,
above 1024, at most 3), e.g. the SSH bastion's 2222.

Plugin sources are GitHub repositories, downloaded as a tarball (no git needed) and built with their Dockerfile.

Auth: Bearer HMAC-SHA256(NETSYNC_SECRET_KEY, "netsync-installer"), which the API computes the same way.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import io
import logging
import os
import re
import socket
import tarfile
import time
import uuid
from typing import Any

import docker
import httpx
from docker.errors import APIError, BuildError, ImageNotFound, NotFound
from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel, Field

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("netsync.installer")

NAME = re.compile(r"^[a-z][a-z0-9_]{1,30}$")
REPO = re.compile(r"^[A-Za-z0-9_.-]{1,100}/[A-Za-z0-9_.-]{1,100}$")
REF = re.compile(r"^[A-Za-z0-9_./-]{1,100}$")
REL_PATH = re.compile(r"^(?!/)(?!.*\.\.)[A-Za-z0-9_./-]{0,200}$")
ENV_KEY = re.compile(r"^NETSYNC_[A-Z0-9_]{1,60}$")
VERSION = re.compile(r"^[0-9A-Za-z.+-]{1,40}$")
MAX_MEMORY_MB = 1024
MAX_SOURCE_BYTES = 200 * 1024 * 1024
PREFIX = "netsync-plugin-"
LABEL = "netsync.plugin"

app = FastAPI(title="NETsync installer", docs_url=None, redoc_url=None, openapi_url=None)
jobs: dict[str, dict[str, Any]] = {}
_docker: docker.DockerClient | None = None


def client() -> docker.DockerClient:
    global _docker
    if _docker is None:
        _docker = docker.from_env()
    return _docker


def token() -> str:
    key = os.environ.get("NETSYNC_SECRET_KEY", "")
    return hmac.new(key.encode(), b"netsync-installer", hashlib.sha256).hexdigest() if key else ""


def check(request: Request) -> None:
    scheme, _, value = request.headers.get("authorization", "").partition(" ")
    want = token()
    if not want or scheme.lower() != "bearer" or not hmac.compare_digest(value.strip(), want):
        raise HTTPException(401, "bad token")


def me():
    """This container: its network and DNS servers are given to the plugins."""
    return client().containers.get(socket.gethostname())


def network_and_dns() -> tuple[str, list[str]]:
    c = me()
    nets = list((c.attrs.get("NetworkSettings") or {}).get("Networks") or {})
    if not nets:
        raise RuntimeError("the installer is not on a Docker network")
    return nets[0], list((c.attrs.get("HostConfig") or {}).get("Dns") or [])


class Source(BaseModel):
    repo: str
    ref: str = "main"
    context: str = ""
    dockerfile: str = "Dockerfile"


class Port(BaseModel):
    container: int
    host: int


class InstallIn(BaseModel):
    name: str
    version: str
    source: Source
    env: dict[str, str] = Field(default_factory=dict)
    memory_mb: int = 256
    ports: list[Port] = Field(default_factory=list)


def validate(body: InstallIn) -> None:
    s = body.source
    if not NAME.match(body.name) or not VERSION.match(body.version):
        raise HTTPException(400, "invalid name or version")
    if not REPO.match(s.repo) or not REF.match(s.ref) or not REL_PATH.match(s.context) or not REL_PATH.match(s.dockerfile):
        raise HTTPException(400, "invalid source")
    for k in body.env:
        if not ENV_KEY.match(k):
            raise HTTPException(400, f"environment variable {k} not allowed (NETSYNC_* only)")
    if not 32 <= body.memory_mb <= MAX_MEMORY_MB:
        raise HTTPException(400, f"memory must be 32-{MAX_MEMORY_MB} MB")
    if len(body.ports) > 3 or any(not (1024 < p.container < 65536 and 1024 < p.host < 65536) for p in body.ports):
        raise HTTPException(400, "ports must be TCP ports above 1024, at most 3")


def context_tar(raw: bytes, context: str) -> io.BytesIO:
    """The context folder of a GitHub tarball, re-packed with paths relative to it."""
    out = io.BytesIO()
    prefix = context.strip("/")
    with tarfile.open(fileobj=io.BytesIO(raw), mode="r:gz") as src, tarfile.open(fileobj=out, mode="w") as dst:
        for m in src.getmembers():
            parts = m.name.split("/", 1)  # first part is "<repo>-<ref>"
            rel = parts[1] if len(parts) > 1 else ""
            if prefix:
                if rel != prefix and not rel.startswith(prefix + "/"):
                    continue
                rel = rel[len(prefix):].lstrip("/")
            if not rel or m.issym() or m.islnk() or m.isdev():
                continue
            m.name = rel
            dst.addfile(m, src.extractfile(m) if m.isfile() else None)
    out.seek(0)
    return out


def _log(job: dict, line: str) -> None:
    job["log"].append(f"{time.strftime('%H:%M:%S')} {line}")
    del job["log"][:-400]


def install(job: dict, body: InstallIn) -> None:
    s, name = body.source, body.name
    url = f"https://codeload.github.com/{s.repo}/tar.gz/{s.ref}"
    _log(job, f"Downloading {s.repo}@{s.ref}")
    with httpx.Client(timeout=120, follow_redirects=True) as h:
        r = h.get(url)
        r.raise_for_status()
        if len(r.content) > MAX_SOURCE_BYTES:
            raise RuntimeError("source is too large")
    ctx = context_tar(r.content, s.context)
    image = f"{PREFIX}{name}:{body.version}"
    _log(job, f"Building {image}")
    try:
        for chunk in client().api.build(fileobj=ctx, custom_context=True, dockerfile=s.dockerfile, tag=image,
                                        rm=True, forcerm=True, pull=True, decode=True,
                                        labels={LABEL: name, "netsync.version": body.version}):
            if "stream" in chunk and chunk["stream"].strip():
                _log(job, chunk["stream"].rstrip())
            if "error" in chunk:
                raise RuntimeError(chunk["error"])
    except BuildError as e:
        raise RuntimeError(f"build failed: {e}") from e
    network, dns = network_and_dns()
    cname = PREFIX + name
    with _suppress_notfound():
        old = client().containers.get(cname)
        _log(job, "Replacing the running container")
        old.remove(force=True)
    _log(job, f"Starting {cname}")
    client().containers.run(
        image, name=cname, detach=True, environment=body.env, network=network, dns=dns or None,
        ports={f"{p.container}/tcp": p.host for p in body.ports} or None,
        restart_policy={"Name": "unless-stopped"}, mem_limit=f"{body.memory_mb}m", pids_limit=256,
        cap_drop=["ALL"], security_opt=["no-new-privileges:true"], privileged=False,
        volumes={f"{PREFIX}{name}-data": {"bind": "/data", "mode": "rw"}},
        labels={LABEL: name, "netsync.version": body.version}, log_config={"Type": "json-file",
                                                                         "Config": {"max-size": "10m", "max-file": "3"}})
    _prune_images(name, image)
    _log(job, "Done")


def _prune_images(name: str, keep: str) -> None:
    for img in client().images.list(filters={"label": f"{LABEL}={name}"}):
        if keep not in img.tags:
            with _suppress_notfound():
                client().images.remove(img.id, force=False)


class _suppress_notfound:
    def __enter__(self):
        return self

    def __exit__(self, typ, exc, tb):
        return typ is not None and issubclass(typ, (NotFound, ImageNotFound, APIError))


async def run_job(job: dict, body: InstallIn) -> None:
    try:
        await asyncio.to_thread(install, job, body)
        job["status"] = "done"
    except Exception as e:  # noqa: BLE001 - reported in the job
        log.exception("install of %s failed", body.name)
        _log(job, f"Error: {e}")
        job["status"], job["error"] = "error", str(e)[:1000]
    job["finished"] = time.time()


@app.get("/health")
async def health():
    return {"ok": True}


@app.post("/install")
async def install_plugin(body: InstallIn, request: Request):
    check(request)
    validate(body)
    if any(j["name"] == body.name and j["status"] == "running" for j in jobs.values()):
        raise HTTPException(409, "already installing")
    job = {"id": uuid.uuid4().hex[:12], "name": body.name, "version": body.version, "status": "running",
           "log": [], "error": None, "started": time.time(), "finished": None}
    jobs[job["id"]] = job
    for old in sorted(jobs.values(), key=lambda j: j["started"])[:-50]:
        jobs.pop(old["id"], None)
    asyncio.get_running_loop().create_task(run_job(job, body))
    return job


@app.get("/jobs/{job_id}")
async def get_job(job_id: str, request: Request):
    check(request)
    if job_id not in jobs:
        raise HTTPException(404, "job not found")
    return jobs[job_id]


def describe(c) -> dict:
    return {"name": c.labels.get(LABEL), "version": c.labels.get("netsync.version"), "container": c.name,
            "status": c.status, "started": (c.attrs.get("State") or {}).get("StartedAt")}


@app.get("/plugins")
async def plugins(request: Request):
    check(request)
    cs = await asyncio.to_thread(client().containers.list, all=True, filters={"label": LABEL})
    return [describe(c) for c in cs if (c.name or "").startswith(PREFIX)]


def _container(name: str):
    if not NAME.match(name):
        raise HTTPException(400, "invalid name")
    try:
        return client().containers.get(PREFIX + name)
    except NotFound as e:
        raise HTTPException(404, "not installed") from e


@app.post("/plugins/{name}/restart")
async def restart(name: str, request: Request):
    check(request)
    await asyncio.to_thread(_container(name).restart, timeout=10)
    return {"ok": True}


@app.get("/plugins/{name}/logs")
async def logs(name: str, request: Request, tail: int = 200):
    check(request)
    text = await asyncio.to_thread(_container(name).logs, tail=max(1, min(tail, 2000)))
    return {"logs": text.decode(errors="replace")}


@app.delete("/plugins/{name}")
async def remove(name: str, request: Request, keep_data: bool = True):
    check(request)

    def go():
        with _suppress_notfound():
            _container(name).remove(force=True)
        if not keep_data:
            with _suppress_notfound():
                client().volumes.get(f"{PREFIX}{name}-data").remove(force=True)
        _prune_images(name, keep="")

    await asyncio.to_thread(go)
    return {"ok": True}
