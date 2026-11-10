"""Probes: active checks of IP addresses, hosts, ports, URLs and more, independent of SNMP devices.

Storage choice: every probe owns a lightweight *virtual device* (``device_type="probe"``, no SNMP
polling, no discovery). Its metrics go to the regular ``metrics`` hypertable and its checks ("Status",
"Response time", "Ping RTT", "Certificate expiry", ...) are regular services, so thresholds (rules),
problems, acknowledgements, downtimes, alerts, device-group scoping and dashboards all work unchanged.

The kinds live in netsync/probing/checkers, the shared behaviour in netsync/probing/runner.py.
"""

from netsync.plugins.base import Plugin
from netsync.probing.base import validate_host
from netsync.probing.checkers.icmp import ping_result
from netsync.probing.runner import ProbeService

PROBE_DEVICE_TYPE = "probe"
METRICS = ("ping_min", "ping_avg", "ping_max", "ping_jitter", "ping_loss")
INTERVAL_RANGE = (20, 3600)
COUNT_RANGE = (1, 20)

validate_target = validate_host  # IP address or hostname (kept for callers of the first probe version)


def device_hostname(name: str) -> str:
    """Hostname of the probe's virtual device: unique, readable in problem lists, never a real host."""
    return f"{name} (probe)"


def probe_results(target: str, h):
    """(metrics, checks, alive) of one icmplib Host - the ICMP result in the original shape."""
    from netsync.plugins.base import MetricSample

    r = ping_result(target, h)
    return [MetricSample(k, v) for k, v in r.metrics.items()], r.checks, r.up


plugin = Plugin(
    name="probes",
    version="0.2.0",
    description="Active monitoring: ping, TCP, UDP, DNS, HTTP(S), JSON APIs, TLS certificates and push heartbeats",
    services=[ProbeService()],
    builtin=True,
)
