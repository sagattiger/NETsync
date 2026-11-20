"""CrowdSec plugin: how many attackers CrowdSec is blocking, from one or more Local APIs (read-only bouncer keys).

Built in rather than a container plugin: it stores time series, raises problems and feeds dashboard and public
widgets, and only in-process plugins can write metrics and services (container plugins get no database access).
Docs: docs/CROWDSEC.md.
"""

from zoneinfo import ZoneInfo

from netsync.plugins.base import Plugin
from netsync.plugins.builtin.crowdsec.service import CrowdSecService

SETTINGS = [
    {"key": "interval_s", "label": "Read every (seconds)", "type": "number", "min": 60, "max": 3600,
     "help": "How often each LAPI is asked for its decisions."},
    {"key": "timeout_s", "label": "Timeout (seconds)", "type": "number", "min": 3, "max": 30},
    {"key": "warn_new_bans", "label": "Warn at new bans per read", "type": "number", "min": 0, "max": 100000,
     "help": "The New bans service turns WARN when one read finds at least this many new local bans. 0 = off "
             "(threshold rules for 'crowdsec_new_bans' work too)."},
    {"key": "timezone", "label": "Time zone for days", "type": "text",
     "help": "Days of the 'new bans per day' chart, e.g. America/Sao_Paulo."},
]
DEFAULTS = {"interval_s": 300, "timeout_s": 10, "warn_new_bans": 0, "timezone": "UTC"}


def _validate(cfg: dict) -> None:
    try:
        ZoneInfo(str(cfg.get("timezone") or "UTC"))
    except (KeyError, ValueError):
        raise ValueError("Unknown time zone (use a name like America/Sao_Paulo)") from None


def _router():
    from netsync.plugins.builtin.crowdsec.api import router

    return router


plugin = Plugin(
    name="crowdsec",
    label="CrowdSec",
    version="1.0.0",
    description="Bans from CrowdSec Local APIs (read-only bouncer keys): active and new bans, scenarios, "
                "a LAPI problem when unreachable, and a dashboard widget",
    services=[CrowdSecService()],
    router=_router(),
    settings=SETTINGS,
    defaults=DEFAULTS,
    validate=_validate,
    builtin=True,
)
