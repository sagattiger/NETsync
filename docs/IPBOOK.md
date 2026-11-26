# IP Book

IP Book keeps your networks, the IP addresses in them and what uses each one: the service, where it runs, how to
reach it and how to log in. Discovery fills in most of it, you add the rest, and NETsync pings every address.
It's a built-in plugin: **IP Book** in the sidebar (`/ipbook`).

## The page

- **Left:** a search box (finds any IP, host name, service, URL or note, also by prefix `10.0.1.` or network
  `10.0.1.0/24`), **All entries**, **No network** (entries whose IPs are in no known network), then every network
  with how full it is and a ⚠ count.
- **Right:** the chosen network's header (icon, title, description, VLAN, gateway, DNS, used/free, a map of its
  addresses, warnings) and its entries. The column holding the address that's in this network is highlighted.
- On phones the network list becomes a drop-down above the list.

## Who sees what

| | Admin | Operator | Viewer |
|---|---|---|---|
| See entries and networks | all | not sensitive ones | not sensitive ones |
| See passwords and secrets | one at a time (show / copy, logged) | never | never |
| Add, edit, delete entries, networks, columns; import | yes | no | no |
| Press **Ping** | yes | yes | yes |

Mark an entry **🔒 Sensitive** and only admins see it at all. Secrets are encrypted in the database with the server's
`NETSYNC_SECRET_KEY` (changing that key makes them unreadable). The list never contains a secret's value, only whether
one is saved; every show or copy is recorded (who, which entry, which column, when). Editing an entry and leaving a
password field empty keeps the saved password; **Clear** removes it.

## Learned and manual

After each device discovery NETsync creates or refreshes a **learned** entry for the device: host name, service name
and logo (from the device's application), hypervisor, type (LXC / VM / Device), VMID, OS, IP Mgmt (the address it's
polled on), IP Lan and other addresses, URL and port. It also learns the IPv4 networks of the device's ports
(not loopback, link-local, /32 or wider than /16). IPv6 networks are added by hand.

Anything you type wins: discovery never changes a field you've set. When discovery disagrees with a value that came
from an import, the entry shows **Discovery says something different** with **Keep mine** / **Use discovered**.
An entry whose device isn't discovered for 7 days is flagged, never deleted. Deleting a learned network hides it so
discovery doesn't bring it back.

## Shared addresses

Some entries rightly share an IP: Docker apps on their host, several apps on one container, services behind one NAT
address. Set **Runs on** in the entry to the host entry: an entry and the ones that run on it can share IPs. An entry
with **NAT = yes** never counts its IP Wan as a duplicate. Anything else sharing an IP is flagged as a duplicate.

## Warnings

Overlapping networks · an IP on two entries · an IP that's also on a different discovered device · a private IP in no
network · a learned entry no longer discovered · a network over 90 % used · a value discovery disagrees with.
Warnings are badges only; they don't send notifications. Operators and viewers see a warning that involves a
sensitive entry as "Conflict with a restricted entry".

## Health and alerts

Every IP in the list is pinged every 5 minutes (Plugins → IP Book → settings, 1–60). An address is **down** after 3
missed pings in a row and up again on the first answer. **Ping** on an entry pings it now.

**Alert when down** is off by default. Turn it on for a network (all its entries) or for one entry (on / off / as
its network says). Then an IP that stops answering becomes a problem in Problems and goes through your notification
rules (problem type **IP Book addresses**), with acknowledge and downtime like any other problem. A sensitive entry's
problem is named only "IP Book: sensitive entry #N".

## Columns

The built-in columns (Service Name, Hypervisor, Type, OS, VMID, HA, Device / Hostname, IP Mgmt, IP Wan, NAT, IP Lan,
Internal/Public FQDN, Public URLs, SSL, MGMT or Internal URLs, http/https port, Web/OS user and password, DB
password, Enable Secret, AAA, Telnet, SSH, Winbox, Description) can be renamed, given an icon, hidden and reordered
(**Columns**). Admins add their own columns: text, long text, number, URL(s), IP (pinged and checked like the others),
port, secret (encrypted, admins only), yes/no or a choice list. Deleting a column deletes its values.

## Importing a spreadsheet

**Import** takes a CSV or Excel (.xlsx) file up to 5 MB:

1. Upload. A title or banner above the column names is fine; the first row naming at least three known columns is the
   header.
2. Match each column to an IP Book column (pre-filled by name), make it a new column, or skip it.
3. Preview: what will be added, merged with discovered entries, flagged for review, and networks to add for private
   addresses in no known network (/24, untick what you don't want; public addresses never create networks).
4. Import.

Clean-up on the way in: `N/A`, `-` and empty become blank; `S`/`N`, `Sim`/`Não`, `Y`/`N`, `yes`/`no` become yes/no;
other text such as `default` is kept. An old Type column mixing kinds and systems is split: `LXC Container` → LXC,
`VM Machine` → VM, `Docker` → Docker, anything else (`RouterOS`, `Debian 13`) → Type Device with that OS. Rows match
discovered entries by host name (with or without the domain), or by IP when only one row has it.
