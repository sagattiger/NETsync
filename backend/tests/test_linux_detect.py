"""Samples taken from real devices in the lab (hrSWInstalledName values)."""

from netsync.snmp.linux import detect, split_package

PVE_KERNEL = "Linux lxc100-infra 7.0.14-21-pve #1 SMP PREEMPT_DYNAMIC PMX 7.0.14-21 (2026-09-30T16:32Z) x86_64"
UBUNTU_KERNEL = "Linux vm206-infra 6.8.0-142-generic #142-Ubuntu SMP PREEMPT_DYNAMIC x86_64"
CPU = ["GenuineIntel: Intel(R) Core(TM) i7-3770 CPU @ 3.40GHz"]


def test_split_package():
    assert split_package("base-files_12.4+deb12u12_amd64") == ("base-files", "12.4+deb12u12")
    assert split_package("ubuntu-release-upgrader-core_1:24.04.29_all") == ("ubuntu-release-upgrader-core", "1:24.04.29")
    assert split_package("rocky-release-9.4-1.7.el9.noarch") == ("rocky-release", "9.4-1.7.el9")


def test_debian_lxc_on_proxmox():
    info = detect(["adduser_3.134_all", "base-files_12.4+deb12u12_amd64", "systemd_252.39-1~deb12u1_amd64"], PVE_KERNEL, CPU)
    assert (info.os, info.version, info.virtualization) == ("debian", "12.4", "lxc")
    assert info.hardware == "LXC container (Proxmox)"


def test_debian13_lxc():
    info = detect(["base-files_13.8+deb13u7_amd64"], PVE_KERNEL, CPU)
    assert (info.os, info.version, info.virtualization) == ("debian", "13.8", "lxc")


def test_proxmox_host_is_not_a_container():
    pkgs = ["base-files_13.8+deb13u7_amd64", "proxmox-ve_9.2.0_all", "pve-manager_9.2.21_all"]
    info = detect(pkgs, PVE_KERNEL.replace("lxc100", "pve001"), CPU)
    assert (info.os, info.version, info.virtualization) == ("proxmox", "9.2.21", None)


def test_ubuntu_with_release_upgrader():
    info = detect(["base-files_13ubuntu10.5_amd64", "ubuntu-release-upgrader-core_1:24.04.29_all"], UBUNTU_KERNEL, CPU)
    assert (info.os, info.version, info.virtualization) == ("ubuntu", "24.04", None)


def test_ubuntu_lxc_from_base_files_only():
    info = detect(["base-files_12ubuntu4.7_amd64"], PVE_KERNEL, CPU)
    assert (info.os, info.version, info.virtualization) == ("ubuntu", "22.04", "lxc")


def test_vm_detected_from_virtual_cpu():
    info = detect(["base-files_12.4+deb12u12_amd64"], "Linux web1 6.1.0-28-amd64 #1 SMP Debian", ["QEMU Virtual CPU version 2.5+"])
    assert info.virtualization == "vm"


def test_rocky():
    info = detect(["rocky-release-9.4-1.7.el9.noarch", "bash-5.1.8-9.el9.x86_64"], "Linux r1 5.14.0-427.el9.x86_64", CPU)
    assert (info.os, info.version) == ("rocky", "9.4")


def test_unknown_packages_returns_none():
    assert detect([], UBUNTU_KERNEL, CPU) is None
