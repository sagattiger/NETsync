"""Common interface of all probe kinds.

A checker validates its own settings (``validate``) and performs one check (``check``). Everything else
(retries, upside-down, heartbeats, metrics, services, alerts) is the runner's job, so a new kind is one
file in netsync/probing/checkers/ registered with ``@register``.
"""

import ipaddress
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, ClassVar

from pydantic import BaseModel, ConfigDict

from netsync.models import State
from netsync.plugins.base import CheckResult


@dataclass
class Result:
    up: bool
    response_ms: float | None = None
    state: int = State.OK  # OK or WARN when up; the runner decides CRIT/pending when down
    message: str = ""  # short, generic reason: "HTTP 503", "timeout", "keyword not found"
    metrics: dict[str, float] = field(default_factory=dict)
    checks: list[CheckResult] = field(default_factory=list)  # extra services, e.g. Certificate expiry
    cert: dict | None = None  # certificate details (https/tls)

    def as_dict(self) -> dict:
        return {
            "up": self.up, "response_ms": self.response_ms, "state": State(self.state).name, "message": self.message,
            "metrics": self.metrics, "cert": self.cert,
            "checks": [{"name": c.name, "state": State(c.state).name if c.state is not None else None,
                        "value": c.value, "output": c.output} for c in self.checks],
        }


@dataclass
class ProbeSpec:
    """What a checker needs. Secrets are already decrypted; never log them."""

    kind: str
    target: str
    port: int | None = None
    timeout_s: float = 10
    count: int = 5
    interval_s: int = 60
    config: dict = field(default_factory=dict)
    secrets: dict = field(default_factory=dict)
    last_push_at: datetime | None = None  # push kind
    probe_id: int | None = None


class KindConfig(BaseModel):
    """Base for each kind's settings model: unknown keys are rejected."""

    model_config = ConfigDict(extra="forbid")


class Checker:
    kind: ClassVar[str]
    label: ClassVar[str]
    Config: ClassVar[type[KindConfig]] = KindConfig
    secret_fields: ClassVar[tuple[str, ...]] = ()
    needs_port: ClassVar[bool] = False
    default_port: ClassVar[int | None] = None
    concurrency: ClassVar[int] = 50
    target_label: ClassVar[str] = "Host"

    def validate(self, target: str, port: int | None, config: dict) -> tuple[str, int | None, dict]:
        """Normalise and validate. Raises ValueError with a user-facing message."""
        cfg = self.Config(**(config or {})).model_dump()
        target = self.validate_target(target)
        if self.needs_port:
            port = port or self.default_port
            if port is None:
                raise ValueError("port is required")
            validate_port(port)
        else:
            port = None
        return target, port, cfg

    def validate_target(self, target: str) -> str:
        return validate_host(target)

    def validate_secrets(self, secrets: dict) -> dict:
        """Only this kind's secret fields; strings without line breaks (except a body), headers as a dict."""
        out = {}
        for k, v in (secrets or {}).items():
            if k not in self.secret_fields:
                raise ValueError(f"unknown secret {k!r}")
            if v is None or v == "":
                out[k] = v
            elif k == "headers":
                if not isinstance(v, dict) or len(v) > 30:
                    raise ValueError("headers must be an object with at most 30 entries")
                for name, value in v.items():
                    if (not HEADER_NAME.match(str(name)) or not isinstance(value, str) or len(value) > 8192
                            or any(c in value for c in BAD_CHARS)):
                        raise ValueError(f"invalid header {name!r}")
                out[k] = v
            elif not isinstance(v, str) or len(v) > 65536 or (k != "body" and any(c in v for c in BAD_CHARS)):
                raise ValueError(f"invalid value for {k}")
            else:
                out[k] = v
        return out

    async def check(self, spec: ProbeSpec) -> Result:  # pragma: no cover - interface
        raise NotImplementedError


REGISTRY: dict[str, Checker] = {}


def register(cls: type[Checker]) -> type[Checker]:
    REGISTRY[cls.kind] = cls()
    return cls


def get_checker(kind: str) -> Checker:
    try:
        return REGISTRY[kind]
    except KeyError:
        raise ValueError(f"unknown probe kind {kind!r}") from None


# --------------------------------------------------------------------------- validation helpers

BAD_CHARS = "\r\n\x00"  # header injection
HEADER_NAME = re.compile(r"^[A-Za-z0-9!#$%&'*+.^_`|~-]{1,128}$")
_LABEL = re.compile(r"^(?!-)[A-Za-z0-9_-]{1,63}(?<!-)$")


def validate_host(value: str) -> str:
    """An IPv4/IPv6 address or a hostname/FQDN. Nothing else: no URLs, ports, spaces or shell characters."""
    v = (value or "").strip()
    if not v or len(v) > 253:
        raise ValueError("target must be an IP address or hostname")
    try:
        return str(ipaddress.ip_address(v))
    except ValueError:
        pass
    host = v.removesuffix(".")
    labels = host.split(".")
    if not all(_LABEL.match(label) and "_" not in label for label in labels):
        raise ValueError("target must be an IP address or hostname (letters, digits, '-' and '.')")
    if labels[-1].isdigit():
        raise ValueError("invalid IP address")  # e.g. 999.1.1.1 or 10.1
    return host.lower()


def validate_dns_name(value: str) -> str:
    """Like a hostname but labels may contain '_' (SRV/TXT names like _sip._tcp.example.com)."""
    v = (value or "").strip().rstrip(".")
    if not v or len(v) > 253 or not all(_LABEL.match(label) for label in v.split(".")):
        raise ValueError("enter a valid DNS name")
    return v.lower()


def validate_port(port: Any) -> int:
    if not isinstance(port, int) or isinstance(port, bool) or not 1 <= port <= 65535:
        raise ValueError("port must be between 1 and 65535")
    return port


def ms_since(t0: float, t1: float) -> float:
    return round((t1 - t0) * 1000, 2)


def short(text: str, n: int = 200) -> str:
    text = " ".join(str(text).split())
    return text if len(text) <= n else text[: n - 1] + "…"


def error_message(e: BaseException) -> str:
    """A generic category for common network errors (never includes the target)."""
    import asyncio
    import socket
    import ssl

    if isinstance(e, asyncio.TimeoutError | TimeoutError):
        return "timeout"
    if isinstance(e, ConnectionRefusedError):
        return "connection refused"
    if isinstance(e, ConnectionResetError):
        return "connection reset"
    if isinstance(e, socket.gaierror):
        return "name resolution failed"
    if isinstance(e, ssl.SSLCertVerificationError):
        return "TLS certificate invalid"
    if isinstance(e, ssl.SSLError):
        return "TLS handshake failed"
    if isinstance(e, OSError) and e.errno is not None:
        import errno as _errno

        return {
            _errno.EHOSTUNREACH: "host unreachable", _errno.ENETUNREACH: "network unreachable",
            _errno.ECONNREFUSED: "connection refused", _errno.ETIMEDOUT: "timeout",
        }.get(e.errno, "connection failed")
    return "connection failed"
