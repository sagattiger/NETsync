# Intel Optane as swap: show it in NETsync

Many Proxmox and Linux hosts use a small Intel Optane module (Optane Memory M10/H10, 800P, P1600X…) as a
fast swap device. Standard SNMP can't tell which disk holds swap or what model a disk is, so NETsync needs one
small helper on the host. With it, the device page shows:

- **Health → Memory → Swap device:** every swap area, the disk it's on, its model, an **Intel Optane** tag,
  its size and how much is in use.
- **Health → Disk I/O:** the disk models, with **Intel Optane** and **swap** tags on the right disk. Its
  read/write graph is the easiest way to see how hard swap is working.

## Setup (on the host, as root)

1. Create the helper. It prints the disk models, a `---` line, then the swap areas:

   ```bash
   cat > /usr/local/bin/netsync-disks <<'EOF'
   #!/bin/sh
   lsblk -dno NAME,MODEL,SIZE
   echo ---
   cat /proc/swaps
   EOF
   chmod 755 /usr/local/bin/netsync-disks
   ```

2. Check it. You should see something like:

   ```text
   $ /usr/local/bin/netsync-disks
   sda     Samsung SSD 860 EVO     465.8G
   sdb     WDC WD2003FYYS-18W0B0     1.8T
   nvme0n1 INTEL MEMPEK1J016GAD     13.4G
   ---
   Filename          Type        Size      Used   Priority
   /dev/nvme0n1p1    partition   14063612  4852   10
   /dev/dm-0         partition   8388604   0      -1
   ```

3. Publish it over SNMP (add the line **once**) and restart snmpd:

   ```bash
   echo 'extend netsync-disks /usr/local/bin/netsync-disks' >> /etc/snmp/snmpd.conf
   systemctl restart snmpd
   ```

4. In NETsync, open the device and press **Rediscover**. The swap device appears under **Health → Memory**.

`lsblk` and `/proc/swaps` are readable by any user, so snmpd needs no extra rights. Nothing is sent anywhere
else: NETsync reads the output over SNMP like any other value.

## Which models are recognised

The tag comes from the model name: Optane Memory M10/H10 (`MEMPEK1J…`, `MEMPEK1W…`), 800P (`SSDPEK1W…`),
P1600X (`SSDPEK1A…`), 900P/905P (`SSDPED1D…`, `SSDPE21D…`), P4800X/P4801X (`SSDPE21K…`, `SSDPEL1K…`) and
P5800X (`SSDPF21Q…`), or any model containing "Optane".

## Notes

- **Several swap areas:** all are listed. Linux uses the one with the highest priority first. In the example
  the Optane partition (priority 10) fills before the LVM swap (priority -1).
- **Swap on LVM** (`/dev/dm-0`, `/dev/mapper/…`) is shown as "on LVM / device-mapper": the physical disk
  behind it isn't visible to this helper.
- **Duplicate line:** if the `extend` line ended up in `snmpd.conf` twice, snmpd ignores the second copy. To
  tidy up, check that the last line is the duplicate with `tail -n 2 /etc/snmp/snmpd.conf`, then remove it with
  `sed -i '$d' /etc/snmp/snmpd.conf` and restart snmpd.

See [HOST-METRICS.md](HOST-METRICS.md) for everything else NETsync reads from Linux hosts.
