# CrowdSec plugin

Shows how many attackers [CrowdSec](https://www.crowdsec.net/) is blocking, from one or more CrowdSec **Local APIs**
(LAPI). Data flows one way: **CrowdSec → NETsync → your dashboards** (and, through the public API, a status page such
as the Paymenter extension). Nothing ever calls CrowdSec from a public page.

## Why a built-in plugin

NETsync has two kinds of plugins ([PLUGINS.md](PLUGINS.md), [PLUGIN-PROTOCOL.md](PLUGIN-PROTOCOL.md)). Container
plugins run in their own container, offer tools to the AI/MCP hub and **get no database access**. CrowdSec numbers
must become time series, problems and dashboard widgets, and only in-process (built-in) plugins can write metrics and
services. So CrowdSec is a built-in plugin (`netsync/plugins/builtin/crowdsec`), like probes. It needs no extra
container or third-party code: one HTTP GET per source per interval.

## What it reads

`GET <LAPI>/v1/decisions` with a **bouncer API key** (`X-Api-Key` header). A bouncer key can only *read* decisions:
NETsync can never add or remove a ban. Format checked against CrowdSec's `localapi_swagger.yaml` (CrowdSec 1.8.x):
a JSON array of decisions with `id`, `uuid`, `origin`, `type`, `scope`, `value`, `duration`, `until`, `scenario`,
`simulated`. Some versions answer `null` instead of `[]` when nothing is banned; both are handled.

- **Local bans**: `type = ban` decisions from our own CrowdSec (`crowdsec`, `cscli`, `appsec`, `console`…),
  deduplicated by address.
- **Community bans**: origins `CAPI` and `lists:*` (community blocklist and subscribed lists).
- **Other remediations** (captcha, throttle…) and **simulated** decisions are counted separately and never as blocked.
- **New bans**: local decisions with an id above the highest id seen on the previous read. The first read only sets
  the starting point. A ban that starts and ends between two reads is not seen. After a CrowdSec database reset
  (ids start over) counting continues from the new ids.
- **Scenarios**: why the locally banned addresses are banned (`crowdsecurity/ssh-bf`…), top 30 per read.
- **Countries: not available.** Decisions carry no country; only alerts do, and reading alerts needs machine
  credentials, which can also write. NETsync only uses read-only access, so it has no per-country numbers.

Addresses are only kept masked (`203.0.113.x`, `2001:db8:1::x`) for the newest 20 local bans, shown to operators and
admins on the CrowdSec page. They are never stored in metrics, never sent to the public API and never logged.

## Storage

Each source owns a virtual device (`device_type = "crowdsec"`, never SNMP polled, pinged or listed under Devices).
Everything below uses NETsync's normal machinery, so housekeeping keeps the data like any device's (every poll for
30 days, hourly averages for 1 year, daily for 5 years by default):

| Metric | Meaning |
|---|---|
| `cs_local` | local bans active now |
| `cs_community` | community / list bans active now |
| `cs_total` | distinct banned addresses (local ∪ community) |
| `cs_other` | captcha / throttle decisions |
| `cs_new` | new local bans since the previous read |
| `cs_new_total` | running count of new local bans (bans per day = daily max − previous max, works from rollups) |
| `bans` on each `cs_scenario` component | local bans active now for that scenario |
| `response_ms` | LAPI response time |

Services (problems, rules, downtimes and notifications work as usual):

- **LAPI**: CRIT when the LAPI is unreachable, refuses the key (HTTP 401/403), isn't a LAPI (404) or answers
  something that isn't a decision list. The last good numbers are kept meanwhile.
- **New bans**: value = new local bans since the previous read. WARN when it reaches *Warn at new bans per read* in
  the plugin settings (0 = off). Threshold rules on check `crowdsec_new_bans` work too.

Graph presets: *Active bans*, *New bans per read* and *Active bans by scenario* (group CrowdSec), usable in graph,
kpi and gauge widgets of the source's device.

## Set up

1. On the CrowdSec host that runs the LAPI: `sudo cscli bouncers add netsync-ro`. Copy the key (shown once).
2. Make the LAPI reachable from the NETsync server only (`api.server.listen_uri` and a firewall rule).
3. In NETsync: **CrowdSec** (sidebar) → **Add source**: a name, the LAPI address (`http://<lapi>:8080`) and the key.
   **Test** reads once without saving. The key is stored encrypted (Fernet, key derived from `NETSYNC_SECRET_KEY`)
   and never shown again; leave the field as is when editing to keep it.
4. **Settings** on the same page: read interval (60–3600 s, default 300), timeout, the new-bans warning and the time
   zone used for "per day" (e.g. `America/Sao_Paulo`).

## Dashboards and the public API

Add a **CrowdSec** widget to any dashboard. Tick sources to use only those; none ticked means every enabled source,
added up. On a public dashboard give it a **public title**. The widget's public form (see
[PUBLIC-API.md](PUBLIC-API.md)) has totals, per-day new bans and scenario keys only: never addresses, source names,
LAPI URLs or error texts.

## API (signed in)

Mounted at `/api/plugins/crowdsec`:

| Request | Who | |
|---|---|---|
| `GET /overview` | everyone | sources with totals and services, combined totals (URLs for admins, masked recent bans for operators+) |
| `GET /widget?ids=1,2&limit=5` | everyone | a widget's data in the public shape |
| `POST /sources`, `PUT /sources/{id}`, `DELETE /sources/{id}` | admin | `{name, url, api_key, enabled}`; `api_key` omitted or `********` keeps the stored key |
| `POST /test` | admin | `{url, api_key?, source_id?}`: read once, totals only |
| `POST /sources/{id}/run` | admin | read now |

## Tests

`backend/tests/test_crowdsec.py` uses fake LAPI answers: a normal list, `null`, `[]`, timeouts, connection refused,
HTTP 401/403/404/500/302, invalid JSON, objects instead of lists, simulated and captcha decisions, new-ban counting
across a database reset, the per-day arithmetic, and that the public widget contains no address, source name or URL.
