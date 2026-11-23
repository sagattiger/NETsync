"""Docker containers through the netsync-docker SNMP extend (sample output of agents/netsync-docker)."""

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from netsync.models import State
from netsync.plugins.base import DeviceContext
from netsync.plugins.builtin import docker

ID1, ID2, ID3, ID4 = "a" * 64, "b" * 64, "c" * 64, "d" * 64
T = "\t"


def sample(at: int) -> str:
    return "\n".join([
        f"# netsync-docker 1 {at}",
        T.join([ID1, "chatwoot-rails", "chatwoot/chatwoot:v4.1", "running", "Up 3 hours (healthy)",
                "0.0.0.0:3000->3000/tcp, :::3000->3000/tcp", "chatwoot", "rails", ""]),
        T.join([ID2, "postgres", "postgres:16", "running", "Up 3 hours (unhealthy)", "", "chatwoot", "postgres", ""]),
        T.join([ID3, "migrate", "chatwoot/chatwoot:v4.1", "exited", "Exited (0) 2 hours ago", "", "chatwoot", "migrate", ""]),
        T.join([ID4, "worker", "app:latest", "exited", "Exited (137) 5 minutes ago", "", "", "", "my-app"]),
        "---",
        T.join([ID1, "1.23%", "512.5MiB / 3.84GiB", "13.03%"]),
        T.join([ID2, "0.40%", "80MiB / 3.84GiB", "2.03%"]),
        T.join([ID3, "0.00%", "0B / 0B", "0.00%"]),
    ])


def test_parse_and_states():
    data = docker.parse(sample(1_000))
    assert data["time"] == 1000 and list(data["containers"]) == ["chatwoot-rails", "postgres", "migrate", "worker"]
    rails = data["containers"]["chatwoot-rails"]
    assert rails["id"] == "a" * 12 and rails["health"] == "healthy" and rails["project"] == "chatwoot"
    assert rails["cpu_pct"] == pytest.approx(1.23) and rails["mem_bytes"] == pytest.approx(512.5 * 1024 ** 2)
    assert rails["mem_limit"] == pytest.approx(3.84 * 1024 ** 3)
    assert data["containers"]["worker"]["exit_code"] == 137 and data["containers"]["worker"]["coolify"] == "my-app"
    states = {n: docker.container_state(c)[0] for n, c in data["containers"].items()}
    assert states == {"chatwoot-rails": State.OK, "postgres": State.CRIT, "migrate": State.WARN, "worker": State.CRIT}


def test_parse_odd_input():
    assert docker.parse("") == {"time": None, "containers": {}}
    assert docker.parse("garbage\n\tonly tabs\t\n---\nx")["containers"] == {}
    assert docker.size_bytes("1.5GB") == 1.5e9 and docker.size_bytes("nope") is None and docker.pct("--") is None
    assert docker.extend_index("netsync-docker") == "14." + ".".join(str(b) for b in b"netsync-docker")


class FakeSnmp:
    def __init__(self, out):
        self.lines = {str(i + 1): line.encode() for i, line in enumerate(out.splitlines())} if out is not None else {}

    async def walk(self, oid):
        assert oid.startswith(docker.NS_EXTEND_OUT_LINE)
        return self.lines


async def test_discover_and_poll():
    import time

    out = sample(int(time.time()) - 30)
    ctx = DeviceContext(SimpleNamespace(), FakeSnmp(out), [], datetime.now(UTC))
    specs = await docker.DockerModule().discover(ctx)
    assert [s.index for s in specs] == ["chatwoot-rails", "postgres", "migrate", "worker"]
    comps = [SimpleNamespace(kind="container", index=s.index, name=s.name, enabled=True, deleted=False, values={})
             for s in specs]
    res = await docker.DockerModule().poll(DeviceContext(SimpleNamespace(), FakeSnmp(out), comps, datetime.now(UTC)))
    checks = {c.name: c.state for c in res.checks}
    assert checks["Docker data"] == State.OK and checks["Container postgres"] == State.CRIT
    m = {(s.name, s.index): s.value for s in res.metrics}
    assert m[("containers_running", None)] == 2 and m[("cpu_pct", "chatwoot-rails")] == pytest.approx(1.23)


async def test_stale_list_and_missing_extend():
    comps = [SimpleNamespace(kind="container", index="postgres", name="postgres", enabled=True, deleted=False, values={})]
    res = await docker.DockerModule().poll(DeviceContext(SimpleNamespace(), FakeSnmp(sample(1_000)), comps, datetime.now(UTC)))
    assert next(c for c in res.checks if c.name == "Docker data").state == State.WARN
    res = await docker.DockerModule().poll(DeviceContext(SimpleNamespace(), FakeSnmp(None), comps, datetime.now(UTC)))
    assert [(c.name, c.state) for c in res.checks] == [("Docker data", State.CRIT)]
    assert await docker.DockerModule().discover(DeviceContext(SimpleNamespace(), FakeSnmp(None), [], datetime.now(UTC))) == []
