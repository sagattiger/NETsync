"""TCP port: connect time, optional TLS handshake (records the certificate) and an optional banner check."""

import asyncio
import re
import time

from pydantic import Field, model_validator

from netsync.models import State
from netsync.probing.base import Checker, KindConfig, ProbeSpec, Result, error_message, ms_since, register
from netsync.probing.certs import cert_checks
from netsync.probing.checkers.tls import peer_cert, tls_handshake

READ_LIMIT = 4096


class TcpConfig(KindConfig):
    tls: bool = False
    ignore_tls: bool = False  # with tls: don't fail on an untrusted certificate
    send: str | None = Field(None, max_length=1024)  # sent after connecting; \r\n escapes allowed
    expect: str | None = Field(None, max_length=512)  # substring (or regex) expected in the first bytes
    expect_regex: bool = False
    warn_days: int | None = Field(None, ge=0, le=3650)
    crit_days: int | None = Field(None, ge=0, le=3650)

    @model_validator(mode="after")
    def _check(self):
        self.expect = self.expect or None
        self.send = self.send or None
        if self.expect and self.expect_regex:
            try:
                re.compile(self.expect)
            except re.error as e:
                raise ValueError(f"invalid regex: {e}") from None
        return self


def unescape(s: str) -> bytes:
    return s.replace("\\r", "\r").replace("\\n", "\n").replace("\\t", "\t").encode()


def matches(data: bytes, expect: str, regex: bool) -> bool:
    text = data.decode("utf-8", "replace")
    return bool(re.search(expect, text)) if regex else expect in text


@register
class TcpChecker(Checker):
    kind = "tcp"
    label = "TCP port"
    Config = TcpConfig
    needs_port = True
    concurrency = 100

    async def check(self, spec: ProbeSpec) -> Result:
        cfg = TcpConfig(**spec.config)
        writer = None
        try:
            t0 = time.perf_counter()
            if cfg.tls:
                reader, writer, connect_ms, chain_ok = await tls_handshake(spec.target, spec.port, spec.target,
                                                                           spec.timeout_s)
                if not chain_ok and not cfg.ignore_tls:
                    return Result(False, connect_ms, State.CRIT, "TLS certificate invalid")
            else:
                reader, writer = await asyncio.wait_for(asyncio.open_connection(spec.target, spec.port), spec.timeout_s)
                connect_ms = ms_since(t0, time.perf_counter())
            metrics = {"connect_ms": connect_ms}
            res = Result(True, connect_ms, State.OK, "connected", metrics)
            if cfg.tls:
                info = peer_cert(writer, spec.target, chain_ok if not cfg.ignore_tls else None)
                if info:
                    res.cert = info
                    metrics["tls_days_left"] = info["days_left"]
                    res.checks += cert_checks(info, cfg.warn_days, cfg.crit_days)
            if cfg.send:
                writer.write(unescape(cfg.send))
                await writer.drain()
            if cfg.expect:
                data = b""
                deadline = time.perf_counter() + spec.timeout_s
                while len(data) < READ_LIMIT and not matches(data, cfg.expect, cfg.expect_regex):
                    left = deadline - time.perf_counter()
                    if left <= 0:
                        break
                    try:
                        chunk = await asyncio.wait_for(reader.read(READ_LIMIT - len(data)), left)
                    except TimeoutError:
                        break
                    if not chunk:
                        break
                    data += chunk
                if not matches(data, cfg.expect, cfg.expect_regex):
                    return Result(False, connect_ms, State.CRIT, "unexpected response", metrics)
                res.message = "response matched"
            return res
        except Exception as e:
            return Result(False, None, State.CRIT, error_message(e))
        finally:
            if writer is not None:
                writer.close()
                try:
                    await asyncio.wait_for(writer.wait_closed(), 2)
                except Exception:
                    pass
