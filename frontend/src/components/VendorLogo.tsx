import {
  siAlmalinux, siAlpinelinux, siArchlinux, siCentos, siCisco, siDebian, siDell, siDocker, siF5, siFedora,
  siFortinet, siFreebsd, siHp, siHuawei, siJunipernetworks, siLenovo, siLinux, siLinuxcontainers, siMikrotik,
  siNetgear, siNokia, siOpenwrt, siOpensuse, siOpnsense, siPaloaltonetworks, siPfsense, siProxmox, siQemu,
  siQnap, siRedhat, siRockylinux, siSynology, siTplink, siTruenas, siUbiquiti, siUbuntu, siVmware,
} from "simple-icons";
import type { SimpleIcon } from "simple-icons";
import { useTheme } from "../theme";
import { Icon } from "./Icon";

// Brand marks from Simple Icons (CC0). Vendors without an icon there (Arista, HPE/Aruba,
// Microsoft, VyOS...) fall back to a device-type glyph.
const BY_OS: Record<string, SimpleIcon> = {
  ios: siCisco, iosxe: siCisco, nxos: siCisco, asa: siCisco,
  routeros: siMikrotik, fortios: siFortinet, panos: siPaloaltonetworks, junos: siJunipernetworks,
  procurve: siHp, unifi: siUbiquiti, esxi: siVmware, pfsense: siPfsense, opnsense: siOpnsense,
  proxmox: siProxmox, freebsd: siFreebsd,
  // Linux distributions (detected from installed packages)
  ubuntu: siUbuntu, debian: siDebian, rhel: siRedhat, rocky: siRockylinux, almalinux: siAlmalinux,
  centos: siCentos, fedora: siFedora, alpine: siAlpinelinux, opensuse: siOpensuse, arch: siArchlinux,
};
const BY_VENDOR: Record<string, SimpleIcon> = {
  cisco: siCisco, mikrotik: siMikrotik, fortinet: siFortinet, "palo alto": siPaloaltonetworks,
  juniper: siJunipernetworks, hp: siHp, ubiquiti: siUbiquiti, vmware: siVmware, dell: siDell,
  lenovo: siLenovo, huawei: siHuawei, "tp-link": siTplink, netgear: siNetgear, synology: siSynology,
  qnap: siQnap, nokia: siNokia, f5: siF5, proxmox: siProxmox,
};
// Fallback for devices discovered before distro detection: guess from sysDescr.
const DISTROS: [RegExp, SimpleIcon][] = [
  [/ubuntu/i, siUbuntu], [/debian|deb\d+/i, siDebian], [/\.el\d|red ?hat|rhel/i, siRedhat],
  [/centos/i, siCentos], [/rocky/i, siRockylinux], [/alma/i, siAlmalinux],
  [/truenas/i, siTruenas], [/openwrt/i, siOpenwrt], [/docker/i, siDocker],
];

export interface LogoDevice {
  os: string | null; vendor: string | null; sys_descr: string | null; device_type: string | null;
  virtualization?: string | null;
}

export const OS_LABEL: Record<string, string> = {
  ubuntu: "Ubuntu", debian: "Debian", rhel: "Red Hat Enterprise Linux", rocky: "Rocky Linux", almalinux: "AlmaLinux",
  centos: "CentOS", fedora: "Fedora", alpine: "Alpine Linux", opensuse: "openSUSE", arch: "Arch Linux",
  proxmox: "Proxmox VE", linux: "Linux", routeros: "RouterOS", fortios: "FortiOS", junos: "Junos", panos: "PAN-OS",
  ios: "IOS", iosxe: "IOS-XE", nxos: "NX-OS", asa: "ASA", esxi: "ESXi", pfsense: "pfSense", opnsense: "OPNsense",
  windows: "Windows", freebsd: "FreeBSD", eos: "EOS", unifi: "UniFi",
};

/** "Debian 12.4", "RouterOS 7.21.4" */
export const osLabel = (os: string | null, version: string | null) =>
  [os ? OS_LABEL[os] ?? os : null, version].filter(Boolean).join(" ");

export function brandIcon(d: LogoDevice): SimpleIcon | null {
  if (d.os && BY_OS[d.os]) return BY_OS[d.os];
  if (d.os === "linux" || d.os === "generic" || !d.os) {
    for (const [re, icon] of DISTROS) if (re.test(d.sys_descr ?? "")) return icon;
    if (d.os === "linux") return siLinux;
  }
  return BY_VENDOR[(d.vendor ?? "").toLowerCase()] ?? null;
}

function luminance(hex: string) {
  const [r, g, b] = [0, 2, 4].map((i) => parseInt(hex.slice(i, i + 2), 16) / 255);
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}

function Mark({ icon, size, mono }: { icon: SimpleIcon; size: number; mono?: boolean }) {
  const { theme } = useTheme();
  // Very dark (or very light) brand colors would vanish on the current background: use text color.
  const lum = luminance(icon.hex);
  const color = mono || (theme === "dark" && lum < 0.25) || (theme === "light" && lum > 0.85) ? "currentColor" : `#${icon.hex}`;
  return (
    <svg viewBox="0 0 24 24" style={{ width: size, height: size }} fill={color} role="img" aria-label={icon.title}>
      <path d={icon.path} />
    </svg>
  );
}

/** Small LXC / VM chip used next to hostnames. */
export function VirtBadge({ virtualization, className = "" }: { virtualization?: string | null; className?: string }) {
  if (!virtualization) return null;
  const lxc = virtualization === "lxc";
  return (
    <span className={`inline-flex items-center gap-1 px-1.5 py-0.5 rounded-md bg-chip text-fg2 text-xxs font-medium ${className}`}
      title={lxc ? "LXC container on Proxmox" : "Virtual machine"}>
      <Mark icon={lxc ? siLinuxcontainers : siQemu} size={10} />
      {lxc ? "LXC" : "VM"}
    </span>
  );
}

export function VendorLogo({ device, size = 40, mono = false }: { device: LogoDevice; size?: number; mono?: boolean }) {
  const icon = brandIcon(device);
  const box = { width: size, height: size };
  const virt = device.virtualization === "lxc" ? siLinuxcontainers : device.virtualization === "vm" ? siQemu : null;
  return (
    <div style={box} title={icon?.title} className="relative rounded-xl bg-inset border border-line flex items-center justify-center text-strong shrink-0">
      {icon ? <Mark icon={icon} size={size * 0.55} mono={mono} /> : (
        <Icon name={device.device_type ?? "network"} className="w-1/2 h-1/2 text-muted" />
      )}
      {virt && size >= 28 && (
        <span className="absolute -bottom-1 -right-1 rounded-md bg-surface border border-line p-[2px] text-fg2"
          title={device.virtualization === "lxc" ? "LXC container" : "Virtual machine"}>
          <Mark icon={virt} size={Math.max(9, size * 0.26)} />
        </span>
      )}
    </div>
  );
}
