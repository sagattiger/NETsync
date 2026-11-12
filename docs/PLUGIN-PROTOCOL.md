# Tool hub, MCP and container plugins

NETsync has one **tool hub**. Every tool, whoever provides it, is listed, allowed, approved, run and audited
there. The built-in AI chat, MCP clients (Claude Desktop, n8n…) and other plugins all go through it.

```
 Claude Desktop / n8n ──MCP──┐                         ┌── in-process plugins (netsync__*)
 NETsync AI chat ────────────┼──► tool hub ──policy──► ┤
 container plugins ──────────┘   approvals · audit     └── container plugins over HTTP (ssh__*, vault__*…)
```

## Tools

* Named `<plugin>__<tool>` (lowercase letters, digits and `_`), e.g. `netsync__alert_history`.
* **read** tools run straight away. **write** tools (anything that changes something) need a person's approval
  in **Setup → AI tools** by default.
* Admins can set each tool to *automatic*, *needs approval* or *off*.
* Every call is logged: who called it, from where (mcp, chat, ui, plugin), the arguments (secrets hidden), the
  result, how long it took and who approved it.
* Users only see devices of their groups. MCP tokens see every device.

Built-in tools (all read-only): `netsync__find_devices`, `netsync__device_overview`, `netsync__list_problems`,
`netsync__alert_history`, `netsync__search_syslog`, `netsync__metric_summary`, `netsync__call_result`.

## MCP server

`POST https://<netsync>/api/mcp`. This is MCP's Streamable HTTP transport with plain JSON responses: no
server-sent events, which clients handle automatically. It authenticates with an **MCP token** (`nsm_…`),
created in **Setup → AI tools → MCP access**. Each token has:

* **tools:** name patterns, e.g. `netsync__*` (the default) or `netsync__*, ssh__run_readonly`.
* **write:** whether it may *request* write tools. Requests still wait for approval unless an admin set the
  tool to automatic.

When a write tool needs approval, the client gets
`{"status": "pending_approval", "call_id": 12, "message": "…"}`. It can ask `netsync__call_result` with that
`call_id` later.

Claude Desktop (`claude_desktop_config.json`), through the `mcp-remote` bridge:

```json
{ "mcpServers": { "netsync": { "command": "npx", "args": ["-y", "mcp-remote", "https://netsync.example.com/api/mcp",
  "--header", "Authorization: Bearer nsm_xxxxxxxx"] } } }
```

n8n: add an **MCP Client Tool** node with the URL above, *HTTP Streamable* transport and a *Bearer* header.

## Container plugins

A plugin that holds secrets, runs third-party code, needs its own loop or another language runs in its **own
container**. It talks to NETsync only over HTTP, with a shared secret. It gets no database access and no
public port.

### Register

1. In **Setup → AI tools → Container plugins**, add the plugin's name and the URL NETsync uses to reach it,
   e.g. `http://netsync-hello:8080` on the same Docker network. NETsync shows a secret **once**
   (`nsp_plg_…`).
2. Start the container with `NETSYNC_PLUGIN_SECRET=<that secret>` (and `NETSYNC_URL=http://api:8000` if it
   calls NETsync back).
3. NETsync checks every plugin each minute. Once it's online, its manifest lists the permissions it asks for.
   Grant the ones you agree with. Its tools only appear in the hub after you grant `tools`.

Permissions:

| Permission | Allows |
|---|---|
| `tools` | Offer its tools to the AI and MCP clients |
| `events` | `GET /api/plugin-api/events`: NETsync events (alerts, recoveries, syslog, AI jobs) as server-sent events |
| `call:read` | `POST /api/plugin-api/tools/call`: call other plugins' read-only tools |

### What the plugin implements

Every request from NETsync carries `Authorization: Bearer <secret>`. Reject anything else.

| Request | Answer |
|---|---|
| `GET /health` | `{"ok": true}` (no secret needed) |
| `GET /manifest` | `{"name", "version", "description", "permissions": [...], "tools": [{"name", "description", "input_schema", "risk": "read"\|"write"}]}`. `name` must equal the registered name |
| `POST /tools/<tool>` with `{"arguments", "call_id", "actor", "origin"}` | `{"result": …}` or `{"error": "message"}` |

`input_schema` is a JSON Schema object; NETsync checks the arguments before calling the plugin.

### Python SDK

[`plugins/sdk/netsync_plugin.py`](../plugins/sdk/netsync_plugin.py) does all of the above. Here is a complete
plugin with one read tool, one write tool and a call back into NETsync:
[`plugins/examples/hello`](../plugins/examples/hello).

```bash
docker build -f plugins/examples/hello/Dockerfile -t netsync-hello plugins
docker run -d --name netsync-hello --network netsync_default \
  -e NETSYNC_PLUGIN_SECRET=nsp_plg_xxxxxxxx -e NETSYNC_URL=http://api:8000 netsync-hello
```

### Security notes

* The secret is stored encrypted in NETsync and is shown once. Rotate it in the UI if it leaks.
* A plugin sees only what reaches it: tool arguments (with the caller's name), and events if granted.
  It never sees the database, users or other plugins' secrets.
* Write tools: approval replays the stored arguments. Values of secret-looking keys (`password`, `token`, `key`…)
  are hidden in the log and can't be replayed, so a write tool must take its credentials from its own vault,
  never from arguments.
