# SSH terminal

Terminals on your Linux servers inside NETsync, on each device's **Terminal** tab and on the **Terminal** page
(several sessions in tabs). There is no second login: NETsync decides what you may do, and every user works
under their **own account** on each server, so the server's own logs show who did what.

## How it works

```
browser ──(NETsync login)──► NETsync API: checks your rights on the device, signs a one-minute ticket
   │
   └──(WebSocket + ticket)──► SSH gateway plugin (own container)
                                 1. as "netsync" (key): netsync-account ensure ns-alice <level>
                                 2. you choose / type your password for that server
                                 3. as "ns-alice" (password): your shell
```

* **Rights** come from device groups (**Setup → Terminal access**): each group gives its members *No terminal*,
  *Read-only*, *Read and write* or *Full* on its devices. With several shared groups the best one counts.
  Admins always have full access; viewers at most read-only.
* **Accounts**: `ns-<your NETsync user>` (e.g. `ns-alice`), created the first time you open a terminal on a
  server. You choose its password then; it is yours for that server and it is also what `sudo` asks for. Forgot
  it? Choose *Set a new one* at the password prompt: NETsync already knows it's you.

| Level | On the server |
|---|---|
| Read-only | normal account, member of `adm` / `systemd-journal` (reads logs); no sudo |
| Read and write | sudo for `systemctl`, `service`, `journalctl`, `apt`/`dnf`/`yum`, `reboot` |
| Full | full sudo |

A Linux "read-only" user can still write in its home folder and `/tmp`; it can't change the system. The
read-and-write command list is in `/etc/sudoers.d/netsync`; note that some of these commands can be used to get
more rights, so treat that level as trusted.

Level changes apply at the next login. **Removing or disabling a user** in NETsync removes their account from
every server at once (offline servers are retried every 10 minutes), and an hourly check removes accounts of users
that no longer exist.

## Setup

1. **Setup → Plugin store → SSH terminal → Install.**
2. **Setup → Terminal access**: choose the level for each group.
3. Same page, **Prepare a server**: generate the script and run it once as root on each server:

   ```bash
   sudo bash netsync-terminal-setup.sh
   ```

   It creates:
   * the `netsync` account: its key (held only inside the gateway container) works only from the NETsync
     address and can only run `/usr/local/sbin/netsync-account`, which manages `ns-*` accounts and nothing else;
   * the groups `netsync-users`, `netsync-write`, `netsync-full` and `/etc/sudoers.d/netsync`;
   * an sshd rule: `ns-*` accounts may log in with a password **only from the NETsync address**, so they are
     reachable only through NETsync.

   Undo: `userdel -r netsync; rm /usr/local/sbin/netsync-account* /etc/sudoers.d/netsync /etc/ssh/sshd_config.d/50-netsync.conf`.
4. **Check a server** on the same page confirms the gateway can manage it.

## Security

* Tickets are valid for one minute, once, signed with the plugin secret; the browser sends them as a WebSocket
  subprotocol, never in a URL.
* The gateway trusts a server's host key the first time and refuses the connection if it changes. After
  reinstalling a server, **Forget** its key on the Terminal access page.
* Passwords are never stored by NETsync or the gateway; they go straight to the server.
* Every session is logged (who, which server, which level, from where, how long, how it ended) on the Terminal
  access page; users see their own sessions on the Terminal page.
