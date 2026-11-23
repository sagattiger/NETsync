# Docker containers (and Coolify servers)

NETsync shows the containers of a Docker host on the device's **Containers** tab: name, image, Compose project
and service (and the Coolify resource name on Coolify servers), state and health, published ports, CPU and memory,
with graphs. Each container is a service, so a stopped or unhealthy container is a problem like any other.

It works through SNMP, with no extra agent or port and without giving NETsync access to Docker:

```
root's cron (every minute) ── docker ps / docker stats ──► /var/lib/netsync/docker.txt
snmpd ── extend netsync-docker /bin/cat /var/lib/netsync/docker.txt ──► NETsync (SNMP, read-only)
```

snmpd only reads a file. It never touches the Docker socket, which would amount to root on the host. The file holds
only the fields NETsync uses: id, name, image, state, status, ports, Compose project/service, the Coolify resource
name, CPU % and memory. No environment variables, commands, other labels or mounts.

## Set up a Docker host

On the Docker host, as root (or with `sudo`):

```bash
curl -fsSL https://raw.githubusercontent.com/sagattiger/NETsync/main/agents/netsync-docker -o /usr/local/bin/netsync-docker
```
```bash
chmod 755 /usr/local/bin/netsync-docker && /usr/local/bin/netsync-docker && head -3 /var/lib/netsync/docker.txt
```

The last command should print `# netsync-docker 1 …` and your first containers. Then run it every minute:

```bash
echo '* * * * * root /usr/local/bin/netsync-docker' > /etc/cron.d/netsync-docker
```

And let snmpd serve the file:

```bash
echo 'extend netsync-docker /bin/cat /var/lib/netsync/docker.txt' >> /etc/snmp/snmpd.conf && systemctl restart snmpd
```

Check from the NETsync server (or any host allowed to query snmpd), replacing the community and address:

```bash
snmpwalk -v2c -c <community> <docker-host> 'NET-SNMP-EXTEND-MIB::nsExtendOutLine."netsync-docker"' | head -3
```

If that answers "No Such Object", the snmpd `view` doesn't include the extend MIB: add
`view systemonly included .1.3.6.1.4.1.8072.1.3` (use your view's name) and restart snmpd. Hosts that already
serve `netsync-disks` ([OPTANE-SWAP.md](OPTANE-SWAP.md)) are fine.

Finally open the device in NETsync and press **Rediscover**. The **Containers** tab appears.

## States

| Container | Service state |
|---|---|
| running (health `healthy` or none, or `starting`) | OK |
| created, never started | OK |
| restarting, paused | WARN |
| exited with code 0 (stopped on purpose, or a finished one-off job) | WARN |
| running but `unhealthy`, exited with any other code, dead | CRIT |

**Docker data** is a device service: WARN when the list is older than 5 minutes (the cron job stopped), CRIT when
the extend doesn't answer. Containers you stopped on purpose can be switched off per component like any other.

A container is identified by its **name**, so recreating it (new image, `docker compose up`) keeps its history. A
container that is removed disappears after two discoveries.

Metrics per container: `cpu_pct`, `mem_bytes`, `mem_pct`, `running` (1/0). Per host: `containers_running`,
`containers_total`.

## Coolify

On a Coolify server the same setup lists every container Coolify runs, with the Coolify resource name when the
container has the `coolify.resourceName` label. Names, URLs and projects from the Coolify API itself are not read
yet.
