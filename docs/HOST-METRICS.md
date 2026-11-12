# Host metrics (Linux / net-snmp)

NETsync reads these over plain SNMP from any Linux host running `snmpd` (Proxmox, Debian, Ubuntu…).
Nothing extra is needed on the host, apart from the optional swap/disk extend described at the end.

| Where on the device page | What | Source |
|---|---|---|
| Health → Processor | CPU model, threads and physical cores, per-thread load, user/system/iowait/irq/steal split, load averages scaled to the thread count | HOST-RESOURCES-MIB (`hrDeviceDescr`, `hrProcessorLoad`), UCD-SNMP-MIB (`ssCpuRaw*`, `laLoad`), core count from LM-SENSORS |
| Health → Memory | Used, buffers, cached, free, available and swap, in bytes and scaled to the real RAM size; swap I/O | UCD-SNMP-MIB `memory` (`memTotalReal`, `memBuffer`, `memCached`, `memSysAvail`…), `ssRawSwapIn/Out` |
| Health → Storage | Every filesystem (bytes, scaled to its size) and block I/O | HOST-RESOURCES-MIB `hrStorage`, `ssIORawSent/Received` |
| Health → Disk I/O | Read/write throughput and operations per whole disk (`sda`, `nvme0n1`…) | UCD-DISKIO-MIB |
| Health → Temperature, Fan speed | Every lm-sensors reading; CPU package/core sensors grouped as *Processor sensors*. Chip-prefixed duplicates (`dell_smm-isa-00de:Other Fan`) are skipped | LM-SENSORS-MIB |
| Graphs → System | Availability, uptime, load, context switches, interrupts, running processes, users logged in | SNMPv2-MIB, UCD-SNMP-MIB, HOST-RESOURCES-MIB |
| Graphs → Network stack | IP statistics and fragmentation, ICMP and ICMP echo, TCP, UDP, SNMP agent statistics, IPv4/IPv6 packets and fragmentation | IP-MIB (`ipSystemStatsTable`), TCP-MIB, UDP-MIB, SNMPv2-MIB |
| Graphs → Poller | Ping and SNMP response time, poll duration, SNMP requests, time waiting and errors per poll | NETsync itself |
| Ports → (expand a port) | Traffic, errors and discards, unicast and non-unicast packets, average packet size, utilisation | IF-MIB `ifXTable` |

Temperatures get a service (`Temperature <sensor>`) with default thresholds of 70 °C (warning) and
85 °C (critical); change them in **Threshold rules** (check `temperature`). Fans get a `Fan <name>` service
without thresholds; add a rule on the `fan` check with "below" if you want an alert when a fan slows down.

New components (sensors, disks, system statistics) appear after the next discovery, or straight away with
**Rediscover** on the device page. Rates need two polls before the first point is drawn.

## Optional: swap device and disk models (Intel Optane detection)

Standard SNMP doesn't say which disk holds swap or what model a disk is. One small `extend` adds both, so
NETsync can show *"Swap: /dev/nvme0n1p1 · Intel Optane · INTEL MEMPEK1W016GA"* and tag the disk on the
Disk I/O page. On the host, as root:

```bash
cat > /usr/local/bin/netsync-disks <<'EOF'
#!/bin/sh
# Disk models for NETsync, then the swap areas
lsblk -dno NAME,MODEL,SIZE
echo ---
cat /proc/swaps
EOF
chmod 755 /usr/local/bin/netsync-disks
echo 'extend netsync-disks /usr/local/bin/netsync-disks' >> /etc/snmp/snmpd.conf
systemctl restart snmpd
```

Then press **Rediscover** on the device. Optane is recognised by the model name (Optane Memory M10/H10,
800P, 900P, 905P, P1600X, P4800X, P5800X: `MEMPEK1J…`, `MEMPEK1W…`, `SSDPEK1A…`, `SSDPEK1W…`,
`SSDPED1D…`, `SSDPE21D…`, `SSDPE21K…`, `SSDPEL1K…`, `SSDPF21Q…`). Swap on LVM (`/dev/dm-1`) is shown as
"on LVM / device-mapper" because the physical disk behind it isn't visible to this script.

## Not available

Observium's *Poller MySQL operations/times*, *Poller memory usage* and *Agent execution time* have no
equivalent: NETsync stores data in PostgreSQL/TimescaleDB, polls many devices in one process, and doesn't use
an agent. *IPv6 traffic per port* needs `ipIfStatsTable`, which Linux `snmpd` doesn't provide.
