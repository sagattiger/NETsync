"""Encryption at rest for probe secrets (passwords, tokens, header values, secret bodies).

Fernet (AES-128-CBC + HMAC-SHA256) with a key derived from NETSYNC_SECRET_KEY. Changing that key makes
stored probe secrets unreadable (probes then run without them and must be edited)."""

import base64
import hashlib
import json
import logging

from cryptography.fernet import Fernet, InvalidToken

from netsync.config import get_settings

log = logging.getLogger(__name__)
MASK = "********"


def _fernet(secret_key: str | None = None) -> Fernet:
    key = (secret_key or get_settings().secret_key).encode()
    return Fernet(base64.urlsafe_b64encode(hashlib.sha256(b"netsync-probe-secrets\0" + key).digest()))


def encrypt(data: dict, secret_key: str | None = None) -> str | None:
    data = {k: v for k, v in (data or {}).items() if v not in (None, "", {}, [])}
    if not data:
        return None
    return _fernet(secret_key).encrypt(json.dumps(data, separators=(",", ":")).encode()).decode()


def decrypt(token: str | None, secret_key: str | None = None) -> dict:
    if not token:
        return {}
    try:
        return json.loads(_fernet(secret_key).decrypt(token.encode()))
    except (InvalidToken, ValueError):
        log.warning("probe secrets cannot be decrypted (was NETSYNC_SECRET_KEY changed?)")
        return {}


def merge(stored: dict, incoming: dict | None) -> dict:
    """PUT semantics: a field left out (or sent as the mask) keeps the stored value; "" or null clears it."""
    out = dict(stored)
    for k, v in (incoming or {}).items():
        if v == MASK:
            continue
        if v in (None, "", {}, []):
            out.pop(k, None)
        else:
            out[k] = v
    return out


def describe(secrets: dict) -> dict:
    """Safe view for GET responses: which secrets are set, never their values (header names are shown)."""
    out: dict = {f"has_{k}": True for k, v in secrets.items() if v}
    if isinstance(secrets.get("headers"), dict):
        out["header_names"] = sorted(secrets["headers"])
    return out
