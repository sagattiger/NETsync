# Public dashboards API

A read-only API so another application (for example a Paymenter extension that shows infrastructure
status on a public web page) can fetch selected dashboards and draw them itself.

- Only dashboards an admin marked **Public** are visible.
- Responses are built from an allow-list. They never contain hostnames, IP addresses, SNMP data,
  sysDescr, syslog, users, comments or check output text. The only free text is what admins type
  themselves: the dashboard's public name and description, and per-widget public titles.
- Authentication uses long-lived, read-only **API tokens** (`nst_…`). These tokens are accepted
  **only** by `/api/public/*`. Every other endpoint rejects them with `401`, so a leaked token
  can't read devices, IPs, syslog or users. The normal login (JWT) is not accepted by `/api/public/*`.

## 1. Create a token

In NETsync: **Setup → API tokens → New token** (admins only). Give it a name, optionally an expiry date,
and copy the token. It is shown **once**: only a SHA-256 hash is stored, plus the first 8 characters for
display. Revoke it from the same page at any time; a revoked or expired token gets `401`.

Via the API (admin JWT):

```bash
curl -X POST https://netsync.example.com/api/tokens \
  -H "Authorization: Bearer <admin JWT>" -H "Content-Type: application/json" \
  -d '{"name": "Paymenter status page", "expires_at": null}'
# -> {"id": 1, "name": "...", "prefix": "nst_AbCd", ..., "token": "nst_AbCdEf...40 chars"}
```

`GET /api/tokens` lists tokens (never the full token) and `DELETE /api/tokens/{id}` revokes one.

## 2. Publish a dashboard

Open a dashboard → **Edit → Settings** and switch on **Public (shown on the website)** (admins only).
When a dashboard is public you can also set:

- **Public name**: shown instead of the internal dashboard name.
- **Public title** on each widget: for example "Core router · Uplink 1". Without one, widgets get a
  generic title (the graph name such as "Interface traffic · ether1", or "Router", "Services", "Problems").
  A hostname only appears if you type it into a public title yourself.

Public dashboards show a green **public** badge in the dashboard list.

## 3. Endpoints

All requests need `Authorization: Bearer nst_…`. Responses are JSON and carry
`Cache-Control: public, max-age=30`. Each token may make **120 requests per minute** (`429` with
`Retry-After` beyond that). Unknown or non-public dashboard ids return `404`.

### `GET /api/public/dashboards`

```json
[
  { "id": 3, "name": "Network status", "description": "Core network and servers", "updated_at": "2026-11-10T14:02:11Z" }
]
```

### `GET /api/public/dashboards/{id}?range=24h`

`range` is one of `1h`, `6h`, `24h` (default), `7d`, `30d`, `1y`. Graph points are averaged into buckets of
1 min, 2 min, 5 min, 30 min, 2 h and 1 day respectively. Each point is `[ISO time, avg, min, max]`.

```json
{
  "id": 3, "name": "Network status", "description": "Core network and servers",
  "range": "24h", "generated_at": "2026-11-10T14:05:00Z",
  "summary": {
    "state": "WARN",
    "devices": { "up": 12, "down": 0 },
    "services": { "OK": 80, "WARN": 2, "CRIT": 0, "UNKNOWN": 1 }
  },
  "widgets": [
    { "id": "w1", "type": "graph", "size": "l", "title": "Core router · Uplink 1", "state": "OK",
      "unit": "bps", "area": true,
      "series": [
        { "name": "in",  "points": [["2026-11-10T13:55:00Z", 123456.0, 110000.0, 140000.0]] },
        { "name": "out", "points": [["2026-11-10T13:55:00Z", 98765.0, 90000.0, 105000.0]] }
      ],
      "last": { "in": 123456.0, "out": 98765.0 } },
    { "id": "w2", "type": "device", "size": "m", "title": "Router", "state": "OK",
      "status": "up", "uptime_seconds": 123456,
      "services": { "OK": 10, "WARN": 0, "CRIT": 0, "UNKNOWN": 0 } },
    { "id": "w3", "type": "services", "size": "m", "title": "Services",
      "items": [ { "name": "Interface ether1", "state": "OK", "since": "2026-11-09T08:00:00Z" } ] },
    { "id": "w4", "type": "problems", "size": "m", "title": "Problems",
      "items": [ { "name": "Memory", "state": "WARN", "since": "2026-11-10T09:12:40Z", "acknowledged": false } ] }
  ]
}
```

Field notes:

- `summary.state`: the worst service state across the devices used by this dashboard
  (`CRIT` > `WARN` > `UNKNOWN` > `OK`). `devices.down` counts devices that are not reachable.
- `graph.state`: the worst state of the graphed component's services (for example the port), or of the
  device for device-level graphs.
- `graph.unit`: how to format values. One of `bps` (bits per second), `pct`, `ms`, `s`, `rate` (per second)
  and `count`. `last` is the newest average per series (`null` without data). Missing data gives an empty
  `points` list, never an error.
- `services` items: every service of the widget's device, worst first. The check output text is not included.
- `problems` items: non-OK services of the widget's device, or of **every device used by this dashboard**
  when the widget has no device. Never the whole installation.

### `GET /api/presets` (app login, not token)

The graph presets (id, label, group, component kind, unit, series) used by both the NETsync UI and this API.
Defined once in `backend/netsync/presets.py`.

## 4. Example

```bash
TOKEN=nst_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx

curl -s -H "Authorization: Bearer $TOKEN" https://netsync.example.com/api/public/dashboards

curl -s -H "Authorization: Bearer $TOKEN" "https://netsync.example.com/api/public/dashboards/3?range=6h" \
  | jq '{name, state: .summary.state, widgets: [.widgets[] | {title, state}]}'
```

Cache responses on the website side for about 30 seconds (the `Cache-Control` header says so). Polling
every 30–60 s stays far below the rate limit.

## 5. Tests

- `backend/tests/test_public_api.py`: token format, hashing and validity (revoked, expired), range
  buckets, presets, publishing rights, and the payload builder. The payload test checks that no hostname,
  IP or check output appears unless an admin put it in a public title, and that the problems widget only
  lists the dashboard's devices.
- `backend/tests/test_public_api_e2e.py`: runs against a live NETsync when `NETSYNC_E2E_URL` and
  `NETSYNC_E2E_ADMIN_JWT` are set. It checks that a token reads public dashboards but gets `401` from
  `/api/devices`, `/api/syslog` and the rest; that revoked and expired tokens get `401`; that non-public ids
  give `404`; and that a JWT is rejected by `/api/public`.
