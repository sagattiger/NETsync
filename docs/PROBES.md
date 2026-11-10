# Probes (active monitoring)

Probes check things that are not SNMP devices: a ping target, a TCP or UDP port, a DNS record, a website, a
JSON API, a TLS certificate, or a job that reports in (push). They work like an Uptime Kuma monitor, but each
probe is also a normal NETsync "device" behind the scenes, so it gets the usual features for free:

- **Services**: every probe has a **Status** service (up/down) and, when it is up, a **Response time** service.
  Some kinds add their own (Ping RTT / Ping loss, Certificate expiry / Certificate validity).
- **Threshold rules** apply to those services (checks `probe_status`, `probe_response`, `ping_rtt`,
  `ping_loss`, `tls_days_left`).
- **Problems, acknowledgements, comments, downtimes and notifications** work exactly as for devices.
- **Device groups**: a probe belongs to groups, and viewers/operators only see the probes of their groups.
- **Dashboards and the public API**: graphs and uptime rows (see [PUBLIC-API.md](PUBLIC-API.md)).

Only operators and admins can create or change probes. Viewers can look at them.

## Kinds

Every kind has the common settings described in [Behaviour](#behaviour). The form only shows the fields of
the chosen kind, and **Test now** runs the configuration once without saving it.

### Ping (`icmp`)

| Field | |
|---|---|
| Host or IP | IPv4, IPv6 or hostname (resolved on every check) |
| Pings per round | 1–20 (default 5) |

Stores `ping_min`, `ping_avg`, `ping_max`, `ping_jitter`, `ping_loss` and `response_ms` (= avg).
Services: Ping RTT (default WARN 150 / CRIT 300 ms) and Ping loss (10 / 50 %).

### TCP port (`tcp`)

| Field | |
|---|---|
| Host, port | e.g. `mail.example.com`, `25` |
| TLS | do a TLS handshake after connecting; records the certificate (see TLS) |
| Ignore TLS errors | with TLS: an untrusted certificate doesn't mark the probe down |
| Send | text sent after connecting; `\r`, `\n`, `\t` escapes, e.g. `QUIT\r\n` |
| Expect | substring (or regex) expected in the first 4 KB received, e.g. `220` (SMTP) or `SSH-` |

Metric `connect_ms`. Example: SMTP banner check = host `mail.example.com`, port `25`, expect `220`.

### UDP port (`udp`)

| Field | |
|---|---|
| Host, port | |
| Payload | text (escapes as above) or hex (`de ad be ef`) |
| Expected reply | substring, regex or hex bytes |

**Without an expected reply, "up" only means that no ICMP port-unreachable or socket error came back** within
2 seconds. UDP has no handshake, so a firewall that silently drops packets looks the same as a working service.
Set a payload and an expected reply whenever the service answers (DNS, NTP, game servers, SIP OPTIONS...).

### DNS (`dns`)

| Field | |
|---|---|
| Name | e.g. `example.com`, `_sip._tcp.example.com`; for PTR enter the IP address |
| Record type | A, AAAA, CNAME, MX, TXT, NS, SOA, PTR, CAA, SRV |
| Resolver | empty = the system resolver, or a server IP (and port, default 53). UDP, with TCP fallback when the answer is truncated |
| Expected values | optional, one per line; **any** or **all** must be in the answer |

Values are compared case-insensitively, without a trailing dot. For MX, SRV and CAA an expected value may be
just the host (`mail.example.com`) instead of the whole record (`10 mail.example.com`).
Metrics `dns_query_ms` and `dns_records`. Down on NXDOMAIN, no records, SERVFAIL, timeout or a mismatch.

### HTTP(S) (`http`)

| Field | |
|---|---|
| URL | `http://` or `https://` only; no credentials in the URL |
| Method | GET, HEAD, POST, PUT, PATCH, DELETE, OPTIONS |
| Accepted status codes | lists and ranges, default `200-299`, e.g. `200-299,301` |
| Keyword | present (or **must be absent**), optionally case-insensitive; searched in the first 1 MB |
| Follow redirects | on by default, at most 10 |
| Ignore TLS errors | off by default (the form warns when it is on) |
| Authentication | none, basic (user + password), bearer token, or a custom header (name + value) |
| Request headers | any headers (stored encrypted) |
| Body | raw, JSON or form; can be marked **secret** (stored encrypted) |
| Certificate WARN/CRIT days | https only, see TLS |

At most 1 MB of the response is read. Metrics `response_ms` (total), `ttfb_ms`, `status_code`, `body_bytes`;
https URLs also record the certificate and add the Certificate expiry / validity services automatically.

### JSON API (`json`)

An HTTP(S) probe (all fields above) plus up to 20 **assertions** on the JSON response; all must pass.

| Path | Operators | Value |
|---|---|---|
| `data.items[0].status`, `meta["x.y"]`, `$.count` | `==` `!=` `<` `<=` `>` `>=` `contains` `not contains` `regex` `exists` `not exists` | compared as JSON when it parses (`42`, `true`, `null`, `"text"`), else as text |

Example: `status == ok`, `data.queue_depth < 100`, `version regex ^2\.`, `errors not exists`.
When an assertion fails the message names it (`assertion failed: data.status == ok`), and **Test now** shows
each assertion with the value that was actually found.

### TLS certificate (`tls`)

| Field | |
|---|---|
| Host, port | port default 443 |
| SNI / hostname | default: the host |
| STARTTLS | none, SMTP, IMAP, POP3 or FTP (for servers on their plain ports) |
| WARN / CRIT days | per probe; empty = threshold rules for `tls_days_left` (default WARN < 21, CRIT < 7 days) |

Records days left, expiry date, issuer, subject CN and SANs, hostname match, chain validity (verified against
the system CAs), TLS version and key type/size; the probe page shows them in a certificate panel.
**DOWN** when the certificate is expired, untrusted (e.g. self-signed) or doesn't match the hostname.
The **Certificate expiry** service turns WARN and then CRIT at the thresholds; each crossing is a state change,
so a notification rule sends one message at WARN and another at CRIT (with the days left in the message).
Notification rules only send WARN messages if their minimum state is WARN.

### Push / heartbeat (`push`)

NETsync creates a secret URL; your job (cron, backup script, CI) calls it:

```bash
curl -fsS "https://netsync.example.com/api/push/nsp_xxxxxxxx?status=up&msg=OK&ping=" >/dev/null
```

- `GET` or `POST /api/push/<token>` with `status=up|down` (default up), `msg` (up to 200 characters) and
  `ping` (a duration in ms, shown as the response time). **No login**: the token is the secret.
- The probe is **DOWN when no push arrives within interval + grace** (grace default 30 s), or when a push says
  `status=down`.
- The URL is shown **once** (when the probe is created, or with **New URL** on the probe page, which also
  disables the old one). Only a SHA-256 hash is stored.
- Rate limit: 60 pushes per minute per token and 600 per minute per client address (`429` beyond). Unknown,
  replaced and paused tokens all get `404`.

### Later kinds

SMTP/IMAP logins, MQTT, WebSocket, gRPC health, game servers and Docker containers are not built yet. A kind
is one file in `backend/netsync/probing/checkers/` (a `Checker` with `validate` and `check`) plus a form
section in `frontend/src/pages/probes/ProbeForm.tsx`.

## Behaviour

| Setting | |
|---|---|
| Interval | 20 s – 1 h |
| Timeout | 1–120 s (always shorter than the interval) |
| Retries | consecutive failures before the probe is **DOWN** (default 1 = the first failure) |
| Retry interval | check this often while failing (default: the interval) |
| Upside down | invert up/down, e.g. a port that must stay closed. Kind-specific services are not updated then |
| Resend notification | while down, notify again every N checks (0 = only on state changes) |
| Tags, description | free text; the list filters by tag |

- **Pending**: a failure before the retries are used up is recorded as *pending* (grey/UNKNOWN beat). It doesn't
  change the services, doesn't notify and doesn't count as downtime.
- **Scheduling**: checks drift apart with ±5 % jitter (max 3 s); after a restart the backlog is spread over up
  to a minute. Each kind has its own concurrency limit (e.g. 50 HTTP checks at once) and every check has a hard
  timeout, so one slow target never holds up the others.
- **Heartbeats**: every check stores one row (time, state, response time, short message) in the `probe_beats`
  hypertable, kept for `NETSYNC_PROBE_BEATS_RETENTION_DAYS` (default 90). The probe page shows the last 100.
- **Uptime %** over 24 h, 7 d, 30 d and 1 y (and the average response time) come from an hourly continuous
  aggregate (`probe_beats_hourly`, kept 400 days). `OK`/`WARN` count as up, `CRIT` as down, pending as up.
- **Maintenance**: a downtime on the probe (Problems → downtime, as for devices) marks its checks as
  *maintenance*; they are left out of uptime % entirely, and the list shows "maintenance".
- **Notifications** use the normal notification rules and channels.

## Import from Uptime Kuma

**Probes → Import from Uptime Kuma** takes the JSON backup from Uptime Kuma (*Settings → Backup → Export*).
A preview lists what will be created, what is skipped and why, before anything is saved; you can untick
monitors. API: `POST /api/probes/import/kuma/preview` (body: the backup) and `POST /api/probes/import/kuma`
(`{"backup": ..., "names": [...]}`, operators and admins).

| Kuma monitor | NETsync probe |
|---|---|
| HTTP(s) | `http` |
| HTTP(s) - Keyword | `http` with keyword (inverted keyword = *must be absent*) |
| HTTP(s) - Json Query | `json`; a simple path (`data.status`) becomes an assertion, JSONata expressions are flagged so you add the assertion by hand |
| TCP Port | `tcp` |
| Ping | `icmp` |
| DNS | `dns` (record type, first resolver) |
| Push | `push` with a **new** push URL (shown once after the import; update the job) |
| anything else (group, docker, database, MQTT, …) | skipped, with the reason |

Mapped fields: name, interval (clamped to 20 s – 1 h, with a warning), retries (Kuma counts retries *after*
the first failure, so `maxretries + 1`), retry interval, timeout, upside down, active/paused, description, tags,
URL, method, headers, body, accepted status codes, redirects, ignore TLS, keyword, basic auth. Headers and basic
auth passwords are stored encrypted. Names that already exist in NETsync are skipped.

**Notifications are never imported**: their bot tokens and passwords stay in Uptime Kuma. The preview lists
them under *Needs setup* (name and type only) so you can recreate them under Setup → Notifications.

## Security

- Probes run from the NETsync worker, so they can reach **internal addresses on purpose** (that's the point
  of monitoring a LAN). That's why only operators and admins can create, change or test probes.
- Strict validation: hosts are IP addresses or hostnames only; URLs must be `http://` or `https://` without
  credentials; ports 1–65535; record types from a fixed list; regexes are compiled before saving; headers
  can't contain line breaks.
- Caps: 1 MB response read, at most 10 redirects, timeout ≤ 120 s, 4 KB TCP banner, 20 assertions.
- **Secrets** (passwords, tokens, custom header values, request headers, secret bodies) are encrypted at rest with
  a key derived from `NETSYNC_SECRET_KEY` (Fernet). The API never returns them: `GET` shows `has_password: true`
  and header *names* only. On `PUT`, a secret field that is left out (or sent as `********`) keeps the stored
  value; an empty string clears it. Changing `NETSYNC_SECRET_KEY` makes stored probe secrets unreadable (the
  probes then run without them until they are edited). Push tokens are stored as SHA-256 hashes.
- Secrets are never logged and are not part of messages. Check messages are short generic categories
  ("HTTP 503", "timeout", "connection refused").
- The **public API** never includes targets, URLs, headers, bodies or raw error text (see PUBLIC-API.md).

## API

App login (JWT). Viewers read; operators and admins write.

| | |
|---|---|
| `GET /api/probes?kind=&tag=&state=` | list (state: OK, WARN, CRIT, UNKNOWN, PAUSED) with uptime, cert days, sparkline |
| `GET /api/probes/kinds` | registered kinds |
| `POST /api/probes` | create (push probes return `push_token` and `push_url` once) |
| `GET/PUT/DELETE /api/probes/{id}` | read / update / delete (with its history) |
| `POST /api/probes/{id}/pause`, `/resume` | |
| `POST /api/probes/bulk` | `{"ids": [...], "action": "pause" \| "resume" \| "delete"}` |
| `POST /api/probes/test?probe_id=` | run a configuration once without saving; with `probe_id`, stored secrets fill the omitted ones |
| `GET /api/probes/{id}/heartbeats?limit=100` | last beats, oldest first |
| `GET /api/probes/{id}/uptime` | uptime % and average response time per window |
| `GET /api/probes/{id}/metrics?name=&range=` | time series, same shape as `/api/devices/{id}/metrics` |
| `POST /api/probes/{id}/push-token` | new push URL (the old one stops working) |

Example (create an HTTPS probe with a keyword and basic auth):

```json
POST /api/probes
{ "name": "Shop", "kind": "http", "target": "https://shop.example.com/health",
  "interval_s": 60, "timeout_s": 10, "retries": 3, "retry_interval_s": 20, "tags": ["web"],
  "config": { "method": "GET", "accepted_codes": "200-299", "keyword": "ok", "auth": "basic", "auth_user": "monitor",
              "warn_days": 21, "crit_days": 7 },
  "secrets": { "password": "…" } }
```

## Tests

`backend/tests/test_probe_phase1.py` … `test_probe_phase4.py` run every checker against local servers started
in the test (asyncio TCP/UDP servers, a local DNS responder, CA-signed and self-signed TLS servers incl.
STARTTLS, httpx MockTransport for HTTP) and cover retries, upside-down, jitter, resend, uptime with maintenance,
certificate thresholds, secrets encryption, size/redirect caps, the URL scheme allow-list and the public
payload. The opt-in live tests (`test_public_api_e2e.py`) cover the push endpoint and secret masking.
