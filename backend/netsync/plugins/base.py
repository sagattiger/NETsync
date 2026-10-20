"""The NETsync plugin API.

A plugin is a bundle of capabilities. Everything in NETsync - including the
built-in SNMP checks, syslog and notification channels - is a plugin, so
third-party extensions (smokeping, netflow, rancid/oxidized, docker...) use
exactly the same interface.

    plugin = Plugin(
        name="my_plugin",
        version="1.0.0",
        description="...",
        modules=[MyDiscoveryModule()],      # discover + poll components on devices
        channels=[MyNotificationChannel()], # deliver alerts
        services=[MyBackgroundService()],   # long running collectors (syslog, netflow...)
        ui_tabs=[UITab(...)],               # extra tabs on the device page
        router=my_fastapi_router,           # extra REST endpoints under /api/plugins/<name>
    )

External plugins are installed as Python packages exposing the plugin object
under the ``netsync.plugins`` entry point group.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING, Any, ClassVar

if TYPE_CHECKING:
    from fastapi import APIRouter

    from netsync.models import Component, Device
    from netsync.snmp.client import SnmpClient


@dataclass
class ComponentSpec:
    """A component found during discovery."""

    kind: str  # port, sensor, storage, processor, mempool, ...
    index: str
    name: str
    descr: str | None = None
    attrs: dict[str, Any] = field(default_factory=dict)


@dataclass
class MetricSample:
    name: str
    value: float
    kind: str | None = None  # component kind/index; None = device level metric
    index: str | None = None


@dataclass
class CheckResult:
    """Result of a check.

    ``state`` is an explicit state decided by the module (e.g. port down).
    ``value`` is compared against threshold rules for ``check``.
    The final service state is the worst of both.
    """

    check: str
    name: str
    output: str = ""
    state: int | None = None
    value: float | None = None
    unit: str = ""
    kind: str | None = None
    index: str | None = None
    perf: dict[str, float] = field(default_factory=dict)


@dataclass
class PollResult:
    metrics: list[MetricSample] = field(default_factory=list)
    checks: list[CheckResult] = field(default_factory=list)
    # Values to remember on each component until the next poll, keyed by (kind, index).
    # Used for counters -> rates and for quick display in the UI.
    values: dict[tuple[str, str], dict[str, Any]] = field(default_factory=dict)


class DeviceContext:
    """What a module gets to work with for one device during discovery/poll."""

    def __init__(self, device: Device, snmp: SnmpClient, components: list[Component], now: datetime):
        self.device = device
        self.snmp = snmp
        self.now = now
        self._components = components

    def components(self, kind: str) -> list[Component]:
        return [c for c in self._components if c.kind == kind and c.enabled and not c.deleted]

    def previous(self, kind: str, index: str) -> dict[str, Any]:
        for c in self._components:
            if c.kind == kind and c.index == index:
                return c.values or {}
        return {}


class Module:
    """Discovers components on a device and polls them."""

    name: ClassVar[str]
    kinds: ClassVar[tuple[str, ...]] = ()  # component kinds this module owns
    order: ClassVar[int] = 100  # lower runs first; 'system' runs at 0

    def applies_to(self, device: Device) -> bool:
        return True

    async def discover(self, ctx: DeviceContext) -> list[ComponentSpec]:
        return []

    async def poll(self, ctx: DeviceContext) -> PollResult:
        return PollResult()


@dataclass
class AlertEvent:
    device_id: int
    hostname: str
    service: str
    old_state: int
    new_state: int
    output: str
    time: datetime
    url: str


class NotificationChannel:
    name: ClassVar[str]
    label: ClassVar[str]
    # JSON-schema-ish description of config fields, rendered by the UI.
    config_fields: ClassVar[list[dict[str, Any]]] = []

    async def send(self, event: AlertEvent, config: dict[str, Any]) -> None:
        raise NotImplementedError


class BackgroundService:
    """A long-running task started by the worker (syslog receiver, flow collector...)."""

    name: ClassVar[str]

    async def run(self, stop: asyncio.Event) -> None:
        raise NotImplementedError


@dataclass
class UITab:
    """A tab shown on the device page. The frontend renders a known ``view``
    (e.g. 'metrics' for generic graphs) or an iframe/URL for fully custom UIs."""

    id: str
    label: str
    view: str = "metrics"  # metrics | table | iframe
    metrics: list[str] = field(default_factory=list)
    url: str | None = None


@dataclass
class Plugin:
    name: str
    version: str
    description: str = ""
    modules: list[Module] = field(default_factory=list)
    channels: list[NotificationChannel] = field(default_factory=list)
    services: list[BackgroundService] = field(default_factory=list)
    ui_tabs: list[UITab] = field(default_factory=list)
    router: APIRouter | None = None
    builtin: bool = False
    label: str | None = None  # human friendly name for the UI
    # Admin-editable settings, rendered by the UI. Each field:
    # {key, label, type: text|secret|number|bool|select|textarea|model, help?, options?: [[value, label]], min?, max?}
    settings: list[dict[str, Any]] = field(default_factory=list)
    defaults: dict[str, Any] = field(default_factory=dict)
    enabled_by_default: bool = True
    # Buttons in the settings dialog: {id, label, method, path} - path is relative to /api/plugins/<name>
    actions: list[dict[str, Any]] = field(default_factory=list)
    # Event hooks called by the core, e.g. {"state_change": [fn(events)], "syslog": [fn(rows)]}
    hooks: dict[str, list] = field(default_factory=dict)
