"""DNS: resolve a record (system resolver or a given server, UDP with TCP fallback), query time, and
optionally check the answer against expected values (any / all must match)."""

import ipaddress
import time
from typing import Literal

import dns.asyncresolver
import dns.exception
import dns.resolver
import dns.reversename
from pydantic import Field, model_validator

from netsync.models import State
from netsync.probing.base import Checker, KindConfig, ProbeSpec, Result, ms_since, register, validate_dns_name

RecordType = Literal["A", "AAAA", "CNAME", "MX", "TXT", "NS", "SOA", "PTR", "CAA", "SRV"]


class DnsConfig(KindConfig):
    record_type: RecordType = "A"
    resolver: str | None = Field(None, max_length=45)  # IP of a DNS server; empty = system resolver
    resolver_port: int = Field(53, ge=1, le=65535)
    expected: list[str] = Field(default_factory=list, max_length=20)
    match: Literal["any", "all"] = "any"

    @model_validator(mode="after")
    def _check(self):
        if self.resolver:
            try:
                self.resolver = str(ipaddress.ip_address(self.resolver.strip()))
            except ValueError:
                raise ValueError("resolver must be an IP address") from None
        else:
            self.resolver = None
        cleaned = []
        for v in self.expected:
            v = " ".join(str(v).split())
            if len(v) > 512 or any(c in v for c in "\r\n\0"):
                raise ValueError("invalid expected value")
            if v:
                cleaned.append(v)
        self.expected = cleaned
        return self


def _norm(s: str) -> str:
    return s.strip().strip('"').rstrip(".").lower()


def record_texts(rtype: str, answer) -> list[str]:
    """Human readable values: A/AAAA address, names without the final dot, 'MX 10 mail.example.com' as
    '10 mail.example.com', TXT strings joined."""
    out = []
    for r in answer:
        if rtype == "TXT":
            out.append(b"".join(r.strings).decode("utf-8", "replace"))
        else:
            out.append(r.to_text().rstrip(".") if rtype in ("CNAME", "NS", "PTR") else r.to_text())
    return out


def answer_matches(values: list[str], expected: list[str], mode: str) -> bool:
    """A value matches an expected entry when the whole value matches, or (MX/SRV/CAA) its last field does."""
    norm = [_norm(v) for v in values]
    tails = [_norm(v.split()[-1]) for v in values if v.split()]

    def hit(e: str) -> bool:
        e = _norm(e)
        return e in norm or e in tails

    results = [hit(e) for e in expected]
    return all(results) if mode == "all" else any(results)


def query_name(target: str, rtype: str) -> str:
    if rtype == "PTR":
        try:
            return dns.reversename.from_address(target).to_text()
        except (dns.exception.SyntaxError, ValueError):
            pass
    return target


@register
class DnsChecker(Checker):
    kind = "dns"
    label = "DNS"
    Config = DnsConfig
    concurrency = 50
    target_label = "Name"

    def validate_target(self, target: str) -> str:
        t = (target or "").strip()
        try:
            return str(ipaddress.ip_address(t))  # PTR lookups take an address
        except ValueError:
            return validate_dns_name(t)

    async def check(self, spec: ProbeSpec) -> Result:
        cfg = DnsConfig(**spec.config)
        res = dns.asyncresolver.Resolver(configure=cfg.resolver is None)
        if cfg.resolver:
            res.nameservers = [cfg.resolver]
            res.port = cfg.resolver_port
        res.lifetime = res.timeout = float(spec.timeout_s)
        t0 = time.perf_counter()
        try:
            # UDP first; dnspython retries over TCP when the answer is truncated
            answer = await res.resolve(query_name(spec.target, cfg.record_type), cfg.record_type,
                                       raise_on_no_answer=True, search=False)
        except dns.resolver.NXDOMAIN:
            return Result(False, ms_since(t0, time.perf_counter()), State.CRIT, "NXDOMAIN")
        except dns.resolver.NoAnswer:
            return Result(False, ms_since(t0, time.perf_counter()), State.CRIT, f"no {cfg.record_type} records")
        except dns.resolver.NoNameservers:
            return Result(False, None, State.CRIT, "SERVFAIL")
        except (dns.exception.Timeout, dns.resolver.LifetimeTimeout):
            return Result(False, None, State.CRIT, "timeout")
        except Exception:  # noqa: BLE001 - every other resolver failure is "down"
            return Result(False, None, State.CRIT, "DNS query failed")
        ms = ms_since(t0, time.perf_counter())
        values = record_texts(cfg.record_type, answer)
        metrics = {"dns_query_ms": ms, "dns_records": float(len(values))}
        if cfg.expected and not answer_matches(values, cfg.expected, cfg.match):
            return Result(False, ms, State.CRIT, "answer mismatch", metrics)
        n = len(values)
        return Result(True, ms, State.OK, f"{n} {cfg.record_type} record{'s' if n != 1 else ''}", metrics)

