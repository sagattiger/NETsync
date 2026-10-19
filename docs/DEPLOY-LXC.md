# Deploying on a Proxmox LXC (Ubuntu)

## 1. Container options (on the Proxmox host)

Docker inside an LXC needs nesting and keyctl. You can turn them on in the GUI (container → Options →
Features → *Nesting* and *keyctl*) or from the host shell:

```bash
pct set <CTID> --features nesting=1,keyctl=1
pct reboot <CTID>
```

Recommended size for about 500 devices: 4 vCPU, 8 GB RAM, 60+ GB disk (metrics with 90-day retention).

## 2. Install Docker (inside the container)

```bash
apt update && apt install -y ca-certificates curl git
curl -fsSL https://get.docker.com | sh
```

## 3. Deploy NETsync

```bash
git clone https://github.com/sagattiger/NETsync.git /opt/netsync
cd /opt/netsync
cp .env.example .env
sed -i "s/change-me-db-password/$(openssl rand -hex 16)/; s/change-me-long-random-string/$(openssl rand -hex 32)/" .env
nano .env    # set NETSYNC_PUBLIC_URL to http://<container-ip>:8080
docker compose up -d --build
docker compose logs api | grep -A1 "initial user"
```

Open `http://<container-ip>:8080`.

## 4. Point devices at it

- **SNMP**: allow the container IP in each device's SNMP ACL.
- **Syslog**: send logs to `<container-ip>` on UDP 514. For example, on MikroTik:
  `/system logging action set remote remote=<ip>`. On Cisco: `logging host <ip>`.

## Updating

```bash
cd /opt/netsync && git pull && docker compose up -d --build
```

## Troubleshooting

- *Latency is empty / ping permission errors*: unprivileged LXCs sometimes block the
  `net.ipv4.ping_group_range` sysctl. Either remove the `sysctls` block from the worker in
  `docker-compose.yml` and add `cap_add: [NET_RAW]`, or disable the plugin with
  `NETSYNC_DISABLED_PLUGINS=latency`.
