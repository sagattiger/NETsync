"""A plugin's event stream runs for hours: its secret check must not keep a database session open."""
import asyncio
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from netsync.tools import api, remote


class FakeSession:
    def __init__(self, found):
        self.found = found
        self.open = False

    async def __aenter__(self):
        self.open = True
        return self

    async def __aexit__(self, *exc):
        self.open = False

    async def scalar(self, _stmt):
        return self.found


def request(auth: str):
    return SimpleNamespace(headers={"authorization": auth})


def test_secret_check_closes_its_session(monkeypatch):
    plugin = SimpleNamespace(enabled=True, granted=["events"])
    s = FakeSession(plugin)
    monkeypatch.setattr(api, "SessionLocal", lambda: s)
    got = asyncio.run(api.calling_plugin(request(f"Bearer {remote.SECRET_PREFIX}abc")))
    assert got is plugin
    assert s.open is False


def test_unknown_secret_is_refused(monkeypatch):
    monkeypatch.setattr(api, "SessionLocal", lambda: FakeSession(None))
    with pytest.raises(HTTPException) as e:
        asyncio.run(api.calling_plugin(request(f"Bearer {remote.SECRET_PREFIX}abc")))
    assert e.value.status_code == 401
