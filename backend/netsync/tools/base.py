"""Tool definitions for the tool hub (MCP).

A tool is a function an AI (the built-in chat, an MCP client such as Claude Desktop, n8n, another plugin)
can call. Plugins contribute tools: in-process plugins via ``Plugin.tools``, container plugins through their
manifest (docs/PLUGIN-PROTOCOL.md). Every call goes through the hub, which applies the policy (off / auto /
needs approval), validates arguments, scopes device access and writes the audit log.
"""

from __future__ import annotations

import fnmatch
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, Literal

Risk = Literal["read", "write"]
Mode = Literal["auto", "approve", "off"]
NAME = re.compile(r"^[a-z][a-z0-9_]{0,30}__[a-z][a-z0-9_]{0,62}$")  # "<plugin>__<tool>", MCP/Claude safe


class ToolError(Exception):
    """A problem the caller should see (bad arguments, not found, not allowed)."""


@dataclass
class Actor:
    """Who is calling. ``user`` is set for logged-in users: their device groups limit what tools may read."""

    kind: Literal["user", "token", "plugin", "system"]
    name: str
    user: Any = None  # netsync.models.User
    tools: list[str] = field(default_factory=lambda: ["*"])  # name patterns this actor may use
    write: bool = False  # may it request write tools at all

    @property
    def label(self) -> str:
        return f"{self.kind}:{self.name}"

    def may_use(self, tool: str) -> bool:
        return any(fnmatch.fnmatchcase(tool, p) for p in self.tools)


@dataclass
class ToolContext:
    actor: Actor
    call_id: int | None = None
    origin: str = "ui"


Handler = Callable[[ToolContext, dict[str, Any]], Awaitable[Any]]


@dataclass
class Tool:
    name: str  # "<plugin>__<tool>"
    description: str
    input_schema: dict[str, Any]
    handler: Handler | None = None  # in-process tools; container tools are proxied by the hub
    risk: Risk = "read"
    title: str | None = None
    plugin: str = ""

    def __post_init__(self) -> None:
        if not NAME.match(self.name):
            raise ValueError(f"tool name {self.name!r} must look like '<plugin>__<tool>' (lowercase, digits, _)")

    @property
    def default_mode(self) -> Mode:
        return "auto" if self.risk == "read" else "approve"

    def describe(self) -> dict[str, Any]:
        """MCP tools/list entry."""
        return {
            "name": self.name,
            "title": self.title or self.name.split("__", 1)[1].replace("_", " ").capitalize(),
            "description": self.description,
            "inputSchema": self.input_schema,
            "annotations": {"readOnlyHint": self.risk == "read", "destructiveHint": self.risk == "write",
                            "openWorldHint": False},
        }


# --------------------------------------------------------------------------- arguments

SECRET_KEYS = re.compile(r"pass(word)?|secret|token|api[_-]?key|private[_-]?key|credential", re.IGNORECASE)
TYPES = {"string": str, "integer": int, "number": (int, float), "boolean": bool, "array": list, "object": dict}


def validate_args(schema: dict[str, Any], args: Any, path: str = "") -> dict[str, Any]:
    """Small JSON-schema check (type, required, enum, min/max, length, additionalProperties) with defaults."""
    if not isinstance(args, dict):
        raise ToolError("arguments must be an object")
    props: dict[str, dict] = schema.get("properties", {})
    out = dict(args)
    for key in schema.get("required", []):
        if key not in out or out[key] is None:
            raise ToolError(f"missing argument: {path}{key}")
    if schema.get("additionalProperties") is False:
        extra = set(out) - set(props)
        if extra:
            raise ToolError(f"unknown argument: {path}{sorted(extra)[0]}")
    for key, spec in props.items():
        if key not in out or out[key] is None:
            if "default" in spec:
                out[key] = spec["default"]
            continue
        value = out[key]
        typ = spec.get("type")
        if typ == "integer" and isinstance(value, float) and value.is_integer():
            value = out[key] = int(value)
        if typ == "number" and isinstance(value, str):
            try:
                value = out[key] = float(value)
            except ValueError:
                pass
        if typ == "integer" and isinstance(value, str) and value.lstrip("-").isdigit():
            value = out[key] = int(value)
        if typ and (not isinstance(value, TYPES[typ]) or (typ in ("integer", "number") and isinstance(value, bool))):
            raise ToolError(f"{path}{key} must be {typ}")
        if "enum" in spec and value not in spec["enum"]:
            raise ToolError(f"{path}{key} must be one of {', '.join(map(str, spec['enum']))}")
        if typ in ("integer", "number"):
            if "minimum" in spec and value < spec["minimum"]:
                raise ToolError(f"{path}{key} must be at least {spec['minimum']}")
            if "maximum" in spec and value > spec["maximum"]:
                raise ToolError(f"{path}{key} must be at most {spec['maximum']}")
        if typ == "string" and "maxLength" in spec and len(value) > spec["maxLength"]:
            raise ToolError(f"{path}{key} is longer than {spec['maxLength']} characters")
        if typ == "object" and spec.get("properties"):
            out[key] = validate_args(spec, value, f"{path}{key}.")
    return out


def redact(value: Any) -> Any:
    """Arguments as stored in the audit log: values of secret-looking keys are hidden."""
    if isinstance(value, dict):
        return {k: ("********" if SECRET_KEYS.search(str(k)) else redact(v)) for k, v in value.items()}
    if isinstance(value, list):
        return [redact(v) for v in value]
    return value


def schema(properties: dict[str, dict], required: list[str] | None = None) -> dict[str, Any]:
    return {"type": "object", "properties": properties, "required": required or [], "additionalProperties": False}
