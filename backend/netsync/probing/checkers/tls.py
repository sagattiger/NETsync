"""TLS certificate monitoring: days left, issuer, SANs, hostname match, chain validity, TLS version, key.

Optional STARTTLS for smtp, imap, pop3 and ftp. ``tls_handshake`` is shared with the tcp kind."""

import asyncio
import ssl
import time
from typing import Literal

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
from netsync.probing.certs import cert_checks, cert_info, expiry_message

HOSTNAME_MISMATCH = 62  # X509_V_ERR_HOSTNAME_MISMATCH

# Tests point this at their own CA.
CAFILE: str | None = None


class StartTlsError(Exception):
    pass


async def _line(reader, timeout: float) -> str:
    return (await asyncio.wait_for(reader.readline(), timeout)).decode("utf-8", "replace")


async def _starttls(proto: str, reader, writer, timeout: float) -> None:
    """Plain-text dialog up to the point where the TLS handshake starts."""
    async def expect(prefix: str, multiline_smtp: bool = False) -> None:
        while True:
            line = await _line(reader, timeout)
            if not line:
                raise StartTlsError("connection closed during STARTTLS")
            if multiline_smtp and len(line) > 3 and line[3] == "-":
                continue
            if not line.startswith(prefix):
                raise StartTlsError("STARTTLS not supported")
            return

    async def send(cmd: str) -> None:
        writer.write(cmd.encode() + b"\r\n")
        await writer.drain()

    if proto == "smtp":
        await expect("220", True)
        await send("EHLO netsync.local")
        await expect("250", True)
        await send("STARTTLS")
        await expect("220", True)
    elif proto == "imap":
        await expect("* OK")
        await send("a1 STARTTLS")
        while True:
            line = await _line(reader, timeout)
            if line.startswith("a1 "):
                if not line.startswith("a1 OK"):
                    raise StartTlsError("STARTTLS not supported")
                break
            if not line:
                raise StartTlsError("connection closed during STARTTLS")
    elif proto == "pop3":
        await expect("+OK")
        await send("STLS")
        await expect("+OK")
    elif proto == "ftp":
        await expect("220", True)
        await send("AUTH TLS")
        await expect("234", True)


def _context(verify: bool) -> ssl.SSLContext:
    ctx = ssl.create_default_context(cafile=CAFILE)
    if not verify:
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
    return ctx


async def _connect(host: str, port: int, sni: str, starttls: str | None, timeout: float, verify: bool):
    t0 = time.perf_counter()
    if starttls:
        reader, writer = await asyncio.wait_for(asyncio.open_connection(host, port), timeout)
        try:
            await _starttls(starttls, reader, writer, timeout)
            await asyncio.wait_for(writer.start_tls(_context(verify), server_hostname=sni), timeout)
        except BaseException:
            writer.close()
            raise
    else:
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(host, port, ssl=_context(verify), server_hostname=sni), timeout)
    return reader, writer, ms_since(t0, time.perf_counter())


async def tls_handshake(host: str, port: int, sni: str | None, timeout: float, starttls: str | None = None):
    """Handshake verifying against the system CAs; on a verification error, handshake again without verifying
    so the certificate can still be inspected. Returns (reader, writer, handshake_ms, chain_valid).
    A hostname-only failure keeps chain_valid True (cert_info reports the mismatch separately)."""
    sni = sni or host
    try:
        r, w, ms = await _connect(host, port, sni, starttls, timeout, verify=True)
        return r, w, ms, True
    except ssl.SSLCertVerificationError as e:
        hostname_only = getattr(e, "verify_code", None) == HOSTNAME_MISMATCH
    r, w, ms = await _connect(host, port, sni, starttls, timeout, verify=False)
    return r, w, ms, hostname_only


def peer_cert(writer, sni: str, chain_valid: bool | None) -> dict | None:
    sslobj = writer.get_extra_info("ssl_object")
    der = sslobj.getpeercert(binary_form=True) if sslobj else None
    return cert_info(der, sni, chain_valid, sslobj.version()) if der else None


async def close(writer) -> None:
    writer.close()
    try:
        await asyncio.wait_for(writer.wait_closed(), 2)
    except (TimeoutError, OSError, ssl.SSLError):
        pass


class TlsConfig(KindConfig):
    sni: str | None = Field(None, max_length=253)
    starttls: Literal["smtp", "imap", "pop3", "ftp"] | None = None
    warn_days: int | None = Field(None, ge=0, le=3650)
    crit_days: int | None = Field(None, ge=0, le=3650)

    @model_validator(mode="after")
    def _check(self):
        self.sni = validate_host(self.sni) if self.sni else None
        return self


def tls_error(e: BaseException) -> str:
    if isinstance(e, StartTlsError):
        return str(e)
    return error_message(e)


@register
class TlsChecker(Checker):
    kind = "tls"
    label = "TLS certificate"
    Config = TlsConfig
    needs_port = True
    default_port = 443
    concurrency = 30

    async def check(self, spec: ProbeSpec) -> Result:
        cfg = TlsConfig(**spec.config)
        sni = cfg.sni or spec.target
        writer = None
        try:
            _, writer, ms, chain_ok = await tls_handshake(spec.target, spec.port, sni, spec.timeout_s, cfg.starttls)
            info = peer_cert(writer, sni, chain_ok)
        except Exception as e:
            return Result(False, None, State.CRIT, tls_error(e))
        finally:
            if writer is not None:
                await close(writer)
        if not info:
            return Result(False, ms, State.CRIT, "no certificate presented")
        checks = cert_checks(info, cfg.warn_days, cfg.crit_days)
        metrics = {"tls_days_left": info["days_left"], "handshake_ms": ms}
        res = Result(True, ms, State.OK, expiry_message(info), metrics, checks, info)
        if info["days_left"] < 0:
            res.up, res.state, res.message = False, State.CRIT, "certificate expired"
        elif info["chain_valid"] is False:
            res.up, res.state, res.message = False, State.CRIT, "certificate untrusted"
        elif info["hostname_match"] is False:
            res.up, res.state, res.message = False, State.CRIT, "certificate hostname mismatch"
        return res

