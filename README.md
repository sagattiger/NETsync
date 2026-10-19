# NETsync

Self-hosted SNMP network monitoring. It combines Observium's device-first pages (every device and
its components on one page with tabs) with CheckMK's monitoring model (OK / WARN / CRIT / UNKNOWN
service states, threshold rules, problem views, acknowledgements, downtimes and notifications).

> Status: **milestone 1, early development.** The architecture and core features are in place,
> but they haven't been tested against real devices yet.

## Features (milestone 1)

- **SNMP v1 / v2c / v3** discovery and polling (async, 64 devices in parallel by default)
- **Vendor / OS detection**: Cisco IOS/IOS-XE/NX-OS/ASA, MikroTik, Fortinet, Palo Alto, Juniper,
  Arista, Aruba/HPE, Ubiquiti, VMware ESXi, pfSense/OPNsense, Windows, Linux, Proxmox, FreeBSD
- **Device pages**: Overview, Ports (traffic, errors, utilization), Health (CPU, memory, storage),
  Services, Latency, Syslog, Events, Settings
- **Service states and threshold rules** in the CheckMK style (per check, device group and item regex,
  with priorities), plus a problems dashboard and live updates over websocket
- **Alerts**: email, Telegram, webhook; acknowledgements; scheduled downtimes
- **Syslog receiver** (UDP/TCP 514, RFC 3164 + RFC 5424) that links messages to devices
- **SmokePing-style latency**: RTT min/avg/max, jitter, packet loss
- **Users, roles** (admin / operator / viewer) and **device groups** that limit what each user sees
- **Plugin system**: everything above is a plugin, see [docs/PLUGINS.md](docs/PLUGINS.md)
- **Cluster ready**: every poller is a *node*. Today one node runs next to the panel; later many
  nodes can report to one central panel.

## Stack

| Part | Tech |
|---|---|
| API | Python 3.12, FastAPI, SQLAlchemy (async) |
| Poller / collectors | asyncio, pysnmp 7, icmplib |
| Storage | PostgreSQL 16 + TimescaleDB (metrics, syslog and state history as hypertables with retention) |
| Queue / live events | Redis |
| UI | React 18, TypeScript, Tailwind, ECharts |

Metrics go into a TimescaleDB hypertable instead of RRD files. Retention is configurable
(metrics 90 days, syslog 30 days and state history 1 year by default), and backups are a plain
`pg_dump`.

## Quick start (Docker)

```bash
git clone https://github.com/sagattiger/NETsync.git
cd NETsync
cp .env.example .env        # set POSTGRES_PASSWORD and NETSYNC_SECRET_KEY
docker compose up -d --build
docker compose logs api | grep "initial user"   # one-time admin password
```

Open `http://<host>:8080`, log in as `admin`, add a device, and the first discovery runs immediately.

For deploying to a Proxmox LXC container, see [docs/DEPLOY-LXC.md](docs/DEPLOY-LXC.md).

## Layout

```
backend/netsync/
  api/            REST API + websocket
  plugins/        plugin API, registry, built-in plugins
    builtin/      system, interfaces, host_resources, syslog, latency, notify
  poller/         discovery/poll pipeline + node worker
  rules/          threshold engine
  snmp/           pysnmp wrapper + vendor profiles
  alerting.py     downtimes, acks, notification dispatch
frontend/         React UI
mibs/             vendor MIB folders
docs/             architecture, plugins, deployment
```

## Development

```bash
# backend
cd backend && python -m venv .venv && . .venv/bin/activate && pip install -e .[dev]
docker compose up -d db redis
NETSYNC_DATABASE_URL=postgresql+asyncpg://netsync:<pw>@localhost:5432/netsync netsync-api
netsync-worker
pytest

# frontend (proxies /api to localhost:8000)
cd frontend && npm install && npm run dev
```

## Roadmap

- **M2**: YAML vendor definitions (CPU/memory/sensors per vendor), ENTITY-SENSOR / vendor health
  sensors, MIB compiler + SNMP browser, SNMP traps, database migrations (Alembic)
- **M3**: NetFlow / sFlow / IPFIX collector, config backups (RANCID/Oxidized style), Docker container monitoring
- **M4**: Cluster mode: remote nodes, central panel, node-to-panel API with tokens
