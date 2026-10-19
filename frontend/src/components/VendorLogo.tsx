import {
  siCisco, siDebian, siDell, siDocker, siF5, siFortinet, siFreebsd, siHp, siHuawei, siJunipernetworks,
  siLenovo, siLinux, siMikrotik, siNetgear, siNokia, siOpenwrt, siOpnsense, siPaloaltonetworks, siPfsense,
  siProxmox, siQnap, siRedhat, siRockylinux, siSynology, siTplink, siTruenas, siUbiquiti, siUbuntu,
  siVmware, siCentos, siAlmalinux,
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
};
const BY_VENDOR: Record<string, SimpleIcon> = {
  cisco: siCisco, mikrotik: siMikrotik, fortinet: siFortinet, "palo alto": siPaloaltonetworks,
  juniper: siJunipernetworks, hp: siHp, ubiquiti: siUbiquiti, vmware: siVmware, dell: siDell,
  lenovo: siLenovo, huawei: siHuawei, "tp-link": siTplink, netgear: siNetgear, synology: siSynology,
  qnap: siQnap, nokia: siNokia, f5: siF5, proxmox: siProxmox,
};
// Linux distributions are recognised from sysDescr.
const DISTROS: [RegExp, SimpleIcon][] = [
  [/ubuntu/i, siUbuntu], [/debian|deb\d+/i, siDebian], [/\.el\d|red ?hat|rhel/i, siRedhat],
  [/centos/i, siCentos], [/rocky/i, siRockylinux], [/alma/i, siAlmalinux], [/pve|proxmox/i, siProxmox],
  [/truenas/i, siTruenas], [/openwrt/i, siOpenwrt], [/docker/i, siDocker],
];

export interface LogoDevice { os: string | null; vendor: string | null; sys_descr: string | null; device_type: string | null }

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

export function VendorLogo({ device, size = 40, mono = false }: { device: LogoDevice; size?: number; mono?: boolean }) {
  const { theme } = useTheme();
  const icon = brandIcon(device);
  const box = { width: size, height: size };
  if (!icon) {
    return (
      <div style={box} className="rounded-xl bg-inset border border-line flex items-center justify-center text-muted shrink-0">
        <Icon name={device.device_type ?? "network"} className="w-1/2 h-1/2" />
      </div>
    );
  }
  // Very dark (or very light) brand colors would vanish on the current background: use text color.
  const lum = luminance(icon.hex);
  const color = mono || (theme === "dark" && lum < 0.25) || (theme === "light" && lum > 0.85) ? "currentColor" : `#${icon.hex}`;
  return (
    <div style={box} title={icon.title} className="rounded-xl bg-inset border border-line flex items-center justify-center text-strong shrink-0">
      <svg viewBox="0 0 24 24" style={{ width: size * 0.55, height: size * 0.55 }} fill={color} role="img" aria-label={icon.title}>
        <path d={icon.path} />
      </svg>
    </div>
  );
}
