"""Self-signed certificates for TLS tests."""

import ipaddress
from datetime import UTC, datetime, timedelta

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID


def make_cert(cn: str = "localhost", sans: tuple[str, ...] = ("localhost",), days: float = 90,
              not_before_days: float = 1):
    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, cn)])
    alt = []
    for s in sans:
        try:
            alt.append(x509.IPAddress(ipaddress.ip_address(s)))
        except ValueError:
            alt.append(x509.DNSName(s))
    now = datetime.now(UTC)
    cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(now - timedelta(days=not_before_days)).not_valid_after(now + timedelta(days=days))
            .add_extension(x509.SubjectAlternativeName(alt), critical=False)
            .sign(key, hashes.SHA256()))
    return cert, key


def write_pair(tmp_path, cert, key):
    c, k = tmp_path / "cert.pem", tmp_path / "key.pem"
    c.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    k.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                    serialization.NoEncryption()))
    return str(c), str(k)


def der(cert) -> bytes:
    return cert.public_bytes(serialization.Encoding.DER)
