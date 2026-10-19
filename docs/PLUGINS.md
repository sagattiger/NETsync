# Writing NETsync plugins

Everything in NETsync is a plugin: SNMP checks, syslog, latency and notification channels.
An external plugin is a normal Python package that exposes a `Plugin` object under the
`netsync.plugins` entry point.

## Capabilities

| Capability | Base class | Use for |
|---|---|---|
| `modules` | `Module` | discover components on a device and poll them (SNMP or anything else) |
| `services` | `BackgroundService` | long-running collectors: syslog, NetFlow, traps, config backups |
| `channels` | `NotificationChannel` | alert delivery: Slack, Teams, PagerDuty, SMS, ... |
| `ui_tabs` | `UITab` | extra tabs on the device page (generic graphs or an iframe) |
| `router` | FastAPI `APIRouter` | extra endpoints, mounted at `/api/plugins/<name>/` |

## Example: a vendor module

```python
# netsync_mikrotik/__init__.py
from netsync.plugins import CheckResult, ComponentSpec, MetricSample, Module, Plugin, PollResult

MTXR_TEMP = "1.3.6.1.4.1.14988.1.1.3.10.0"   # tenths of degrees C

class MikrotikHealth(Module):
    name = "mikrotik_health"
    kinds = ("sensor",)

    def applies_to(self, device):
        return device.os == "routeros"

    async def discover(self, ctx):
        r = await ctx.snmp.get(MTXR_TEMP)
        return [ComponentSpec("sensor", "temp", "System temperature", attrs={"unit": "C"})] if r[MTXR_TEMP] else []

    async def poll(self, ctx):
        if not ctx.components("sensor"):
            return PollResult()
        temp = (await ctx.snmp.get(MTXR_TEMP))[MTXR_TEMP] / 10
        return PollResult(
            metrics=[MetricSample("temperature", temp, "sensor", "temp")],
            checks=[CheckResult("temperature", "Temperature System", value=temp, unit="°C",
                                kind="sensor", index="temp", output=f"{temp:.1f} °C")],
            values={("sensor", "temp"): {"value": temp}},
        )

plugin = Plugin(name="mikrotik", version="0.1.0", description="MikroTik health", modules=[MikrotikHealth()])
```

```toml
# pyproject.toml of the plugin
[project.entry-points."netsync.plugins"]
mikrotik = "netsync_mikrotik:plugin"
```

Install the package into the backend image (`pip install netsync-mikrotik`), then restart the api and
worker containers.

## How checks become states

1. A module returns `CheckResult`s. `state` is an explicit state set by the module (for example, a link is down),
   and `value` is a number compared against threshold rules for `check`.
2. The rules engine picks the first matching rule (by priority, device / group, item regex) or the
   built-in default, then computes the final state as the worse of the two.
3. When a service changes state, NETsync writes a `state_changes` row, pushes a live event to the UI, and sends
   notifications unless the device is in downtime or the problem is acknowledged.

## Notes

- `ctx.previous(kind, index)` returns what you stored in `PollResult.values` on the last poll. Use it
  to turn counters into rates.
- Metrics are stored with a name and, optionally, a component. The UI's `MetricChart` and the
  `/api/devices/{id}/metrics` endpoint can graph any metric name without extra code.
- A background service that produces checks (like `latency`) calls
  `netsync.poller.pipeline.store_results(...)` and then `netsync.alerting.dispatch(events)`.
