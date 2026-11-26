"""IP Book columns: the built-in set (from the design's Columns table) and the types custom columns can have."""

from typing import Any

TYPES = ("text", "longtext", "number", "url", "urls", "ip", "port", "secret", "bool", "choice", "service", "device")
SECRET_TYPES = {"secret"}
IP_TYPES = {"ip"}
EXTRA_IP_KEYS = {"other_ips"}  # learned addresses that don't fit IP Mgmt / IP Lan: pinged and checked too


def _c(key: str, label: str, type_: str, icon: str, **extra: Any) -> dict[str, Any]:
    return {"key": key, "label": label, "type": type_, "icon": icon, **extra}


BUILTIN: list[dict[str, Any]] = [
    _c("service", "Service Name", "service", "puzzle"),
    _c("hypervisor", "Hypervisor", "device", "server"),
    _c("type", "Type", "choice", "grid", options=["Device", "VM", "LXC", "Docker"]),
    _c("os", "OS", "text", "terminal"),
    _c("vmid", "VMID", "number", "list"),
    _c("ha", "HA", "bool", "refresh"),
    _c("hostname", "Device / Hostname", "text", "router"),
    _c("ip_mgmt", "IP Mgmt", "ip", "gear"),
    _c("ip_wan", "IP Wan", "ip", "globe"),
    _c("nat", "NAT", "bool", "arrow"),
    _c("ip_lan", "IP Lan", "ip", "network"),
    _c("fqdn_internal", "Internal FQDN", "text", "network"),
    _c("fqdn_public", "Public FQDN", "text", "globe"),
    _c("urls_public", "Public URLs", "urls", "external"),
    _c("ssl", "SSL", "bool", "lock"),
    _c("urls_internal", "MGMT or Internal URLs", "urls", "external"),
    _c("http_port", "http port", "port", "switch"),
    _c("https_port", "https port", "port", "switch"),
    _c("web_user", "Web User", "text", "user"),
    _c("web_pass", "Web Pass", "secret", "lock"),
    _c("os_user", "OS User", "text", "user"),
    _c("os_pass", "OS Password", "secret", "lock"),
    _c("db_pass", "DB Password", "secret", "lock"),
    _c("enable_secret", "Enable Secret", "secret", "lock"),
    _c("aaa", "AAA", "text", "shield"),
    _c("telnet_port", "Telnet / Port", "port", "terminal"),
    _c("ssh_port", "SSH / Port", "port", "terminal"),
    _c("winbox", "Winbox", "port", "router"),
    _c("description", "Description", "longtext", "note"),
]
for _i, _col in enumerate(BUILTIN):
    _col["position"] = _i
BUILTIN_KEYS = {c["key"] for c in BUILTIN}


def ip_keys(cols: list[dict]) -> set[str]:
    """Keys of every IP-bearing column (built-in and custom), plus the learned extra addresses."""
    return {c["key"] for c in cols if c.get("type") in IP_TYPES} | EXTRA_IP_KEYS


def secret_keys(cols: list[dict]) -> set[str]:
    return {c["key"] for c in cols if c.get("type") in SECRET_TYPES}


async def seed(session) -> None:
    """Insert built-in columns that are missing; existing ones (renamed, hidden, reordered) are left alone."""
    from sqlalchemy import select

    from netsync.models import IpbColumn

    have = set(await session.scalars(select(IpbColumn.key)))
    for c in BUILTIN:
        if c["key"] not in have:
            session.add(IpbColumn(key=c["key"], label=c["label"], type=c["type"], icon=c["icon"],
                                  options=c.get("options"), position=c["position"], hidden=False, builtin=True))
    await session.flush()
