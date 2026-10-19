from netsync.plugins.base import Plugin
from netsync.plugins.builtin import latency
from netsync.plugins.builtin.host_resources import HostResourcesModule
from netsync.plugins.builtin.interfaces import InterfacesModule
from netsync.plugins.builtin.netstats import NetstatsModule
from netsync.plugins.builtin.notify import EmailChannel, TelegramChannel, WebhookChannel
from netsync.plugins.builtin.syslog import SyslogService
from netsync.plugins.builtin.system import SystemModule

BUILTIN_PLUGINS = [
    Plugin(
        name="snmp_core",
        version="0.1.0",
        description="System, interfaces, CPU, memory, storage and TCP/UDP stack via standard MIBs",
        modules=[SystemModule(), InterfacesModule(), HostResourcesModule(), NetstatsModule()],
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
]
