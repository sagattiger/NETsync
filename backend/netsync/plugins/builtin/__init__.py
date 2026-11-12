from netsync import housekeeping, probes
from netsync.tools import builtin as tool_builtin
from netsync.tools.remote import RemotePluginService
from netsync.plugins.base import Plugin
from netsync.plugins.builtin import ai, latency
from netsync.plugins.builtin.host_resources import HostResourcesModule
from netsync.plugins.builtin.interfaces import InterfacesModule
from netsync.plugins.builtin.netstats import NetstatsModule
from netsync.plugins.builtin.notify import EmailChannel, TelegramChannel, WebhookChannel
from netsync.plugins.builtin.diskio import DiskIoModule
from netsync.plugins.builtin.sensors import SensorsModule
from netsync.plugins.builtin.syslog import SyslogService
from netsync.plugins.builtin.system import SystemModule
from netsync.plugins.builtin.ucd import UcdModule

BUILTIN_PLUGINS = [
    Plugin(
        name="snmp_core",
        version="0.1.0",
        description="System, interfaces, CPU, memory, storage, sensors, disk I/O and the IP/TCP/UDP/SNMP stack "
                    "via standard MIBs",
        modules=[SystemModule(), InterfacesModule(), HostResourcesModule(), UcdModule(), NetstatsModule(),
                 SensorsModule(), DiskIoModule()],
        builtin=True,
    ),
    Plugin(
        name="notifications",
        version="0.1.0",
        description="Email, Telegram and webhook notification channels",
        channels=[EmailChannel(), TelegramChannel(), WebhookChannel()],
        builtin=True,
    ),
    Plugin(
        name="syslog",
        version="0.1.0",
        description="Syslog receiver (UDP/TCP 514) linked to devices",
        services=[SyslogService()],
        builtin=True,
    ),
    latency.plugin,
    probes.plugin,
    housekeeping.plugin,
    Plugin(
        name="netsync",
        label="Tool hub (MCP)",
        version="1.0.0",
        description="NETsync's read-only AI tools, the MCP server, approvals and container plugins",
        tools=tool_builtin.TOOLS,
        services=[RemotePluginService()],
        builtin=True,
    ),
    ai.plugin,
]
