"""Syslog receiver (UDP + TCP) - RFC 3164 and RFC 5424.

Messages are matched to devices by source IP (or hostname) and stored in the
``syslog_messages`` hypertable.
"""

import asyncio
import logging
import re
from datetime import UTC, datetime

from sqlalchemy import insert, select

from netsync.config import get_settings
from netsync.db import SessionLocal
from netsync.models import Device, SyslogMessage
from netsync.plugins.base import BackgroundService

log = logging.getLogger(__name__)

RFC5424 = re.compile(r"^<(\d{1,3})>1 (\S+) (\S+) (\S+) (\S+) (\S+) (-|\[.*?\]) ?(.*)$", re.S)
RFC3164 = re.compile(r"^<(\d{1,3})>(?:([A-Z][a-z]{2} [ \d]\d \d\d:\d\d:\d\d) )?(?:(\S+) )?([^:\[\s]+)?(?:\[\d+\])?: ?(.*)$", re.S)
PRI_ONLY = re.compile(r"^<(\d{1,3})>(.*)$", re.S)


def parse(raw: str) -> dict:
    raw = raw.strip()
    if m := RFC5424.match(raw):
        pri, _ts, host, app, _pid, _msgid, _sd, msg = m.groups()
        return {"pri": int(pri), "hostname": None if host == "-" else host,
                "program": None if app == "-" else app, "message": msg}
    if m := RFC3164.match(raw):
        pri, _ts, host, prog, msg = m.groups()
        return {"pri": int(pri), "hostname": host, "program": prog, "message": msg}
    if m := PRI_ONLY.match(raw):
        return {"pri": int(m.group(1)), "hostname": None, "program": None, "message": m.group(2)}
    return {"pri": 13, "hostname": None, "program": None, "message": raw}


class SyslogService(BackgroundService):
    name = "syslog"

    def __init__(self) -> None:
        self.queue: asyncio.Queue[tuple[str, str]] = asyncio.Queue(maxsize=100_000)
        self.device_map: dict[str, int] = {}

    def enqueue(self, data: bytes, ip: str) -> None:
        try:
            self.queue.put_nowait((ip, data.decode("utf-8", errors="replace")))
        except asyncio.QueueFull:
            pass  # drop under extreme load rather than block the receiver

    async def refresh_devices(self) -> None:
        async with SessionLocal() as s:
            rows = (await s.execute(
                select(Device.id, Device.ip, Device.hostname, Device.sys_name, Device.ip_addresses)
            )).all()
        m: dict[str, int] = {}
        for did, ip, hostname, sys_name, addresses in rows:
            # every interface address of the device, so logs sent from any interface match
            for key in (*(addresses or []), ip, hostname, sys_name, (hostname or "").split(".")[0]):
                if key:
                    m.setdefault(key.lower(), did)
        self.device_map = m

    async def writer(self, stop: asyncio.Event) -> None:
        last_refresh = 0.0
        loop = asyncio.get_running_loop()
        while not stop.is_set():
            if loop.time() - last_refresh > 60:
                await self.refresh_devices()
                last_refresh = loop.time()
            batch = []
            try:
                batch.append(await asyncio.wait_for(self.queue.get(), timeout=1))
            except TimeoutError:
                continue
            while not self.queue.empty() and len(batch) < 1000:
                batch.append(self.queue.get_nowait())
            now = datetime.now(UTC)
            rows = []
            for ip, raw in batch:
                p = parse(raw)
                device_id = self.device_map.get(ip) or self.device_map.get((p["hostname"] or "").lower())
                rows.append({
                    "time": now, "device_id": device_id, "source_ip": ip,
                    "facility": p["pri"] >> 3, "severity": p["pri"] & 7,
                    "hostname": p["hostname"], "program": p["program"], "message": p["message"][:8192],
                })
            try:
                async with SessionLocal() as s:
                    await s.execute(insert(SyslogMessage), rows)
                    await s.commit()
            except Exception:
                log.exception("failed to store %d syslog messages", len(rows))

    async def run(self, stop: asyncio.Event) -> None:
        s = get_settings()
        loop = asyncio.get_running_loop()
        service = self

        class Udp(asyncio.DatagramProtocol):
            def datagram_received(self, data, addr):
                service.enqueue(data, addr[0])

        async def handle_tcp(reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
            ip = writer.get_extra_info("peername")[0]
            try:
                while line := await reader.readline():
                    service.enqueue(line, ip)
            finally:
                writer.close()

        transport, _ = await loop.create_datagram_endpoint(Udp, local_addr=(s.syslog_host, s.syslog_port))
        server = await asyncio.start_server(handle_tcp, s.syslog_host, s.syslog_port)
        log.info("syslog listening on %s:%d udp/tcp", s.syslog_host, s.syslog_port)
        try:
            await self.writer(stop)
        finally:
            transport.close()
            server.close()
