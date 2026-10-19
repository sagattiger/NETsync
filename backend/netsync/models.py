"""Database models.

Inventory/state live in regular tables; metrics, syslog and state history are
TimescaleDB hypertables (see db.HYPERTABLES).
"""

from datetime import datetime
from enum import IntEnum, StrEnum

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    SmallInteger,
    String,
    Table,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class State(IntEnum):
    """CheckMK style service states."""

    OK = 0
    WARN = 1
    CRIT = 2
    UNKNOWN = 3


class Role(StrEnum):
    ADMIN = "admin"  # everything, incl. users and settings
    OPERATOR = "operator"  # manage devices, ack, downtimes in their groups
    VIEWER = "viewer"  # read only, limited to their groups


def utcnow_col(**kw):
    return mapped_column(DateTime(timezone=True), server_default=func.now(), **kw)


# --------------------------------------------------------------------------- cluster

class Node(Base):
    """A polling node. The central panel talks to many nodes in cluster mode."""

    __tablename__ = "nodes"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(64), unique=True)
    url: Mapped[str | None] = mapped_column(String(255))
    is_local: Mapped[bool] = mapped_column(Boolean, default=True)
    last_seen: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    version: Mapped[str | None] = mapped_column(String(32))


# --------------------------------------------------------------------------- users

user_groups = Table(
    "user_groups",
    Base.metadata,
    Column("user_id", ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
    Column("group_id", ForeignKey("device_groups.id", ondelete="CASCADE"), primary_key=True),
)

device_group_members = Table(
    "device_group_members",
    Base.metadata,
    Column("device_id", ForeignKey("devices.id", ondelete="CASCADE"), primary_key=True),
    Column("group_id", ForeignKey("device_groups.id", ondelete="CASCADE"), primary_key=True),
)


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True)
    email: Mapped[str | None] = mapped_column(String(255))
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(16), default=Role.VIEWER)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = utcnow_col()

    # Profile
    full_name: Mapped[str | None] = mapped_column(String(128))
    phone: Mapped[str | None] = mapped_column(String(64))
    job_title: Mapped[str | None] = mapped_column(String(128))
    timezone: Mapped[str | None] = mapped_column(String(64))
    # UI settings: theme, default_range, time_format, refresh_interval...
    preferences: Mapped[dict] = mapped_column(JSON, default=dict)
    avatar: Mapped[bytes | None] = mapped_column(LargeBinary, deferred=True)
    avatar_mime: Mapped[str | None] = mapped_column(String(32))
    avatar_version: Mapped[int] = mapped_column(Integer, default=0)
    last_login: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    password_changed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    groups: Mapped[list["DeviceGroup"]] = relationship(secondary=user_groups, lazy="selectin")


class DeviceGroup(Base):
    __tablename__ = "device_groups"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(64), unique=True)
    description: Mapped[str | None] = mapped_column(Text)


# --------------------------------------------------------------------------- inventory

class Device(Base):
    __tablename__ = "devices"

    id: Mapped[int] = mapped_column(primary_key=True)
    node_id: Mapped[int | None] = mapped_column(ForeignKey("nodes.id"))
    hostname: Mapped[str] = mapped_column(String(255), unique=True)
    ip: Mapped[str | None] = mapped_column(String(64))

    snmp_version: Mapped[str] = mapped_column(String(4), default="2c")  # 1, 2c, 3
    snmp_port: Mapped[int] = mapped_column(Integer, default=161)
    snmp_community: Mapped[str | None] = mapped_column(String(255))
    snmp_v3: Mapped[dict | None] = mapped_column(JSON)  # user, auth_proto, auth_key, priv_proto, priv_key

    sys_name: Mapped[str | None] = mapped_column(String(255))
    sys_descr: Mapped[str | None] = mapped_column(Text)
    sys_object_id: Mapped[str | None] = mapped_column(String(255))
    sys_location: Mapped[str | None] = mapped_column(String(255))
    sys_contact: Mapped[str | None] = mapped_column(String(255))
    uptime: Mapped[int | None] = mapped_column(BigInteger)

    vendor: Mapped[str | None] = mapped_column(String(64))
    os: Mapped[str | None] = mapped_column(String(64))
    hardware: Mapped[str | None] = mapped_column(String(255))
    version: Mapped[str | None] = mapped_column(String(128))
    serial: Mapped[str | None] = mapped_column(String(128))
    device_type: Mapped[str | None] = mapped_column(String(32))  # router, switch, firewall, server, ...

    status: Mapped[int] = mapped_column(SmallInteger, default=State.UNKNOWN)
    status_reason: Mapped[str | None] = mapped_column(Text)
    disabled: Mapped[bool] = mapped_column(Boolean, default=False)
    last_polled: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_discovered: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    poll_duration: Mapped[float | None] = mapped_column(Float)
    created_at: Mapped[datetime] = utcnow_col()

    groups: Mapped[list[DeviceGroup]] = relationship(secondary=device_group_members, lazy="selectin")
    components: Mapped[list["Component"]] = relationship(
        back_populates="device", cascade="all, delete-orphan", lazy="raise", passive_deletes=True
    )


class Component(Base):
    """Anything discovered on a device: port, sensor, storage, processor, mempool..."""

    __tablename__ = "components"
    __table_args__ = (UniqueConstraint("device_id", "kind", "index"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    device_id: Mapped[int] = mapped_column(ForeignKey("devices.id", ondelete="CASCADE"), index=True)
    module: Mapped[str] = mapped_column(String(64))  # plugin module that owns it
    kind: Mapped[str] = mapped_column(String(32))  # port, sensor, storage, processor, mempool
    index: Mapped[str] = mapped_column(String(128))  # SNMP index or other stable key
    name: Mapped[str] = mapped_column(String(255))
    descr: Mapped[str | None] = mapped_column(Text)
    attrs: Mapped[dict] = mapped_column(JSON, default=dict)  # speed, mac, sensor class, units...
    values: Mapped[dict] = mapped_column(JSON, default=dict)  # last polled values for quick display
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    deleted: Mapped[bool] = mapped_column(Boolean, default=False)
    last_seen: Mapped[datetime] = utcnow_col()

    device: Mapped[Device] = relationship(back_populates="components")


class Service(Base):
    """A checked item with a state, e.g. 'Interface Gi0/1' or 'CPU utilization'."""

    __tablename__ = "services"
    __table_args__ = (UniqueConstraint("device_id", "name"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    device_id: Mapped[int] = mapped_column(ForeignKey("devices.id", ondelete="CASCADE"), index=True)
    component_id: Mapped[int | None] = mapped_column(ForeignKey("components.id", ondelete="CASCADE"))
    check: Mapped[str] = mapped_column(String(64))  # e.g. if_status, cpu_util, storage_used
    name: Mapped[str] = mapped_column(String(255))
    state: Mapped[int] = mapped_column(SmallInteger, default=State.UNKNOWN)
    output: Mapped[str | None] = mapped_column(Text)
    perf: Mapped[dict] = mapped_column(JSON, default=dict)
    last_check: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_change: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    acknowledged: Mapped[bool] = mapped_column(Boolean, default=False)
    ack_comment: Mapped[str | None] = mapped_column(Text)
    ack_by: Mapped[str | None] = mapped_column(String(64))


# --------------------------------------------------------------------------- time series

class Metric(Base):
    __tablename__ = "metrics"

    time: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    device_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    component_id: Mapped[int] = mapped_column(Integer, primary_key=True, default=0)
    name: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[float] = mapped_column(Float)


class SyslogMessage(Base):
    __tablename__ = "syslog_messages"

    time: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    device_id: Mapped[int | None] = mapped_column(Integer, index=True)
    source_ip: Mapped[str] = mapped_column(String(64))
    facility: Mapped[int] = mapped_column(SmallInteger)
    severity: Mapped[int] = mapped_column(SmallInteger)
    hostname: Mapped[str | None] = mapped_column(String(255))
    program: Mapped[str | None] = mapped_column(String(128))
    message: Mapped[str] = mapped_column(Text)


class StateChange(Base):
    __tablename__ = "state_changes"

    time: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    service_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    device_id: Mapped[int] = mapped_column(Integer, index=True)
    old_state: Mapped[int] = mapped_column(SmallInteger)
    new_state: Mapped[int] = mapped_column(SmallInteger)
    output: Mapped[str | None] = mapped_column(Text)


class DeviceNote(Base):
    """Free-form markdown notes for a device (one document per device)."""

    __tablename__ = "device_notes"

    device_id: Mapped[int] = mapped_column(ForeignKey("devices.id", ondelete="CASCADE"), primary_key=True)
    content: Mapped[str] = mapped_column(Text, default="")
    updated_at: Mapped[datetime] = utcnow_col()
    updated_by: Mapped[str | None] = mapped_column(String(64))


class EventComment(Base):
    """A comment on a state change event. Pinned comments keep the event on top
    (e.g. "known issue, fix scheduled for October 31st").

    Events live in the state_changes hypertable and are identified by
    (service_id, event_time)."""

    __tablename__ = "event_comments"
    __table_args__ = (Index("ix_event_comments_event", "device_id", "service_id", "event_time"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    device_id: Mapped[int] = mapped_column(ForeignKey("devices.id", ondelete="CASCADE"))
    service_id: Mapped[int] = mapped_column(Integer)
    event_time: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    body: Mapped[str] = mapped_column(Text)
    pinned: Mapped[bool] = mapped_column(Boolean, default=False)
    author_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    author: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = utcnow_col()
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Dashboard(Base):
    """A user-built page of widgets (graphs, device status, problem lists).

    ``widgets`` is a list of {id, type, title, size, device_id, component_id, preset, ...};
    widget data is always fetched through the regular device-scoped endpoints."""

    __tablename__ = "dashboards"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(128))
    description: Mapped[str | None] = mapped_column(Text)
    owner_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    owner: Mapped[str] = mapped_column(String(64))
    shared: Mapped[bool] = mapped_column(Boolean, default=False)
    widgets: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = utcnow_col()
    updated_at: Mapped[datetime] = utcnow_col()


# --------------------------------------------------------------------------- rules / alerting

class ThresholdRule(Base):
    """CheckMK style rule: the most specific matching rule (lowest priority) wins."""

    __tablename__ = "threshold_rules"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(128))
    check: Mapped[str] = mapped_column(String(64))  # which check this applies to
    device_group_id: Mapped[int | None] = mapped_column(ForeignKey("device_groups.id", ondelete="CASCADE"))
    device_id: Mapped[int | None] = mapped_column(ForeignKey("devices.id", ondelete="CASCADE"))
    item_regex: Mapped[str | None] = mapped_column(String(255))  # match service/component name
    warn: Mapped[float | None] = mapped_column(Float)
    crit: Mapped[float | None] = mapped_column(Float)
    direction: Mapped[str] = mapped_column(String(8), default="above")  # above | below
    params: Mapped[dict] = mapped_column(JSON, default=dict)  # check specific options
    priority: Mapped[int] = mapped_column(Integer, default=100)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)


class Downtime(Base):
    __tablename__ = "downtimes"

    id: Mapped[int] = mapped_column(primary_key=True)
    device_id: Mapped[int] = mapped_column(ForeignKey("devices.id", ondelete="CASCADE"), index=True)
    service_id: Mapped[int | None] = mapped_column(ForeignKey("services.id", ondelete="CASCADE"))
    start: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    end: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    comment: Mapped[str | None] = mapped_column(Text)
    author: Mapped[str | None] = mapped_column(String(64))


class NotificationRule(Base):
    __tablename__ = "notification_rules"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(128))
    channel: Mapped[str] = mapped_column(String(32))  # plugin channel name: email, telegram, webhook
    config: Mapped[dict] = mapped_column(JSON, default=dict)
    min_state: Mapped[int] = mapped_column(SmallInteger, default=State.CRIT)
    notify_recovery: Mapped[bool] = mapped_column(Boolean, default=True)
    device_group_id: Mapped[int | None] = mapped_column(ForeignKey("device_groups.id", ondelete="CASCADE"))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)


class PluginSetting(Base):
    """Per-plugin configuration stored in the DB, editable from the UI."""

    __tablename__ = "plugin_settings"

    name: Mapped[str] = mapped_column(String(64), primary_key=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    config: Mapped[dict] = mapped_column(JSON, default=dict)
