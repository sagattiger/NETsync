"""A rediscover/poll request for a device that is busy is queued, not dropped."""

import asyncio

from netsync.poller import worker as worker_mod
from netsync.poller.worker import Worker


async def test_busy_device_job_is_queued_then_run(monkeypatch):
    def no_db():
        raise RuntimeError("no database in unit tests")

    monkeypatch.setattr(worker_mod, "SessionLocal", no_db)
    w = Worker()
    real = Worker.run_device.__get__(w)
    calls: list[tuple[int, bool]] = []

    async def spy(device_id: int, discover: bool) -> None:
        calls.append((device_id, discover))
        await real(device_id, discover)

    w.run_device = spy  # type: ignore[method-assign]

    w.running.add(5)  # a scheduled poll is running
    await real(5, False)
    await real(5, True)  # "Rediscover" clicked meanwhile: discovery wins
    await real(5, False)
    assert w.queued == {5: True} and calls == []

    w.running.discard(5)
    await real(5, False)  # the running job ends (here: fails fast) ...
    await asyncio.sleep(0.05)
    assert calls == [(5, True)]  # ... and the queued rediscovery runs right after
    assert w.queued == {} and w.running == set()
