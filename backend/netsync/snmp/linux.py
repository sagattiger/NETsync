"""Linux distribution, Proxmox host and container detection.

sysDescr only carries the *kernel*, and LXC containers share the host's kernel, so a
container on Proxmox reports "...-pve" just like the host. Instead we read the installed
package list (HOST-RESOURCES-MIB hrSWInstalledName, "name_version_arch" on Debian-like
systems, "name-version-release.arch" for RPM) and derive:

  * the distribution and its version (from base-files / *-release packages)
  * a Proxmox VE host (pve-manager / proxmox-ve installed)
  * an LXC container on Proxmox (pve kernel but no pve-manager)
  * a virtual machine when the virtual CPU is visible (QEMU/KVM/VMware/Hyper-V)
"""

import re
from dataclasses import dataclass

HR_SW_INSTALLED_NAME = "1.3.6.1.2.1.25.6.3.1.2"
HR_DEVICE_DESCR = "1.3.6.1.2.1.25.3.2.1.3"

# Ubuntu base-files major version -> release, used when ubuntu-release-upgrader is absent.
UBUNTU_BASE_FILES = {"10": "18.04", "11": "20.04", "12": "22.04", "13": "24.04", "14": "26.04"}

RPM_RELEASES = [
    ("rocky-release", "rocky", "Rocky Linux"),
    ("almalinux-release", "almalinux", "AlmaLinux"),
    ("centos-stream-release", "centos", "CentOS Stream"),
    ("centos-release", "centos", "CentOS"),
    ("redhat-release", "rhel", "Red Hat"),
    ("oraclelinux-release", "oracle", "Oracle Linux"),
    ("fedora-release", "fedora", "Fedora"),
    ("openSUSE-release", "opensuse", "openSUSE"),
]

VM_CPU = re.compile(r"QEMU|KVM|VMware|Hyper-V|Microsoft Virtual|VirtualBox|Xen", re.I)


@dataclass
class LinuxInfo:
    os: str
    vendor: str
    version: str | None
    virtualization: str | None  # "lxc", "vm" or None (bare metal / unknown)
    hardware: str | None


def split_package(entry: str) -> tuple[str, str]:
    """'base-files_12.4+deb12u12_amd64' -> ('base-files', '12.4+deb12u12');
    'rocky-release-9.4-1.7.el9.noarch' -> ('rocky-release', '9.4-1.7.el9')."""
    if "_" in entry:
        name, _, rest = entry.partition("_")
        return name, rest.rsplit("_", 1)[0] if "_" in rest else rest
    m = re.match(r"^(.+?)-(\d[^-]*-[^-]+?)(?:\.(?:noarch|x86_64|aarch64|i686))?$", entry)
    return (m.group(1), m.group(2)) if m else (entry, "")


def detect(packages: list[str], sys_descr: str, cpu_descrs: list[str]) -> LinuxInfo | None:
    pkgs = dict(split_package(p) for p in packages if p)
    pve_kernel = "-pve" in (sys_descr or "")

    def virtualization() -> str | None:
        if pve_kernel and "pve-manager" not in pkgs and "proxmox-ve" not in pkgs:
            return "lxc"
        if any(VM_CPU.search(c or "") for c in cpu_descrs):
            return "vm"
        return None

    if "pve-manager" in pkgs or "proxmox-ve" in pkgs:
        return LinuxInfo("proxmox", "Proxmox", pkgs.get("pve-manager") or pkgs.get("proxmox-ve"), None, "Proxmox VE host")

    virt = virtualization()
    hardware = {"lxc": "LXC container (Proxmox)", "vm": "Virtual machine"}.get(virt)
    base = pkgs.get("base-files", "")

    if "ubuntu" in base or "ubuntu-release-upgrader-core" in pkgs:
        upgrader = pkgs.get("ubuntu-release-upgrader-core", "")
        if m := re.search(r"(\d{2}\.\d{2})", upgrader.split(":")[-1]):
            version = m.group(1)
        else:
            version = UBUNTU_BASE_FILES.get(base.split("ubuntu")[0].split(".")[0])
        return LinuxInfo("ubuntu", "Ubuntu", version, virt, hardware)

    # Debian base-files: "12.4+deb12u12", "13.8+deb13u7" (or a plain "13.8" on testing)
    if "+deb" in base or re.fullmatch(r"\d+(\.\d+)?", base):
        m = re.match(r"^(\d+(?:\.\d+)?)", base)
        return LinuxInfo("debian", "Debian", m.group(1) if m else None, virt, hardware)

    for pkg, os_id, vendor in RPM_RELEASES:
        if pkg in pkgs:
            version = re.match(r"^([\d.]+)", pkgs[pkg])
            return LinuxInfo(os_id, vendor, version.group(1) if version else None, virt, hardware)

    if "alpine-base" in pkgs:
        return LinuxInfo("alpine", "Alpine", re.match(r"^([\d.]+)", pkgs["alpine-base"]).group(1), virt, hardware)

    if virt:  # unknown distro, but we still know it is a container / VM
        return LinuxInfo("linux", "Linux", None, virt, hardware)
    return None
