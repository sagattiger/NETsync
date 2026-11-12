"""Minimal SDK for NETsync container plugins (docs/PLUGIN-PROTOCOL.md). Needs fastapi, uvicorn and httpx.

    from netsync_plugin import NetsyncPlugin

    plugin = NetsyncPlugin("hello", version="1.0.0", description="Example", permissions=["tools", "call:read"])

    @plugin.tool("greet", "Say hello", {"type": "object", "properties": {"name": {"type": "string"}}})
    async def greet(args, call):
        return {"text": f"Hello {args.get('name', 'world')}"}

    app = plugin.app()  # run with: uvicorn module:app --host 0.0.0.0 --port 8080

NETSYNC_PLUGIN_SECRET (shown once when the plugin is registered in NETsync) must be set in the environment;
NETSYNC_URL (e.g. http://api:8000) is needed only to call NETsync back.
"""

from __future__ import annotations

import hmac
import json
import os
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass
from typing import Any

import httpx
from fastapi import FastAPI, HTTPException, Request

Handler = Callable[[dict[str, Any], dict[str, Any]], Awaitable[Any]]


@dataclass
class _Tool:
    name: str
    description: str
    input_schema: dict[str, Any]
    risk: str
    handler: Handler


class NetsyncPlugin:
    def __init__(self, name: str, version: str = "0.1.0", description: str = "",
                 permissions: list[str] | None = None, secret: str | None = None, netsync_url: str | None = None):
        self.name, self.version, self.description = name, version, description
        self.permissions = permissions or ["tools"]
        self.secret = secret or os.environ.get("NETSYNC_PLUGIN_SECRET", "")
        self.netsync_url = (netsync_url or os.environ.get("NETSYNC_URL", "http://api:8000")).rstrip("/")
        self._tools: dict[str, _Tool] = {}

    # ------------------------------------------------------------------ tools offered to NETsync

    def tool(self, name: str, description: str, input_schema: dict[str, Any] | None = None, risk: str = "read"):
        """Register a tool. ``risk="write"`` tools run only after a person approves them in NETsync."""
        def wrap(fn: Handler) -> Handler:
            self._tools[name] = _Tool(name, description, input_schema or {"type": "object", "properties": {}}, risk, fn)
            return fn
        return wrap

    def manifest(self) -> dict[str, Any]:
        return {"name": self.name, "version": self.version, "description": self.description,
                "permissions": self.permissions,
                "tools": [{"name": t.name, "description": t.description, "input_schema": t.input_schema, "risk": t.risk}
                          for t in self._tools.values()]}

    def _check(self, request: Request) -> None:
        scheme, _, value = request.headers.get("authorization", "").partition(" ")
        if not self.secret or scheme.lower() != "bearer" or not hmac.compare_digest(value.strip(), self.secret):
            raise HTTPException(401, "bad secret")

    def app(self) -> FastAPI:
        api = FastAPI(title=f"NETsync plugin {self.name}", docs_url=None, redoc_url=None, openapi_url=None)

        @api.get("/health")
        async def health():
            return {"ok": True, "name": self.name, "version": self.version}

        @api.get("/manifest")
        async def manifest(request: Request):
            self._check(request)
            return self.manifest()

        @api.post("/tools/{name}")
        async def run(name: str, request: Request):
            self._check(request)
            tool = self._tools.get(name)
            if tool is None:
                raise HTTPException(404, f"unknown tool {name}")
            body = await request.json()
            try:
                return {"result": await tool.handler(body.get("arguments") or {}, body)}
            except Exception as e:  # noqa: BLE001 - reported to NETsync as the tool's error
                return {"error": f"{type(e).__name__}: {e}"}

        return api

    # ------------------------------------------------------------------ calling NETsync back

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.secret}"}

    async def call_tool(self, name: str, arguments: dict[str, Any] | None = None) -> Any:
        """Call another plugin's read-only tool, e.g. ``netsync__list_problems`` (needs the ``call:read`` permission)."""
        async with httpx.AsyncClient(timeout=60) as c:
            r = await c.post(f"{self.netsync_url}/api/plugin-api/tools/call", headers=self._headers(),
                             json={"name": name, "arguments": arguments or {}})
            r.raise_for_status()
            return r.json()

    async def events(self) -> AsyncIterator[dict[str, Any]]:
        """NETsync events as they happen (needs the ``events`` permission). Reconnect when it ends."""
        async with httpx.AsyncClient(timeout=httpx.Timeout(10, read=None)) as c, c.stream(
                "GET", f"{self.netsync_url}/api/plugin-api/events", headers=self._headers()) as r:
            r.raise_for_status()
            async for line in r.aiter_lines():
                if line.startswith("data: "):
                    yield json.loads(line[6:])
