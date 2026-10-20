from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ORM(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class GroupOut(ORM):
    id: int
    name: str
    description: str | None = None


class DeviceIn(BaseModel):
    hostname: str
    ip: str | None = None
    snmp_version: str = Field("2c", pattern="^(1|2c|3)$")
    snmp_port: int = 161
    snmp_community: str | None = "public"
    snmp_v3: dict[str, Any] | None = None
    device_type: str | None = None
    node_id: int | None = None
    group_ids: list[int] = []


class DeviceUpdate(BaseModel):
    ip: str | None = None
    snmp_version: str | None = Field(None, pattern="^(1|2c|3)$")
    snmp_port: int | None = None
    snmp_community: str | None = None
    snmp_v3: dict[str, Any] | None = None
    device_type: str | None = None
    node_id: int | None = None
    disabled: bool | None = None
    group_ids: list[int] | None = None


class DeviceOut(ORM):
    """SNMP credentials are write-only and never returned."""

    id: int
    hostname: str
    ip: str | None
    node_id: int | None
    snmp_version: str
    snmp_port: int
    sys_name: str | None
    sys_descr: str | None
    sys_object_id: str | None
    sys_location: str | None
    sys_contact: str | None
    uptime: int | None
    vendor: str | None
    os: str | None
    hardware: str | None
    version: str | None
    serial: str | None
    device_type: str | None
    virtualization: str | None = None
    kernel: str | None = None
    ip_addresses: list[str] = []
    status: int
    status_reason: str | None
    disabled: bool
    last_polled: datetime | None
    last_discovered: datetime | None
    poll_duration: float | None
    groups: list[GroupOut] = []


class DeviceSummary(DeviceOut):
    services_ok: int = 0
    services_warn: int = 0
    services_crit: int = 0
    services_unknown: int = 0
    ports: int = 0


class ComponentOut(ORM):
    id: int
    kind: str
    index: str
    module: str
    name: str
    descr: str | None
    attrs: dict[str, Any]
    values: dict[str, Any]
    enabled: bool


class ServiceOut(ORM):
    id: int
    device_id: int
    component_id: int | None
    check: str
    name: str
    state: int
    output: str | None
    perf: dict[str, Any]
    last_check: datetime | None
    last_change: datetime | None
    acknowledged: bool
    ack_comment: str | None
    ack_by: str | None


class ProblemOut(ServiceOut):
    hostname: str = ""
    resolved: bool = False
    problem_state: int = 0  # state of the latest problem event (what a resolved row was)
    problem_since: datetime | None = None
    resolved_at: datetime | None = None
    duration: float | None = None  # seconds the problem has been / was active
    event: dict[str, Any] | None = None  # latest problem event with the episode comment thread
    ai_status: str | None = None  # pending / running AI analysis


class AckIn(BaseModel):
    comment: str = ""


class DowntimeIn(BaseModel):
    device_id: int
    service_id: int | None = None
    start: datetime
    end: datetime
    comment: str | None = None


class DowntimeOut(ORM):
    id: int
    device_id: int
    service_id: int | None
    start: datetime
    end: datetime
    comment: str | None
    author: str | None


class RuleIn(BaseModel):
    name: str
    check: str
    device_group_id: int | None = None
    device_id: int | None = None
    item_regex: str | None = None
    warn: float | None = None
    crit: float | None = None
    direction: str = Field("above", pattern="^(above|below)$")
    params: dict[str, Any] = {}
    priority: int = 100
    enabled: bool = True


class RuleOut(RuleIn, ORM):
    id: int


class NotificationRuleIn(BaseModel):
    name: str
    channel: str
    config: dict[str, Any] = {}
    min_state: int = 2
    notify_recovery: bool = True
    device_group_id: int | None = None
    enabled: bool = True


class NotificationRuleOut(NotificationRuleIn, ORM):
    id: int


class UserIn(BaseModel):
    username: str
    password: str = Field(min_length=8)
    email: str | None = None
    role: str = Field("viewer", pattern="^(admin|operator|viewer)$")
    group_ids: list[int] = []


class UserUpdate(BaseModel):
    password: str | None = Field(None, min_length=8)
    email: str | None = None
    role: str | None = Field(None, pattern="^(admin|operator|viewer)$")
    is_active: bool | None = None
    group_ids: list[int] | None = None


class UserOut(ORM):
    id: int
    username: str
    email: str | None
    role: str
    is_active: bool
    groups: list[GroupOut] = []


class GroupIn(BaseModel):
    name: str
    description: str | None = None


class SyslogOut(ORM):
    id: int
    time: datetime
    device_id: int | None
    source_ip: str
    facility: int
    severity: int
    hostname: str | None
    program: str | None
    message: str
    ai: dict | None = None
