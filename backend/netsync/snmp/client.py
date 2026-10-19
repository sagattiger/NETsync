"""Thin async wrapper around pysnmp (v1, v2c, v3)."""

from __future__ import annotations

from typing import Any

from pysnmp.hlapi.v3arch.asyncio import (
    CommunityData,
    ContextData,
    ObjectIdentity,
    ObjectType,
    SnmpEngine,
    UdpTransportTarget,
    UsmUserData,
    bulk_walk_cmd,
    get_cmd,
    usmAesCfb128Protocol,
    usmAesCfb256Protocol,
    usmDESPrivProtocol,
    usmHMAC192SHA256AuthProtocol,
    usmHMAC384SHA512AuthProtocol,
    usmHMACMD5AuthProtocol,
    usmHMACSHAAuthProtocol,
    usmNoAuthProtocol,
    usmNoPrivProtocol,
)
from pysnmp.proto import rfc1902, rfc1905

from netsync.config import get_settings

AUTH_PROTOCOLS = {
    None: usmNoAuthProtocol,
    "md5": usmHMACMD5AuthProtocol,
    "sha": usmHMACSHAAuthProtocol,
    "sha256": usmHMAC192SHA256AuthProtocol,
    "sha512": usmHMAC384SHA512AuthProtocol,
}
PRIV_PROTOCOLS = {
    None: usmNoPrivProtocol,
    "des": usmDESPrivProtocol,
    "aes": usmAesCfb128Protocol,
    "aes256": usmAesCfb256Protocol,
}

_engine: SnmpEngine | None = None


def engine() -> SnmpEngine:
    global _engine
    if _engine is None:
        _engine = SnmpEngine()
    return _engine


class SnmpError(Exception):
    pass


class SnmpTimeout(SnmpError):
    pass


def convert(value: Any) -> Any:
    """Convert a pysnmp value to a plain python value."""
    if isinstance(value, (rfc1905.NoSuchObject, rfc1905.NoSuchInstance, rfc1905.EndOfMibView)):
        return None
    if isinstance(value, rfc1902.IpAddress):
        return value.prettyPrint()
    if isinstance(value, rfc1902.OctetString):
        return bytes(value.asOctets())
    if isinstance(value, rfc1902.ObjectIdentifier):
        return str(value)
    try:
        return int(value)
    except (TypeError, ValueError):
        return value.prettyPrint()


def text(value: Any) -> str | None:
    """Decode an OctetString value to text."""
    if value is None:
        return None
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace").strip("\x00").strip()
    return str(value)


def mac(value: Any) -> str | None:
    if isinstance(value, bytes) and len(value) == 6:
        return ":".join(f"{b:02x}" for b in value)
    return None


class SnmpClient:
    def __init__(
        self,
        host: str,
        port: int = 161,
        version: str = "2c",
        community: str | None = "public",
        v3: dict | None = None,
        timeout: float | None = None,
        retries: int | None = None,
    ):
        s = get_settings()
        self.host = host
        self.port = port
        self.timeout = timeout if timeout is not None else s.snmp_timeout
        self.retries = retries if retries is not None else s.snmp_retries
        if version == "3":
            v3 = v3 or {}
            self.auth = UsmUserData(
                v3.get("user", ""),
                authKey=v3.get("auth_key") or None,
                privKey=v3.get("priv_key") or None,
                authProtocol=AUTH_PROTOCOLS[v3.get("auth_proto")],
                privProtocol=PRIV_PROTOCOLS[v3.get("priv_proto")],
            )
        else:
            self.auth = CommunityData(community or "public", mpModel=0 if version == "1" else 1)
        self.bulk = version != "1"
        self._target: UdpTransportTarget | None = None

    @classmethod
    def for_device(cls, device) -> SnmpClient:
        return cls(
            device.ip or device.hostname,
            port=device.snmp_port,
            version=device.snmp_version,
            community=device.snmp_community,
            v3=device.snmp_v3,
        )

    async def target(self) -> UdpTransportTarget:
        if self._target is None:
            self._target = await UdpTransportTarget.create(
                (self.host, self.port), timeout=self.timeout, retries=self.retries
            )
        return self._target

    async def get(self, *oids: str) -> dict[str, Any]:
        """GET scalar OIDs. Returns {oid: value} (value None when missing)."""
        err_ind, err_status, err_index, var_binds = await get_cmd(
            engine(),
            self.auth,
            await self.target(),
            ContextData(),
            *[ObjectType(ObjectIdentity(o)) for o in oids],
            lookupMib=False,
        )
        if err_ind:
            raise SnmpTimeout(str(err_ind)) if "timeout" in str(err_ind).lower() else SnmpError(str(err_ind))
        if err_status:
            raise SnmpError(err_status.prettyPrint())
        return {str(name): convert(val) for name, val in var_binds}

    async def walk(self, oid: str) -> dict[str, Any]:
        """Walk a subtree. Returns {index_suffix: value}."""
        base = oid.strip(".")
        out: dict[str, Any] = {}
        if self.bulk:
            gen = bulk_walk_cmd(
                engine(),
                self.auth,
                await self.target(),
                ContextData(),
                0,
                25,
                ObjectType(ObjectIdentity(base)),
                lexicographicMode=False,
                lookupMib=False,
            )
        else:
            from pysnmp.hlapi.v3arch.asyncio import walk_cmd

            gen = walk_cmd(
                engine(),
                self.auth,
                await self.target(),
                ContextData(),
                ObjectType(ObjectIdentity(base)),
                lexicographicMode=False,
                lookupMib=False,
            )
        async for err_ind, err_status, _idx, var_binds in gen:
            if err_ind:
                raise SnmpTimeout(str(err_ind)) if "timeout" in str(err_ind).lower() else SnmpError(str(err_ind))
            if err_status:
                break
            for name, val in var_binds:
                name = str(name)
                if not name.startswith(base + "."):
                    continue
                v = convert(val)
                if v is not None:
                    out[name[len(base) + 1 :]] = v
        return out

    async def table(self, columns: dict[str, str]) -> dict[str, dict[str, Any]]:
        """Walk several table columns and pivot into {index: {column: value}}."""
        rows: dict[str, dict[str, Any]] = {}
        for col, oid in columns.items():
            for index, value in (await self.walk(oid)).items():
                rows.setdefault(index, {})[col] = value
        return rows
