"""Certificate details and the "Certificate expiry" check, shared by tls, tcp (TLS switch) and https."""

import ipaddress
from datetime import UTC, datetime

from cryptography import x509
from cryptography.hazmat.primitives.asymmetric import dsa, ec, ed448, ed25519, rsa
from cryptography.x509.oid import NameOID

from netsync.models import State
from netsync.plugins.base import CheckResult

DEFAULT_WARN_DAYS = 21
DEFAULT_CRIT_DAYS = 7


def _name(name: x509.Name, oid=NameOID.COMMON_NAME) -> str | None:
    attrs = name.get_attributes_for_oid(oid)
    return str(attrs[0].value) if attrs else None


def _key(cert: x509.Certificate) -> tuple[str, int | None]:
    key = cert.public_key()
    if isinstance(key, rsa.RSAPublicKey):
        return "RSA", key.key_size
    if isinstance(key, ec.EllipticCurvePublicKey):
        return f"EC {key.curve.name}", key.key_size
    if isinstance(key, ed25519.Ed25519PublicKey):
        return "Ed25519", 256
    if isinstance(key, ed448.Ed448PublicKey):
        return "Ed448", 456
    if isinstance(key, dsa.DSAPublicKey):
        return "DSA", key.key_size
    return "unknown", None


def hostname_matches(hostname: str, dns_names: list[str], ips: list[str]) -> bool:
    host = hostname.lower().rstrip(".")
    try:
        ip = str(ipaddress.ip_address(host))
        return ip in ips
    except ValueError:
        pass
    for pattern in dns_names:
        p = pattern.lower().rstrip(".")
        if p == host:
            return True
        if p.startswith("*.") and "." in host:
            # a wildcard covers exactly one left-most label
            if host.split(".", 1)[1] == p[2:]:
                return True
    return False


def cert_info(der: bytes, hostname: str | None, chain_valid: bool | None, tls_version: str | None = None,
              now: datetime | None = None) -> dict:
    cert = x509.load_der_x509_certificate(der)
    now = now or datetime.now(UTC)
    not_after = cert.not_valid_after_utc
    try:
        san = cert.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
        dns_names = san.get_values_for_type(x509.DNSName)
        ips = [str(i) for i in san.get_values_for_type(x509.IPAddress)]
    except x509.ExtensionNotFound:
        dns_names, ips = [], []
    cn = _name(cert.subject)
    key_type, key_bits = _key(cert)
    names = dns_names or ([cn] if cn else [])
    return {
        "subject_cn": cn,
        "sans": (dns_names + ips)[:50],
        "issuer": _name(cert.issuer) or _name(cert.issuer, NameOID.ORGANIZATION_NAME),
        "issuer_org": _name(cert.issuer, NameOID.ORGANIZATION_NAME),
        "not_before": cert.not_valid_before_utc.isoformat(),
        "not_after": not_after.isoformat(),
        "days_left": round((not_after - now).total_seconds() / 86400, 1),
        "hostname_match": hostname_matches(hostname, names, ips) if hostname else None,
        "chain_valid": chain_valid,
        "tls_version": tls_version,
        "key_type": key_type,
        "key_bits": key_bits,
        "serial": format(cert.serial_number, "x"),
        "self_signed": cert.issuer == cert.subject,
    }


def cert_checks(info: dict, warn_days: float | None = None, crit_days: float | None = None) -> list[CheckResult]:
    """'Certificate expiry' (days left; per-probe thresholds or the tls_days_left rules / defaults) and
    'Certificate validity' (CRIT on hostname mismatch or an untrusted chain)."""
    days = info["days_left"]
    out = f"expires in {days:.0f} days ({info['not_after'][:10]})" if days >= 0 else f"expired {-days:.0f} days ago"
    if warn_days is not None or crit_days is not None:
        crit = crit_days if crit_days is not None else DEFAULT_CRIT_DAYS
        warn = warn_days if warn_days is not None else DEFAULT_WARN_DAYS
        state = State.CRIT if days < crit else State.WARN if days < warn else State.OK
        if state != State.OK:
            out += f" (< {crit if state == State.CRIT else warn:g} days)"
        expiry = CheckResult("tls_days_left", "Certificate expiry", output=out, state=state)
    else:  # threshold rules for check "tls_days_left" (direction below), default 21/7
        expiry = CheckResult("tls_days_left", "Certificate expiry", output=out, value=days, unit=" days",
                             state=State.CRIT if days < 0 else None)
    problems = []
    if info.get("hostname_match") is False:
        problems.append("hostname mismatch")
    if info.get("chain_valid") is False:
        problems.append("untrusted certificate chain")
    validity = CheckResult("tls_valid", "Certificate validity", output=", ".join(problems) or "valid",
                           state=State.CRIT if problems else State.OK)
    return [expiry, validity]


def expiry_message(info: dict) -> str:
    days = info["days_left"]
    return f"certificate expires in {days:.0f} days" if days >= 0 else "certificate expired"
