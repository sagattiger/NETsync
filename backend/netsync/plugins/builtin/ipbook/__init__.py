"""IP Book: networks, the IP addresses in them and what uses each one - the service, where it runs, how to reach it
and how to log in. Learned from discovery, edited by admins, pinged, with optional alerts and encrypted secrets.

Built in (like CrowdSec) because it reads discovery, writes metrics and services, and stores encrypted secrets.
Design: docs/superpowers/specs/2026-11-26-ip-book-design.md. Docs: docs/IPBOOK.md.
"""

from netsync.plugins.base import Plugin

SETTINGS = [
    {"key": "interval_min", "label": "Ping every (minutes)", "type": "number", "min": 1, "max": 60,
     "help": "How often every IP in IP Book is pinged. An IP is down after 3 missed pings in a row."},
]
DEFAULTS = {"interval_min": 5}


def _router():
    from netsync.plugins.builtin.ipbook.api import router

    return router


plugin = Plugin(
    name="ipbook",
    label="IP Book",
    version="1.0.0",
    description="Networks, IP addresses and what uses each one: learned from discovery, edited by admins, "
                "pinged, with optional alerts, encrypted admin-only secrets and a spreadsheet import",
    settings=SETTINGS,
    defaults=DEFAULTS,
    router=_router(),
    builtin=True,
)
