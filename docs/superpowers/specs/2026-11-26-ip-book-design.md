# IP Book — design

A built-in NETsync plugin that keeps the list of networks, IP addresses and what uses each one: the service, where it
runs, how to reach it and how to log in. It replaces the team's spreadsheet.

Status: design approved by the owner (approach A, built-in plugin). Date: 2026-11-26.

## Why

Today the list lives in a spreadsheet. It goes out of date because updating it is a separate chore nobody does, and
networks and addresses aren't controlled in one place. NETsync is opened every day and already discovers most of
the facts (hostnames, IPs with their prefixes, Proxmox host, LXC/VM, VMID, application name, logo, URL, port), so a
list inside NETsync mostly keeps itself current. People fill in only what discovery can't know (WAN IPs, NAT, public
URLs, logins).

Success: the spreadsheet is imported once and never opened again; each network's page shows who uses which IP and
whether it answers; conflicts (duplicate IPs, overlapping networks) are visible without anyone looking for them.

## Goals

- Networks (manual and learned) with a header: icon, title, description, VLAN, gateway, DNS, usage, address grid,
  warning badges.
- Rows (one per service/host, several IPs per row) with the built-in columns below plus admin-defined custom columns.
- Learned rows and networks from discovery; manual rows and networks; values typed by people always win.
- Ping every IP in the list, show health and response time, a Ping button per row; optional "Alert when down"
  that turns an IP that stops answering into a normal NETsync problem.
- Warnings: overlap, duplicates, IP outside every network, learned row no longer discovered, network over 90 % full.
- Import the existing spreadsheet (CSV or Excel) with a column-mapping step and a preview.
- Passwords and secrets encrypted, admin-only, revealed or copied one at a time and audited. Rows marked sensitive are
  admin-only.
- Search across all networks and rows.

## Non-goals (v1)

- Finding hosts NETsync doesn't monitor (ARP/neighbour tables, network scans). People add those rows by hand.
- DHCP/DNS integration, reserving addresses from other systems, IPv6 address grids (IPv6 networks and IPs are
  stored, pinged and checked; only the per-address grid is IPv4-only).
- Exporting the list (a CSV export would be a way for secrets to leave; can come later without secrets).
- Per-user or per-group permissions beyond NETsync's roles.
- One learned row per Docker container (containers usually share their host's IP; "Docker" exists as a type for
  manual rows).

## Anti-goals (failure even if it works)

- A secret or a sensitive row reaching a non-admin anywhere: list/search APIs, problem output, notifications,
  the AI coworker and tool hub/MCP, the public API, logs, error messages, browser storage.
- Discovery overwriting or deleting something a person typed, or deleting rows on its own.
- Real data in the public repo (tests and docs use example networks such as 192.0.2.0/24, 198.51.100.0/24,
  10.0.0.0/24 and invented names).
- The page becoming slow or the server heavier: it runs on a 4 GB LXC; a few thousand IPs must stay cheap.

## Constraints

- NETsync stack: FastAPI + SQLAlchemy async on TimescaleDB, Redis, React/Vite/Tailwind. Built-in plugin like
  `crowdsec` (`netsync/plugins/builtin/ipbook/`), its router mounted at `/api/plugins/ipbook`, a page at `/ipbook`,
  a sidebar entry.
- New tables via `create_all`; later column additions via `ADDED_COLUMNS` in `db.py`.
- Secrets encrypted with `netsync.probing.secrets.encrypt/decrypt` (the key NETsync already uses for probe and
  CrowdSec secrets).
- Pinging uses `icmplib.async_multiping` in the worker, as the latency plugin does (unprivileged ICMP is already set
  up in the worker container).
- Alerts reuse services/state changes: a virtual device (like probes and CrowdSec sources) so Problems,
  notification rules, acknowledge and downtime work unchanged. Add `"ipbook"` to `VIRTUAL_DEVICE_TYPES` so it stays
  out of SNMP polling, device lists and tools.
- Roles: admin, operator, viewer (`require(Role.X)`).

## Approaches considered

- **A. Built-in plugin (chosen).** Own tables in the NETsync DB, a discovery hook, the worker's ping, services for
  alerts, the existing secret encryption. Least new machinery; fits how CrowdSec and probes are built. Sensitive data
  sits in the main DB, protected by encryption and admin-only access.
- **B. Container plugin from the store.** Own container and DB, talks to NETsync only over the API. Secrets in a
  separate box, but no direct discovery or Problems hooks: learned rows would need polling and alerts a separate path.
  More code, slower updates.
- **Dropped: sync with an existing IPAM (phpIPAM, NetBox).** Works against the goal of one place used daily; another
  app named "IP PAM" already exists in their stack.

## Decided with the owner

- Name **IP Book** ("IP PAM" is taken).
- Layout B: networks listed on the left (icon, title, CIDR, "+ Add network"), search above it; the selected network's
  header and its rows on the right. Pseudo-entries at the top of the list: **All rows** and **No network** (rows
  whose IPs fall in no known network).
- One row per service/host with several IPs. A row appears under **every** network that contains one of its IP-typed
  values; it is one record, edited once. The column holding the matching IP is highlighted in that network's view.
- Columns: the built-in set below (show/hide, reorder, rename) **plus admin-defined custom columns** with a type.
- Permissions: **only admins** create, edit or delete networks, rows and columns, and only admins see secrets and
  sensitive rows. Operators and viewers have read-only access to non-sensitive rows, never see secret values, and may
  press **Ping** (it changes nothing).
- Health: every IP pinged; an **"Alert when down"** switch, **off by default**, per network (applies to its rows)
  and per row (overrides the network: on / off / inherit). When on, an IP that stops answering becomes a problem in
  Problems and goes through notification rules.
- Import: one sheet with all networks, the header row somewhere below a title/banner; columns already matching the
  built-in set. Merge with discovery; conflicts flagged for review; preview before saving.
- The type column is split: **Type** = Device / VM / LXC / Docker; the operating system goes to an **OS** column.

## Columns

Built-in columns (key, label, type). Secret types are encrypted and admin-only.

| key | label | type |
|---|---|---|
| service | Service Name (text + logo) | service |
| hypervisor | Hypervisor (hostname + logo) | device-ref |
| type | Type | choice: Device, VM, LXC, Docker |
| os | OS | text |
| vmid | VMID | number |
| ha | HA | yes/no |
| hostname | Device / Hostname | text |
| ip_mgmt | IP Mgmt | ip |
| ip_wan | IP Wan | ip |
| nat | NAT | yes/no |
| ip_lan | IP Lan | ip |
| fqdn_internal | Internal FQDN | text |
| fqdn_public | Public FQDN | text |
| urls_public | Public URLs | url list |
| ssl | SSL | yes/no |
| urls_internal | MGMT or Internal URLs | url list |
| http_port | http port | port |
| https_port | https port | port |
| web_user | Web User | text |
| web_pass | Web Pass | secret |
| os_user | OS User | text |
| os_pass | OS Password | secret |
| db_pass | DB Password | secret |
| enable_secret | Enable Secret | secret |
| aaa | AAA | text |
| telnet_port | Telnet / Port | port |
| ssh_port | SSH / Port | port |
| winbox | Winbox | port |
| description | Description | long text |

Custom column types: text, long text, number, url, ip, port, secret, yes/no, choice (admin-defined list). A custom
`ip` column is pinged and duplicate-checked like the built-in ones; a custom `secret` column is encrypted and
admin-only. Every column has an optional icon (from NETsync's icon set) shown in the header. Built-in columns can't
be deleted, only hidden; custom columns can be deleted (with a confirmation that names how many rows have a value).

## Data model (proposed)

- `ipbook_networks`: id, cidr (unique), title, description, icon, vlan, gateway, dns (text), alert_when_down (bool,
  default false), source (`learned` | `manual`), hidden (bool; a learned network the admin removed stays hidden so
  discovery doesn't bring it back), created_at, updated_at.
- `ipbook_columns`: id, key (unique; built-ins seeded), label, type, icon, options (JSON, for choice), position,
  hidden, builtin (bool).
- `ipbook_rows`: id, values (JSON: non-secret values by column key), secrets_enc (text: encrypted dict of secret
  values by column key), sensitive (bool), alert_when_down (nullable bool; null = inherit from the network), source
  (`learned` | `manual` | `imported`), device_id (FK devices, SET NULL; the device a learned row came from),
  learned (JSON: the last values discovery proposed), manual_keys (JSON list: columns a person has set; discovery
  never writes these), conflicts (JSON: {column: {sheet/manual value, discovered value}} awaiting review),
  missing_since (timestamp when its device stopped being discovered), runs_on_id (FK ipbook_rows, SET NULL; the
  host row, see Shared IPs), created_at, updated_at, updated_by.
- `ipbook_reveals`: id, user, row_id, column key, action (`reveal` | `copy`), time. Kept like other audit data.
- IP health: one virtual device "IP Book"; one component per (row, IP) with metrics `ping_rtt` and `ping_loss`,
  so history uses the normal metric storage and rollups. A service (check `ipbook_ping`) exists only while the
  row's effective "Alert when down" is on; it goes CRIT after 3 missed pings in a row and back to OK on the first
  answer. Its name/output carry the service name and the IP, never secrets.

The builder may change table shapes if the behaviour above is kept.

## Behaviour

**Discovery (learned rows).** After each device discovery, a hook creates or refreshes one learned row per real
(non-virtual) device: hostname, service name and logo (device app name/logo), hypervisor (from `hypervisor_id`),
type (from `virtualization`: lxc → LXC, vm → VM, else Device), VMID (`guest_id`), OS, IPs (the device's management
`ip` → IP Mgmt; other addresses from `ip_addresses` go to IP Lan when one is free, else they're listed in the row's
"other IPs" detail), app URL and port. Fields in `manual_keys` are never written; a learned value that differs from
a manual one is recorded in `conflicts` only when the row came from import (see Import), otherwise silently kept as
"discovery says …" in the row detail. A row whose device is gone or not discovered for 7 days gets `missing_since`
and a warning; it is never deleted automatically.

**Learned networks.** Built from device IPv4 addresses with their prefixes, skipping loopback, link-local,
multicast, host routes (/32) and prefixes wider than /16. *Builder's call, recorded:* IPv6 networks are not learned in
v1, because discovery doesn't store IPv6 prefixes today and adding that would change core discovery. Admins add IPv6
networks by hand; IPv6 IPs in rows are still pinged and checked. Docker's default
bridges and other networks seen only on container hosts are learned like any other; an admin hides what they don't
want (hidden learned networks stay hidden).

**Ping.** A worker service pings every IP-typed value of every row every 5 minutes (setting, 1–60), batched with
`async_multiping`, at most a few hundred in flight. Results update the row's per-IP status (up with RTT / down /
never answered) and store metrics. The **Ping** button pings one row's IPs now and returns the result (rate-limited
per user).

**Shared IPs (decided with the owner).** Several rows may rightly share an IP: Docker apps on their host's IP,
several apps on one LXC on different ports, NAT'd services behind one WAN IP. A row has an optional **Runs on** link
to another row (its host). Rows sharing an IP with the row they run on, or with siblings that run on the same row,
are not duplicates. A row with NAT = yes never counts its IP Wan as a duplicate. Any other IP on two rows is a
duplicate.

**Warnings** (computed when the page loads, shown as badges on the network and the row; no notifications):
overlapping networks; the same IP in two rows (see Shared IPs), or in a row and a different discovered device; an IP inside no
network; a learned row with `missing_since`; a network over 90 % used; an unresolved import conflict.

**Permissions** are enforced in the API, not only the UI: list/search responses for non-admins omit sensitive rows
and every secret value (secret columns come back as "set / not set" only). Admins also get secrets only through
`POST /rows/{id}/reveal {column, action}`, which returns the one value and writes an `ipbook_reveals` entry. The
plugin exposes no tools to the AI coworker or MCP in v1, and nothing on the public API.

*Builder's call, recorded:* Problems and notifications are visible to every role, so the service for a **sensitive**
row gets a neutral name and output ("IP Book: sensitive entry #123 down", no IP, no service name); admins open the
row from the problem link. Warning badges shown to non-admins count conflicts involving sensitive rows ("1 conflict
with a restricted entry") without naming them. No core Problems/notification code changes.

**Import.**
1. Upload CSV or XLSX (first sheet, or a chosen sheet), up to a few MB.
2. Header detection: the first row where at least three cells match built-in labels or keys (case and spacing
   ignored); rows above are skipped.
3. Mapping: each sheet column → a built-in column, a new custom column (type chosen), or "skip". Pre-filled by label.
4. Clean-up: `N/A`, `-`, empty → blank; `S`/`N`, `Sim`/`Não`, `Y`/`N`, `yes`/`no` → yes/no for yes/no columns;
   other text kept as is (e.g. `default`, `???`). The old mixed Type column is split: values naming a kind
   (LXC Container, VM Machine, VM, LXC, Docker) set Type; anything else (RouterOS, Debian 13) sets OS and Type =
   Device.
5. Merge: match each sheet row to a learned row by hostname (case-insensitive, with or without the domain). Match by
   IP only when exactly one sheet row has that IP and it hits exactly one learned row; otherwise the sheet row becomes
   its own entry, so several services on one host never overwrite each other. Matched: sheet values become manual values; where discovery currently says something different, the
   difference goes to `conflicts` for review. Unmatched: a new `imported` row. Empty sheet rows are skipped.
6. Preview: counts and a list of rows to create, merge and flag; nothing is saved until confirmed. Secrets are
   encrypted on save. Networks are proposed (manual) for imported **private** IPv4 addresses (RFC 1918, CGNAT) that
   fall in no known network, as /24 unless the admin edits the proposal in the preview. *Builder's call:* public IPs
   never create networks; they appear under "No network" without the "outside every network" warning (that warning
   is for private addresses only). The owner's "IP Wan" column often holds a second internal address, so all IP
   columns are treated alike.

**Search** matches service, hostname, FQDNs, URLs, description, custom text columns and IPs (exact, prefix, or CIDR
containment), across all networks; non-admins never match on sensitive rows or secrets.

## UI

- Sidebar entry "IP Book" (all roles). Page `/ipbook`, `/ipbook/:networkId`.
- Left: search, "All rows", "No network", then networks (icon, title, CIDR, a small usage bar, warning dot);
  "+ Add network" for admins.
- Right: network header (icon, title, description, VLAN, gateway, DNS, used/free, address grid for IPv4 /20 or
  smaller, warning badges, "Alert when down" state, Edit for admins), then the rows table: status dot + RTT,
  columns with icons, learned/manual/imported tag, 🔒 on sensitive rows, masked secrets with reveal/copy for admins,
  Ping button. Horizontal scroll for many columns; column visibility and order are shared settings (admin), not per
  user.
- Row editor (admin): all columns grouped (Service, Placement, Addresses, Names & URLs, Ports, Logins, Custom,
  Notes), logo picker reused from the device app logo, "Sensitive" and "Alert when down (inherit/on/off)", and a
  "Discovery says" panel with accept/keep buttons for each conflict.
- Column manager (admin): rename, icon, show/hide, reorder, add/delete custom columns.
- Import wizard (admin): upload → mapping → preview → import.
- Mobile: the network list becomes a select above the table.

## Left to the builder

- Exact table shapes, indexes and API paths, as long as behaviour and permissions above hold.
- How the address grid and the usage count treat network/broadcast addresses and reserved ranges.
- Parser library for XLSX (e.g. `openpyxl` in the backend) and the upload size limit.
- Rate limits for Ping and reveal; how long reveal audit rows are kept (follow the existing housekeeping pattern).
- Visual details, following NETsync's current look (cards, tokens, icons) and the accessibility rules already used.
- Docs: `docs/IPBOOK.md` (what it is, permissions, import, alerting) and a line in PLUGINS.md.
- Tests with invented data: permissions/secret filtering, merge/manual-wins, import clean-up and type split,
  warnings, network learning filters, alert service creation.
