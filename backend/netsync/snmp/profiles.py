"""OS / vendor detection profiles.

Matched in order against sysObjectID (prefix) and sysDescr (regex). Add new
vendors here or from a plugin via ``PROFILES.append(...)``.
"""

import re
from dataclasses import dataclass


@dataclass
class Profile:
    os: str
    vendor: str
    device_type: str
    oid_prefix: str | None = None
    descr_regex: str | None = None
    version_regex: str | None = None
    # Optional vendor OIDs (scalar GETs) that override what sysDescr / ENTITY-MIB give us.
    version_oid: str | None = None
    serial_oid: str | None = None
    hardware_oid: str | None = None
    hardware_regex: str | None = None  # extract the model from sysDescr

    def matches(self, sys_object_id: str, sys_descr: str) -> bool:
        if self.oid_prefix and not (sys_object_id + ".").startswith(self.oid_prefix + "."):
            return False
        if self.descr_regex and not re.search(self.descr_regex, sys_descr, re.I):
            return False
        return bool(self.oid_prefix or self.descr_regex)


PROFILES: list[Profile] = [
    Profile("iosxe", "Cisco", "router", "1.3.6.1.4.1.9", r"IOS[ -]XE", r"Version ([\w.()]+)"),
    Profile("nxos", "Cisco", "switch", "1.3.6.1.4.1.9", r"NX-OS", r"Version ([\w.()]+)"),
    Profile("asa", "Cisco", "firewall", "1.3.6.1.4.1.9", r"Adaptive Security Appliance", r"Version ([\w.()]+)"),
    Profile("ios", "Cisco", "router", "1.3.6.1.4.1.9", r"IOS", r"Version ([\w.()]+)"),
    Profile("routeros", "MikroTik", "router", "1.3.6.1.4.1.14988",
            version_oid="1.3.6.1.4.1.14988.1.1.4.4.0",  # mtxrLicVersion
            serial_oid="1.3.6.1.4.1.14988.1.1.7.3.0",  # mtxrSerialNumber
            hardware_regex=r"RouterOS (.+)"),
    Profile("fortios", "Fortinet", "firewall", "1.3.6.1.4.1.12356"),
    Profile("panos", "Palo Alto", "firewall", "1.3.6.1.4.1.25461"),
    Profile("junos", "Juniper", "router", "1.3.6.1.4.1.2636", None, r"JUNOS ([\w.\-]+)"),
    Profile("eos", "Arista", "switch", "1.3.6.1.4.1.30065", None, r"EOS version ([\w.]+)"),
    Profile("arubaos-cx", "Aruba", "switch", "1.3.6.1.4.1.47196"),
    Profile("procurve", "HPE", "switch", "1.3.6.1.4.1.11", r"ProCurve|Aruba|HP J"),
    Profile("unifi", "Ubiquiti", "network", "1.3.6.1.4.1.41112"),
    Profile("esxi", "VMware", "server", "1.3.6.1.4.1.6876", None, r"ESXi ([\d.]+)"),
    Profile("pfsense", "Netgate", "firewall", None, r"pfSense"),
    Profile("opnsense", "Deciso", "firewall", None, r"OPNsense"),
    Profile("windows", "Microsoft", "server", "1.3.6.1.4.1.311", None, r"Version ([\d.]+)"),
    Profile("proxmox", "Proxmox", "server", None, r"pve"),
    Profile("linux", "Linux", "server", None, r"^Linux", r"^Linux \S+ ([\w.\-]+)"),
    Profile("freebsd", "FreeBSD", "server", None, r"^FreeBSD", r"FreeBSD \S+ ([\w.\-]+)"),
]


def detect(sys_object_id: str, sys_descr: str) -> tuple[Profile | None, str | None]:
    for p in PROFILES:
        if p.matches(sys_object_id or "", sys_descr or ""):
            version = None
            if p.version_regex and (m := re.search(p.version_regex, sys_descr or "")):
                version = m.group(1)
            return p, version
    return None, None
