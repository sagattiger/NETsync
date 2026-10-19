import asyncio
import logging
import secrets
from contextlib import asynccontextmanager

from fastapi import APIRouter, FastAPI, WebSocket, WebSocketDisconnect
from sqlalchemy import func, select

from netsync import __version__
from netsync.alerting import EVENTS_CHANNEL, redis
from netsync.api import admin, auth, devices, monitoring, syslog
from netsync.db import SessionLocal, init_db
from netsync.models import Role, User
from netsync.plugins.registry import registry
from netsync.security import decode_token, hash_password

log = logging.getLogger(__name__)


async def ensure_admin() -> None:
    async with SessionLocal() as s:
        if await s.scalar(select(func.count()).select_from(User)):
            return
        password = secrets.token_urlsafe(12)
        s.add(User(username="admin", role=Role.ADMIN, password_hash=hash_password(password)))
        await s.commit()
        log.warning("=" * 60)
        log.warning("Created initial user 'admin' with password: %s", password)
        log.warning("Change it after the first login.")
        log.warning("=" * 60)


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    await ensure_admin()
    yield


def create_app() -> FastAPI:
    registry.load()
    app = FastAPI(title="NETsync", version=__version__, lifespan=lifespan, docs_url="/api/docs",
                  openapi_url="/api/openapi.json")

    api = APIRouter(prefix="/api")
    for r in (auth.router, devices.router, monitoring.router, admin.router, syslog.router):
        api.include_router(r)
    for plugin in registry.plugins.values():
        if plugin.router is not None:
            api.include_router(plugin.router, prefix=f"/plugins/{plugin.name}", tags=[f"plugin:{plugin.name}"])

    @api.get("/health")
    async def health():
        return {"status": "ok", "version": __version__}

    app.include_router(api)

    @app.websocket("/api/ws")
    async def events(ws: WebSocket, token: str):
        """Live state changes for the UI. Auth via ?token=<jwt>."""
        if decode_token(token) is None:
            await ws.close(code=4401)
            return
        await ws.accept()
        pubsub = redis().pubsub()
        await pubsub.subscribe(EVENTS_CHANNEL)
        try:
            while True:
                msg = await pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
                if msg:
                    await ws.send_text(msg["data"])
                else:
                    await asyncio.sleep(0.1)
        except (WebSocketDisconnect, RuntimeError):
            pass
        finally:
            await pubsub.unsubscribe(EVENTS_CHANNEL)
            await pubsub.aclose()

    return app


app = create_app()
