# Public dashboards API

A read-only API so another application (for example a Paymenter extension that shows infrastructure
status on a public web page) can fetch selected dashboards and draw them itself.

- Only dashboards an admin marked **Public** are visible.
- Responses are built from an allow-list. They never contain hostnames, IP addresses, probe targets,
  SNMP data, sysDescr, syslog, users, comments or check output text. The only free text is what admins
  type themselves: the dashboard's public name and description, per-widget public titles, series labels
  and logos.
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

Each widget also has an **Appearance** section in the editor: a logo (search Dashboard Icons or paste an
`https://` image URL), a colour and a short label per series (e.g. Rx / Tx), the width (¼, ⅓, ½, ⅔ or full,
also by dragging the widget's right edge), the height (compact / normal / tall) and a **Compact** switch
(logo, title, current value and a small chart only). All of it is optional; widgets without it look and
serialize exactly as before.

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

### `GET /api/public/dashboards/{id}/widgets/{widget_id}?range=24h`

Just one widget, in exactly the same format as inside the dashboard response, for example to show
"Uplink traffic" and "Ping to Google" in a small section of a home page without loading the whole
dashboard. Same token, `range` values, cache header and rate limit. `404` when the dashboard is not
public or the widget id doesn't exist. Widget ids are shown in the dashboard response (`widgets[].id`).

```json
{ "id": "g1", "type": "graph", "size": "s", "cols": 4, "height": "compact", "compact": true,
  "logo": { "src": "https://cdn.jsdelivr.net/gh/homarr-labs/dashboard-icons/svg/google.svg", "alt": "Google" },
  "source": "probe", "title": "Ping to Google", "state": "OK", "unit": "ms", "area": false,
  "colors": ["#00ABFA"],
  "series": [ { "key": "avg", "name": "Google",
                "points": [["2026-11-10T13:55:00Z", 80.4, 78.9, 92.1], ["2026-11-10T14:00:00Z", 80.1, 79.0, 84.5]] } ],
  "last": { "Google": 80.1 },
  "loss_pct": 0.0 }
```

Field notes:

- `summary.state`: the worst service state across the devices used by this dashboard
  (`CRIT` > `WARN` > `UNKNOWN` > `OK`). `devices.down` counts devices that are not reachable.
- `graph.state`: the worst state of the graphed component's services (for example the port), or of the
  device for device-level graphs.
- `graph.series[]`: `key` is the series' original key (`in`/`out`, `avg`…), `name` is what to display: the
  admin's label (e.g. `Rx`/`Tx`) or, without one, the key. `last` is keyed by `name`.
- `graph.unit`: how to format values. One of `bps` (bits per second), `pct`, `ms`, `s`, `rate` (per second),
  `count`, and since the host metrics: `bytes`, `Bps` (bytes per second), `celsius`, `rpm`, `load` (load
  average, a plain number) and `duration` (seconds, e.g. uptime). Treat an unknown unit as a plain number. `last` is the newest average per series (`null` without data). Missing data gives an empty
  `points` list, never an error.
- Optional widget fields, **omitted when not set** (older widgets don't have them):
  - `cols`: width on a 12-column grid, one of `3`, `4`, `6`, `8`, `12`. When missing, derive it from `size`:
    `s` = 4, `m` = 6, `l` = 12.
  - `height`: `compact`, `normal` or `tall`. Missing means `normal`.
  - `compact`: `true` asks for a minimal rendering: logo, title, current value(s) and a small chart without
    legend or axis labels.
  - `logo`: `{ "src", "alt" }`. `src` is always `https://` (a Dashboard Icons CDN file or an admin-supplied
    URL); `alt` is the icon name, or empty.
  - `colors` (graph widgets): hex colours (`#RGB` or `#RRGGBB`), one per series in order. Fewer colours than
    series means "use your default for the rest".
- **Probe widgets** are graph widgets with `"source": "probe"`. A probe actively checks something that is not
  an SNMP device: a ping target, a TCP/UDP port, a DNS record, a website or JSON API, a TLS certificate or a
  push heartbeat (see [PROBES.md](PROBES.md)). Fields:
  - `kind`: `icmp`, `tcp`, `udp`, `dns`, `http`, `json`, `tls` or `push`.
  - `unit` and series depend on the graph: Ping latency (`ms`, series `avg`; each point is `[time, avg, min, max]`
    with the lowest and highest round-trip time of the bucket), Ping packet loss (`pct`), Response time (`ms`),
    Uptime (`pct`, one point per day for 7d and longer), Certificate days left (`count`), DNS query time (`ms`),
    HTTP status code (`count`).
  - `state` comes from the probe's checks (Status, Response time, Ping, Certificate expiry...).
  - `uptime`: `{"24h": 99.98, "7d": 99.9, "30d": 99.95}` (percent, `null` without data; maintenance excluded),
    only when there is data. `cert_days_left`: whole days, for https/tls probes. `loss_pct`: ping probes.
  - `message`: a generic category of the last check, e.g. `"HTTP 503"`, `"timeout"`, `"connection refused"`,
    `"certificate expires in 5 days"`, `"no push received"`. Anything else (custom push messages, assertion
    details, text that contains the target) is reduced to `"up"`, `"down"` or `"pending"`.
  - The series `name` defaults to the probe's name. A probe's **target, URL, headers, body and raw error text are
    never included**; if a probe's name contains its target (e.g. "8.8.8.8" or "example.com"), the generic title
    (graph name) and series key are used instead.
- **Uptime widgets** (`"type": "uptime"`) are one status-page row: the heartbeat bars and uptime % of a probe.

  ```json
  { "id": "u1", "type": "uptime", "size": "l", "cols": 12, "compact": true,
    "logo": { "src": "https://cdn.jsdelivr.net/gh/homarr-labs/dashboard-icons/svg/nginx.svg", "alt": "Nginx" },
    "title": "Website", "state": "OK", "kind": "http", "message": "HTTP 200",
    "uptime": { "24h": 99.98, "7d": 99.9, "30d": 99.95 },
    "cert_days_left": 42,
    "beats": [["2026-11-10T13:55:00Z", "OK", 182.4], ["2026-11-10T13:56:00Z", "CRIT", null]] }
  ```

  `beats` holds up to the last 100 checks, oldest first: `[ISO time, state, response ms or null]`. `OK`/`WARN` =
  up, `CRIT` = down, `UNKNOWN` = pending (failing, retries not used up yet). `range` doesn't apply to this widget.
- `graph.style` (optional, omitted when not set): how the admin wants the graph drawn. `area` (smooth line
  with a soft fill; the default), `line`, `spike` (sharp joins, no fill: error counts, latency spikes) or
  `range` (one thin bar per bucket from `min` to `max` with the average as a line; uses the `[t, avg, min, max]`
  points you already get). Unknown values: draw your default.
- **UI kit widgets** (since the "Glow" restyle; see `docs/design/netsync-ui-kit.svg`). Clients that don't
  know a `type` should skip the widget. They carry the usual `id`, `type`, `size` and the optional `cols`,
  `height`, `logo` fields. `unit` is formatted as for graphs (`bps`, `pct`, `ms`, `s`, `rate`, `count`).
  - `kpi`: one big number. `value` is the newest average over `range` (or the probe's uptime % over the
    admin's window, then `unit` is `pct`), `caption` a short text for under it, `spark` up to 24 averages
    oldest first (no timestamps; may be empty), `state` as for graphs.

    ```json
    { "id": "k1", "type": "kpi", "size": "s", "cols": 3, "title": "Uptime · Website",
      "value": 99.98, "unit": "pct", "caption": "last 30 days", "state": "OK",
      "spark": [100.0, 99.95, 100.0, 100.0] }
    ```
  - `gauge`: a value on a `min`..`max` scale (default 0..100) with optional `warn` / `crit` thresholds
    (`null` when unset). When `warn` > `crit`, lower is worse (e.g. uptime). `value` is **not** clamped (a
    270 ms latency on a 0..100 gauge stays 270: draw the arc full). `state` is `OK`, `WARN`, `CRIT` from the
    thresholds, or `UNKNOWN` without data.

    ```json
    { "id": "g2", "type": "gauge", "size": "s", "title": "CPU utilization",
      "value": 87.0, "unit": "pct", "min": 0.0, "max": 100.0, "warn": 80, "crit": 90, "state": "WARN" }
    ```
  - `rings`: 1–4 percentages side by side (e.g. the CPU of each node). `value` is clamped to 0..100 and
    `null` without data. `color` (hex) only when the admin picked one. `label` is the admin's label, else the
    component name (e.g. `Physical memory`), the probe's public name, or the metric name.

    ```json
    { "id": "r1", "type": "rings", "size": "m", "title": "Health",
      "items": [{ "label": "pve001", "value": 74.0 }, { "label": "pve002", "value": 48.0, "color": "#FF7A3D" }] }
    ```
  - `donut`: services by state. `items` lists the states with a count above 0, in the order OK, WARN, CRIT,
    UNKNOWN; `state` is
    `OK`, `WARN`, `CRIT` or `UNKNOWN` (use it for the colour), `label` is `ok`, `warning`, `critical` or
    `unknown`. `center` is the total and `caption` the word for under it (`services`, or `open` for open
    problems). Counts the widget's device, or every device and probe used by this dashboard.

    ```json
    { "id": "d1", "type": "donut", "size": "s", "title": "Problems", "state": "CRIT",
      "items": [{ "label": "warning", "value": 7, "state": "WARN" }, { "label": "critical", "value": 5, "state": "CRIT" }],
      "center": 12, "caption": "open" }
    ```
  - `bars`: the top N (1–10, default 5) items by their newest value, highest first. Items are a device's
    interfaces (or filesystems, memory pools) by name, or probes by their public name (`Probe 2` when the
    name would reveal the target). `value` is never negative; `null` without a recent sample (sorted last).

    ```json
    { "id": "b1", "type": "bars", "size": "s", "title": "Interface traffic", "unit": "bps",
      "items": [{ "label": "ether1", "value": 84000000.0 }, { "label": "sfp1", "value": 63000000.0 }] }
    ```
  - None of these contain hostnames, IPs, probe targets or URLs, device/component/probe ids, or check output.
- `summary` also counts the services of probes used by the dashboard; `devices` counts real devices only.
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
  | jq '{name, state: .summary.state, widgets: [.widgets[] | {id, title, state}]}'

# one widget, e.g. for a home page section
curl -s -H "Authorization: Bearer $TOKEN" "https://netsync.example.com/api/public/dashboards/3/widgets/g1?range=24h" \
  | jq '{title, state, last, loss_pct}'
```

Cache responses on the website side for about 30 seconds (the `Cache-Control` header says so). Polling
every 30–60 s stays far below the rate limit.

## 5. Probes (NETsync side)

**Probes** (sidebar) are NETsync's active monitoring (ping, TCP, UDP, DNS, HTTP(S), JSON APIs, TLS certificates
and push heartbeats). Everything about them is in [PROBES.md](PROBES.md). On a probe's page, **Add to dashboard**
adds its graph or an uptime row; in the widget editor pick a graph under *Probes* or the **Uptime** widget type.

## 6. Tests

- `backend/tests/test_public_api.py`: token format, hashing and validity (revoked, expired), range
  buckets, presets, publishing rights, and the payload builder. The payload test checks that no hostname,
  IP or check output appears unless an admin put it in a public title, and that the problems widget only
  lists the dashboard's devices.
- `backend/tests/test_public_api_e2e.py`: runs against a live NETsync when `NETSYNC_E2E_URL` and
  `NETSYNC_E2E_ADMIN_JWT` are set. It checks that a token reads public dashboards but gets `401` from
  `/api/devices`, `/api/syslog` and the rest; that revoked and expired tokens get `401`; that non-public ids
  give `404`; and that a JWT is rejected by `/api/public`. It also creates a probe of 127.0.0.1, waits for its
  metrics, and checks the single-widget endpoint (labels, logo, cols, no target in the response, 404s).
- `backend/tests/test_probe_phase4.py`: the new presets, uptime widgets (beats, windows, single widget), probe
  fields in graph widgets, the public message allow-list, and that no target, URL or host ever appears.
- `backend/tests/test_ui_kit_widgets.py`: the kpi, gauge, rings, donut and bars widgets and the graph `style`:
  validation (types, limits, gauge min < max), thresholds, ring clamping, bar sorting and limits, labels, and
  that no hostname, IP, target or id appears in their payloads.
- `backend/tests/test_probes_widgets.py`: probe target validation, probe check results, widget colour /
  label / logo / cols validation, the Dashboard Icons index, probe and appearance fields in the public payload
  (and never the probe target), the single-widget build, and that old widgets serialize unchanged.
