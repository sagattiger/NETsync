"""The node worker: schedules discovery/polling and runs plugin background services.

In cluster mode one worker runs per node and only polls devices assigned to it.
"""

import asyncio
import json
import logging
import signal
from datetime import UTC, datetime, timedelta

from sqlalchemy import or_, select

from netsync import __version__
from netsync.alerting import dispatch, redis
from netsync.config import get_settings
from netsync.db import SessionLocal, init_db
from netsync.models import Device, Node
from netsync.plugins.registry import registry
from netsync.poller.pipeline import discover_device, poll_device

log = logging.getLogger(__name__)

JOBS_QUEUE = "netsync:jobs"


class Worker:
    def __init__(self) -> None:
        self.settings = get_settings()
        self.sem = asyncio.Semaphore(self.settings.poll_concurrency)
        self.running: set[int] = set()
        self.node_id: int | None = None
        self.stop = asyncio.Event()

    async def register_node(self) -> None:
        async with SessionLocal() as s:
            node = await s.scalar(select(Node).where(Node.name == self.settings.node_name))
            if node is None:
                node = Node(name=self.settings.node_name, is_local=True)
                s.add(node)
            node.last_seen = datetime.now(UTC)
            node.version = __version__
            await s.commit()
            self.node_id = node.id

    async def run_device(self, device_id: int, discover: bool) -> None:
        if device_id in self.running:
            return
        self.running.add(device_id)
        try:
            async with self.sem, SessionLocal() as s:
                device = await s.get(Device, device_id)
                if device is None:
                    return
                try:
                    if discover:
                        await discover_device(s, device)
                    events = await poll_device(s, device)
                except Exception as e:
                    log.warning("%s: %s failed: %s", device.hostname, "discovery" if discover else "poll", e)
                    await s.rollback()
                    device = await s.get(Device, device_id)
                    events = await poll_device(s, device)  # records the device as down
                await s.commit()
            await dispatch(events)
        except Exception:
            log.exception("device %s job failed", device_id)
        finally:
            self.running.discard(device_id)

    async def scheduler(self) -> None:
        while not self.stop.is_set():
            try:
                await self.register_node()
                now = datetime.now(UTC)
                poll_before = now - timedelta(seconds=self.settings.poll_interval)
                disc_before = now - timedelta(seconds=self.settings.discovery_interval)
                async with SessionLocal() as s:
                    rows = (await s.execute(
                        select(Device.id, Device.last_polled, Device.last_discovered).where(
                            Device.disabled.is_(False),
                            or_(Device.node_id.is_(None), Device.node_id == self.node_id),
                        )
                    )).all()
                for did, last_polled, last_disc in rows:
                    discover = last_disc is None or last_disc < disc_before
                    if discover or last_polled is None or last_polled < poll_before:
                        asyncio.create_task(self.run_device(did, discover))
            except Exception:
                log.exception("scheduler iteration failed")
            try:
                await asyncio.wait_for(self.stop.wait(), timeout=15)
            except TimeoutError:
                pass

    async def job_listener(self) -> None:
        """Immediate jobs from the API, e.g. 'discover now' on a new device."""
        while not self.stop.is_set():
            try:
                item = await redis().blpop([JOBS_QUEUE], timeout=5)
                if item:
                    job = json.loads(item[1])
                    asyncio.create_task(self.run_device(int(job["device_id"]), job.get("type") == "discover"))
            except Exception:
                log.exception("job listener error")
                await asyncio.sleep(5)

    async def main(self) -> None:
        await init_db()
        registry.load()
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(sig, self.stop.set)
            except NotImplementedError:
                pass
        tasks = [asyncio.create_task(self.scheduler()), asyncio.create_task(self.job_listener())]
        for svc in registry.services:
            log.info("starting background service %s", svc.name)
            tasks.append(asyncio.create_task(svc.run(self.stop), name=svc.name))
        await self.stop.wait()
        for t in tasks:
            t.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


async def enqueue_job(device_id: int, kind: str = "discover") -> None:
    await redis().rpush(JOBS_QUEUE, json.dumps({"device_id": device_id, "type": kind}))
