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

On a small server (4 GB RAM or less) build the images one at a time, so the builds don't push the database into
swap:

```bash
cd /opt/netsync && git pull && docker compose build api && docker compose build web && docker compose up -d
```

## Database memory

The database is set up for a 4 GB server: 512 MB `shared_buffers`, 1.5 GB `effective_cache_size`, 8 MB `work_mem`,
128 MB `maintenance_work_mem` (see the `db` service in `docker-compose.yml`). Inside an LXC container Postgres can't
size itself: its tuning tool sees the whole Proxmox host's RAM and would take far more memory than the container has,
filling RAM and swap until the container hangs. On a bigger server raise the values in `.env`, roughly a quarter of
the RAM for shared buffers and three quarters for the cache size, then `docker compose up -d db`:

```bash
PG_SHARED_BUFFERS=2GB
PG_EFFECTIVE_CACHE_SIZE=6GB
PG_WORK_MEM=16MB
PG_MAINTENANCE_WORK_MEM=512MB
```

## Troubleshooting

- *Latency is empty / ping permission errors*: unprivileged LXCs sometimes block the
  `net.ipv4.ping_group_range` sysctl. Either remove the `sysctls` block from the worker in
  `docker-compose.yml` and add `cap_add: [NET_RAW]`, or disable the plugin with
  `NETSYNC_DISABLED_PLUGINS=latency`.
