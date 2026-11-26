"""Notification rules: which problem types a rule sends, webhook URL cleanup, secrets kept out of the UI."""

from typing import Any
from urllib.parse import urlsplit

# (key, label, checks). A rule with no types selected sends every type.
PROBLEM_TYPES: list[tuple[str, str, set[str]]] = [
    ("device_down", "Device down / unreachable", {"ping_loss", "snmp"}),
    ("latency", "Latency (ping)", {"ping_rtt"}),
    ("cpu", "CPU", {"cpu_util"}),
    ("memory", "Memory (RAM, swap)", {"mem_used", "swap_used"}),
    ("disk", "Disk / storage", {"storage_used"}),
    ("port", "Ports / interfaces", {"if"}),
    ("network_errors", "Network errors (TCP, UDP)", {"tcp_retrans", "udp_errors"}),
    ("hardware", "Hardware (temperature, fans, power)", {"temperature", "fan", "psu", "voltage", "current", "power"}),
    ("reboot", "Reboots / uptime", {"uptime"}),
    ("probe", "Probes (websites, TLS certificates)", {"probe_status", "probe_response", "tls_valid", "tls_days_left"}),
    ("container", "Docker containers", {"docker_container", "docker_data"}),
    ("crowdsec", "CrowdSec", {"crowdsec_lapi", "crowdsec_new_bans"}),
    ("ipbook", "IP Book addresses (alert when down)", {"ipbook_ping"}),
    ("other", "Other checks", set()),
]
TYPE_KEYS = {k for k, _, _ in PROBLEM_TYPES}
_BY_CHECK = {c: k for k, _, checks in PROBLEM_TYPES for c in checks}


def problem_type(check: str | None) -> str:
    """The problem type of a service check (unknown checks are "other")."""
    return _BY_CHECK.get(check or "", "other")


def wants(types: list[str] | None, check: str | None) -> bool:
    """True when a rule with these selected types sends an alert for this check (none selected = all)."""
    return not types or problem_type(check) in types


def clean_types(types: list[str] | None) -> list[str] | None:
    if not types:
        return None
    bad = [t for t in types if t not in TYPE_KEYS]
    if bad:
        raise ValueError(f"Unknown problem type: {', '.join(bad)}")
    return sorted(set(types), key=[k for k, _, _ in PROBLEM_TYPES].index)


def clean_url(value: Any) -> str:
    """A webhook address: http(s) URL, host name or IP (with optional port and path); no scheme means http://."""
    v = str(value or "").strip()
    if not v:
        raise ValueError("URL is required")
    if "://" not in v:
        v = "http://" + v
    try:
        parts = urlsplit(v)
        port = parts.port  # raises on a bad port
    except ValueError as e:
        raise ValueError(f"URL {value!r} is not valid ({e})") from e
    if parts.scheme.lower() not in ("http", "https"):
        raise ValueError("URL must start with http:// or https://")
    if not parts.hostname or any(c.isspace() for c in v):
        raise ValueError(f"URL {value!r} is not valid")
    del port
    return v


def secret_keys(fields: list[dict]) -> set[str]:
    return {f["key"] for f in fields if f.get("type") == "secret"}


def clean_config(fields: list[dict], config: dict, old: dict | None = None) -> dict:
    """Trims values, checks URLs and keeps a saved secret when the form sends it back empty."""
    out: dict[str, Any] = {}
    secrets = secret_keys(fields)
    for f in fields:
        k = f["key"]
        v = config.get(k)
        v = v.strip() if isinstance(v, str) else v
        if k in secrets and not v and old and old.get(k):
            v = old[k]
        if k == "url" and (v or f.get("required")):
            v = clean_url(v)
        if f.get("required") and not v:
            raise ValueError(f"{f['label']} is required")
        if v not in (None, ""):
            out[k] = v
    return out


def public_config(fields: list[dict], config: dict) -> tuple[dict, list[str]]:
    """The config for the UI without secret values, and which secrets are saved."""
    secrets = secret_keys(fields)
    return ({k: v for k, v in (config or {}).items() if k not in secrets},
            sorted(k for k in secrets if (config or {}).get(k)))


def error_text(e: BaseException, config: dict) -> str:
    """A short error for the UI, with saved tokens and secrets blanked out (a Telegram URL holds the bot token)."""
    text = f"{type(e).__name__}: {e}"
    for k, v in (config or {}).items():
        if k != "url" and isinstance(v, str) and len(v) >= 6:
            text = text.replace(v, "***")
    return text[:300]
