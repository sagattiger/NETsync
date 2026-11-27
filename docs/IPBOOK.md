# IP Book

IP Book keeps your networks, the IP addresses in them and what uses each one: the service, where it runs, how to
reach it and how to log in. Discovery fills in most of it, you add the rest, and NETsync pings every address.
It's a built-in plugin: **IP Book** in the sidebar (`/ipbook`).

## Books

IP Book holds **books**, created with **+ New book** (admins). Nothing exists until you create it.

- **IP book**: one network (up to /20). Every address is a row, like a range sheet: status (subnet, gateway,
  available, used, live, reserved, down, broadcast), the address, its last **Ping** (response time, or down),
  Hostname, Internal ID, Device, Location, Interface Name, Mac-Address, Info. and Last Change. ISP Customer, End
  Customer, Private IP and Last Mile Provider exist too but start hidden: show them under **Columns**. Mark an
  address **Reserved** to keep it free. Filter All / Used / Available.
- **Service book**: a list of services, the entries described below (logins, URLs, ports, encrypted passwords).
  Have as many as you like, e.g. one per stack or customer.

How an IP book fills itself:

- **Discovery** fills Hostname, Device, Interface Name and MAC for addresses it finds on the devices NETsync
  monitors, and the hostname gets the device's OS logo and a link to it. Anything you type wins. When a device no
  longer has an address, what discovery wrote is removed and the address is available again.
- **Network scan** (on by default, switch it off under **Edit book**): every few minutes every address of the book is
  pinged. One that answers but has nothing written on it and is on no monitored device shows as **live**, with its
  name from reverse DNS when it has one. A live address that stops answering for three rounds goes back to available
  (it isn't "down": nobody said something should be there). Addresses with something written on them are pinged
  each round too; one that stops answering is **down**, and with **Alert when down** it becomes a problem.

**Ping** and **Edit** (admins) above the list work on a selection: press one, tick the addresses (or the box in the
header for every address shown), then press it again. Ping does up to 256 addresses at a time and updates their
Ping column. Edit with several addresses writes what you change on all of them and leaves the rest as it is.

The bar at the top lists IP books, then service books, and **+ New book**; its search box finds addresses and services
across all books. Long books scroll inside the window, so the header and the sideways scrollbar stay in reach.

## Who sees what

| | Admin | Operator | Viewer |
|---|---|---|---|
| See books, entries and addresses | all | not sensitive entries | not sensitive entries |
| See passwords and secrets | one at a time (show / copy, logged) | never | never |
| Add, edit, delete books, entries, addresses, columns; import | yes | no | no |
| Press **Ping** | yes | yes | yes |

Mark an entry **🔒 Sensitive** and only admins see it at all. Secrets are encrypted in the database with the server's
`NETSYNC_SECRET_KEY` (changing that key makes them unreadable). The list never contains a secret's value, only whether
one is saved; every show or copy is recorded (who, which entry, which column, when). Editing an entry and leaving a
password field empty keeps the saved password; **Clear** removes it.

## Service entries

Service books are filled by you (or an import); discovery doesn't add service entries. Editing an entry saves only the
fields you changed.

## Shared addresses

Some entries rightly share an IP: Docker apps on their host, several apps on one container, services behind one NAT
address. Set **Runs on** in the entry to the host entry: an entry and the ones that run on it can share IPs. An entry
with **NAT = yes** never counts its IP Wan as a duplicate. Anything else sharing an IP is flagged as a duplicate.

## Warnings

In service books: an IP on two entries (see Shared addresses), an IP that's also on a different discovered device,
and a value discovery disagrees with after an import.

## Health and alerts

Every IP in the list is pinged every 5 minutes (Plugins → IP Book → settings, 1–60). An address is **down** after 3
missed pings in a row and up again on the first answer. **Ping** on an entry pings it now.

**Alert when down** is off by default. Turn it on for a book (all its entries or used addresses) or for one entry or
address (on / off / as the book says). Then an IP that stops answering becomes a problem in Problems and goes through your notification
rules (problem type **IP Book addresses**), with acknowledge and downtime like any other problem. A sensitive entry's
problem is named only "IP Book: sensitive entry #N".

## Columns

The built-in columns (Service Name, Hypervisor, Type, OS, VMID, HA, Device / Hostname, IP Mgmt, IP Wan, NAT, IP Lan,
Internal/Public FQDN, Public URLs, SSL, MGMT or Internal URLs, http/https port, Web/OS user and password, DB
password, Enable Secret, AAA, Telnet, SSH, Winbox, Description) can be renamed, given an icon, hidden and reordered
(**Columns**). Admins add their own columns: text, long text, number, URL(s), IP (pinged and checked like the others),
port, secret (encrypted, admins only), yes/no or a choice list. Deleting a column deletes its values.

## Importing a spreadsheet

**Import** (in a service book) takes a CSV or Excel (.xlsx) file up to 5 MB:

1. Upload. A title or banner above the column names is fine; the first row naming at least three known columns is the
   header.
2. Match each column to an IP Book column (pre-filled by name), make it a new column, or skip it.
3. Preview: what will be added to the service book and which entries already in it are updated.
4. Import.

Clean-up on the way in: `N/A`, `-` and empty become blank; `S`/`N`, `Sim`/`Não`, `Y`/`N`, `yes`/`no` become yes/no;
other text such as `default` is kept. An old Type column mixing kinds and systems is split: `LXC Container` → LXC,
`VM Machine` → VM, `Docker` → Docker, anything else (`RouterOS`, `Debian 13`) → Type Device with that OS. Rows match
entries already in the book by host name (with or without the domain), or by IP when only one row has it.
