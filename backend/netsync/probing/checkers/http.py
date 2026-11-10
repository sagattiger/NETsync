"""HTTP(S): status codes, keyword present/absent, response time, TTFB; https also records the certificate."""

import asyncio
import json
import re
import time
from typing import Literal
from urllib.parse import urlsplit

import httpx
from pydantic import Field, model_validator

from netsync.models import State
from netsync.probing.base import (
    Checker,
    KindConfig,
    ProbeSpec,
    Result,
    error_message,
    ms_since,
    register,
    validate_host,
)
from netsync.probing.certs import cert_checks, cert_info

MAX_BODY = 1024 * 1024  # stop reading after 1 MB
MAX_REDIRECTS = 10
USER_AGENT = "NETsync-probe/1.0"
_CODES = re.compile(r"^\s*(\d{3})(?:\s*-\s*(\d{3}))?\s*$")


def parse_codes(spec: str) -> list[tuple[int, int]]:
    """'200-299,301' -> [(200, 299), (301, 301)]"""
    out = []
    for part in (spec or "").split(","):
        if not part.strip():
            continue
        m = _CODES.match(part)
        if not m:
            raise ValueError(f"invalid status code range {part.strip()!r}")
        lo, hi = int(m[1]), int(m[2] or m[1])
        if not (100 <= lo <= hi <= 599):
            raise ValueError(f"invalid status code range {part.strip()!r}")
        out.append((lo, hi))
    if not out:
        raise ValueError("accepted status codes are required")
    return out


def code_ok(code: int, ranges: list[tuple[int, int]]) -> bool:
    return any(lo <= code <= hi for lo, hi in ranges)


def validate_url(value: str) -> str:
    v = (value or "").strip()
    if not v or len(v) > 2048 or any(c.isspace() or ord(c) < 32 for c in v):
        raise ValueError("enter a valid http:// or https:// URL")
    u = urlsplit(v)
    if u.scheme not in ("http", "https"):
        raise ValueError("only http:// and https:// URLs are allowed")
    if u.username or u.password:
        raise ValueError("put credentials in the authentication fields, not in the URL")
    if not u.hostname:
        raise ValueError("the URL needs a host")
    validate_host(u.hostname)
    try:
        u.port  # noqa: B018 - raises on an invalid port
    except ValueError:
        raise ValueError("invalid port in URL") from None
    return v


class HttpConfig(KindConfig):
    method: Literal["GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"] = "GET"
    body: str | None = Field(None, max_length=65536)
    body_type: Literal["raw", "json", "form"] = "raw"
    body_secret: bool = False  # keep the body encrypted (it then lives in secrets["body"])
    accepted_codes: str = Field("200-299", max_length=200)
    follow_redirects: bool = True
    max_redirects: int = Field(MAX_REDIRECTS, ge=0, le=MAX_REDIRECTS)
    ignore_tls: bool = False
    auth: Literal["none", "basic", "bearer", "header"] = "none"
    auth_user: str | None = Field(None, max_length=256)
    auth_header_name: str | None = Field(None, max_length=128, pattern=r"^[A-Za-z0-9!#$%&'*+.^_`|~-]+$")
    keyword: str | None = Field(None, max_length=1024)
    keyword_absent: bool = False  # up when the keyword is NOT in the body
    keyword_case_insensitive: bool = False
    warn_days: int | None = Field(None, ge=0, le=3650)
    crit_days: int | None = Field(None, ge=0, le=3650)

    @model_validator(mode="after")
    def _check(self):
        parse_codes(self.accepted_codes)
        self.keyword = self.keyword or None
        if self.body and self.body_type == "json" and not self.body_secret:
            try:
                json.loads(self.body)
            except ValueError:
                raise ValueError("body is not valid JSON") from None
        if self.auth == "header" and not self.auth_header_name:
            raise ValueError("enter the authentication header name")
        if self.body_secret:
            self.body = None  # the body itself is a secret
        return self


def _root_cause(e: BaseException) -> BaseException:
    seen = set()
    while (e.__cause__ or e.__context__) and id(e) not in seen:
        seen.add(id(e))
        e = e.__cause__ or e.__context__
    return e


def http_error(e: BaseException) -> str:
    if isinstance(e, httpx.TooManyRedirects):
        return "too many redirects"
    if isinstance(e, httpx.TimeoutException | asyncio.TimeoutError | TimeoutError):
        return "timeout"
    root = _root_cause(e)
    if "CERTIFICATE_VERIFY_FAILED" in str(root) or "certificate verify failed" in str(e):
        return "TLS certificate invalid"
    if isinstance(e, httpx.RemoteProtocolError):
        return "invalid HTTP response"
    return error_message(root)


def build_request(cfg: HttpConfig, secrets: dict) -> tuple[dict, httpx.BasicAuth | None, bytes | None]:
    headers = {str(k): str(v) for k, v in (secrets.get("headers") or {}).items()}
    auth = None
    if cfg.auth == "basic":
        auth = httpx.BasicAuth(cfg.auth_user or "", secrets.get("password") or "")
    elif cfg.auth == "bearer" and secrets.get("token"):
        headers["Authorization"] = f"Bearer {secrets['token']}"
    elif cfg.auth == "header" and cfg.auth_header_name:
        headers[cfg.auth_header_name] = secrets.get("header_value") or ""
    body = secrets.get("body") if cfg.body_secret else cfg.body
    lower = {k.lower() for k in headers}
    if body and "content-type" not in lower:
        headers["Content-Type"] = {"json": "application/json", "form": "application/x-www-form-urlencoded"}.get(
            cfg.body_type, "text/plain; charset=utf-8")
    return headers, auth, body.encode() if body else None


async def fetch(spec: ProbeSpec, cfg: HttpConfig, transport: httpx.AsyncBaseTransport | None = None) -> tuple[Result, bytes]:
    """One request. Returns the result plus the (capped) body for subclasses such as json."""
    headers, auth, content = build_request(cfg, spec.secrets)
    async with httpx.AsyncClient(verify=not cfg.ignore_tls, follow_redirects=cfg.follow_redirects,
                                 max_redirects=cfg.max_redirects, timeout=httpx.Timeout(spec.timeout_s),
                                 headers={"User-Agent": USER_AGENT}, transport=transport) as client:
        t0 = time.perf_counter()
        async with client.stream(cfg.method, spec.target, headers=headers, auth=auth, content=content) as resp:
            ttfb = ms_since(t0, time.perf_counter())
            info = None
            if resp.url.scheme == "https":
                stream = resp.extensions.get("network_stream")
                sslobj = stream.get_extra_info("ssl_object") if stream is not None else None
                der = sslobj.getpeercert(binary_form=True) if sslobj else None
                if der:
                    info = cert_info(der, resp.url.host, None if cfg.ignore_tls else True, sslobj.version())
            body = b""
            if cfg.method != "HEAD":
                async for chunk in resp.aiter_bytes():
                    body += chunk
                    if len(body) >= MAX_BODY:
                        body = body[:MAX_BODY]
                        break
            total = ms_since(t0, time.perf_counter())
            code = resp.status_code
            encoding = resp.encoding or "utf-8"

    metrics = {"response_ms": total, "ttfb_ms": ttfb, "status_code": float(code), "body_bytes": float(len(body))}
    res = Result(True, total, State.OK, f"HTTP {code}", metrics)
    if info:
        res.cert = info
        metrics["tls_days_left"] = info["days_left"]
        res.checks += cert_checks(info, cfg.warn_days, cfg.crit_days)
    if not code_ok(code, parse_codes(cfg.accepted_codes)):
        res.up, res.state = False, State.CRIT
        return res, body
    if cfg.keyword:
        text = body.decode(encoding, "replace")
        found = cfg.keyword.casefold() in text.casefold() if cfg.keyword_case_insensitive else cfg.keyword in text
        if found == cfg.keyword_absent:
            res.up, res.state = False, State.CRIT
            res.message = "keyword found" if cfg.keyword_absent else "keyword not found"
        else:
            res.message = f"HTTP {code}, keyword {'absent' if cfg.keyword_absent else 'found'}"
    return res, body


@register
class HttpChecker(Checker):
    kind = "http"
    label = "HTTP(S)"
    Config = HttpConfig
    secret_fields = ("password", "token", "header_value", "headers", "body")
    concurrency = 50
    target_label = "URL"
    transport: httpx.AsyncBaseTransport | None = None  # tests inject httpx.MockTransport

    def validate_target(self, target: str) -> str:
        return validate_url(target)

    async def check(self, spec: ProbeSpec) -> Result:
        cfg = HttpConfig(**spec.config)
        try:
            res, _ = await asyncio.wait_for(fetch(spec, cfg, self.transport), spec.timeout_s + 2)
            return res
        except Exception as e:
            return Result(False, None, State.CRIT, http_error(e))
