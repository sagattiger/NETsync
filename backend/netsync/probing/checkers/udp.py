"""UDP: send a datagram (text or hex) and optionally expect a reply (substring, regex or hex).

Without an expected reply, "up" only means no ICMP port-unreachable / socket error arrived within the
wait - UDP has no handshake, so a silent drop looks the same as a listening service."""

import asyncio
import re
import time
from typing import Literal

from pydantic import Field, model_validator

from netsync.models import State
from netsync.probing.base import Checker, KindConfig, ProbeSpec, Result, error_message, ms_since, register

READ_LIMIT = 65535
SILENT_WAIT = 2.0  # seconds to wait for an ICMP error when no reply is expected


def _hex(s: str) -> bytes:
    cleaned = re.sub(r"[\s:]", "", s)
    if len(cleaned) % 2 or not re.fullmatch(r"[0-9a-fA-F]*", cleaned):
        raise ValueError("invalid hex")
    return bytes.fromhex(cleaned)


class UdpConfig(KindConfig):
    payload: str | None = Field(None, max_length=2048)
    payload_hex: bool = False
    expect: str | None = Field(None, max_length=512)
    expect_mode: Literal["substring", "regex", "hex"] = "substring"

    @model_validator(mode="after")
    def _check(self):
        self.payload = self.payload or None
        self.expect = self.expect or None
        if self.payload and self.payload_hex:
            try:
                _hex(self.payload)
            except ValueError:
                raise ValueError("payload is not valid hex") from None
        if self.expect and self.expect_mode == "regex":
            try:
                re.compile(self.expect)
            except re.error as e:
                raise ValueError(f"invalid regex: {e}") from None
        if self.expect and self.expect_mode == "hex":
            try:
                _hex(self.expect)
            except ValueError:
                raise ValueError("expected reply is not valid hex") from None
        return self

    def payload_bytes(self) -> bytes:
        if not self.payload:
            return b""
        return _hex(self.payload) if self.payload_hex else self.payload.replace("\\r", "\r").replace("\\n", "\n").encode()

    def matches(self, data: bytes) -> bool:
        if self.expect_mode == "hex":
            return _hex(self.expect) in data
        text = data.decode("utf-8", "replace")
        return bool(re.search(self.expect, text)) if self.expect_mode == "regex" else self.expect in text


class _Proto(asyncio.DatagramProtocol):
    def __init__(self):
        self.data: asyncio.Future = asyncio.get_running_loop().create_future()

    def datagram_received(self, data, addr):
        if not self.data.done():
            self.data.set_result(data)

    def error_received(self, exc):
        if not self.data.done():
            self.data.set_exception(exc)

    def connection_lost(self, exc):
        if exc and not self.data.done():
            self.data.set_exception(exc)


@register
class UdpChecker(Checker):
    kind = "udp"
    label = "UDP port"
    Config = UdpConfig
    needs_port = True
    concurrency = 50

    async def check(self, spec: ProbeSpec) -> Result:
        cfg = UdpConfig(**spec.config)
        loop = asyncio.get_running_loop()
        transport = None
        try:
            transport, proto = await asyncio.wait_for(
                loop.create_datagram_endpoint(_Proto, remote_addr=(spec.target, spec.port)), spec.timeout_s)
            t0 = time.perf_counter()
            transport.sendto(cfg.payload_bytes())
            wait = spec.timeout_s if cfg.expect else min(SILENT_WAIT, spec.timeout_s)
            try:
                data = await asyncio.wait_for(asyncio.shield(proto.data), wait)
            except TimeoutError:
                if cfg.expect:
                    return Result(False, None, State.CRIT, "no reply")
                return Result(True, None, State.OK, "sent, no error (no reply expected)")
            ms = ms_since(t0, time.perf_counter())
            if cfg.expect and not cfg.matches(data[:READ_LIMIT]):
                return Result(False, ms, State.CRIT, "unexpected reply", {"reply_ms": ms})
            return Result(True, ms, State.OK, "reply matched" if cfg.expect else "reply received", {"reply_ms": ms})
        except Exception as e:  # noqa: BLE001 - ICMP unreachable arrives as ConnectionRefusedError
            return Result(False, None, State.CRIT, "port unreachable" if isinstance(e, ConnectionRefusedError | ConnectionResetError)
                          else error_message(e))
        finally:
            if transport is not None:
                transport.close()
