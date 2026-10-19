import logging
from importlib.metadata import entry_points

from netsync.config import get_settings
from netsync.plugins.base import BackgroundService, Module, NotificationChannel, Plugin

log = logging.getLogger(__name__)

ENTRY_POINT_GROUP = "netsync.plugins"


class Registry:
    def __init__(self) -> None:
        self.plugins: dict[str, Plugin] = {}

    def register(self, plugin: Plugin) -> None:
        if plugin.name in self.plugins:
            log.warning("plugin %s registered twice, ignoring", plugin.name)
            return
        self.plugins[plugin.name] = plugin

    def load(self) -> None:
        from netsync.plugins.builtin import BUILTIN_PLUGINS

        disabled = {p.strip() for p in get_settings().disabled_plugins.split(",") if p.strip()}
        candidates = list(BUILTIN_PLUGINS)
        for ep in entry_points(group=ENTRY_POINT_GROUP):
            try:
                candidates.append(ep.load())
            except Exception:
                log.exception("failed to load plugin entry point %s", ep.name)
        for plugin in candidates:
            if plugin.name in disabled:
                log.info("plugin %s disabled", plugin.name)
                continue
            self.register(plugin)
        log.info("loaded plugins: %s", ", ".join(self.plugins))

    @property
    def modules(self) -> list[Module]:
        mods = [m for p in self.plugins.values() for m in p.modules]
        return sorted(mods, key=lambda m: m.order)

    @property
    def channels(self) -> dict[str, NotificationChannel]:
        return {c.name: c for p in self.plugins.values() for c in p.channels}

    @property
    def services(self) -> list[BackgroundService]:
        return [s for p in self.plugins.values() for s in p.services]


registry = Registry()
