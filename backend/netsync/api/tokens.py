"""API tokens for the public dashboards API.

Tokens look like ``nst_`` + 40 url-safe characters. Only a SHA-256 hash is stored. They are
accepted exclusively by /api/public/* (see ``public_token``); the normal API keeps using JWTs,
so a leaked token can never read devices, IPs, syslog or users.
"""

import hashlib
import logging
import secrets
import time
from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from netsync.api.deps import Session, require
from netsync.models import ApiToken, Role

log = logging.getLogger(__name__)

router = APIRouter(prefix="/tokens", tags=["api tokens"])

TOKEN_PREFIX = "nst_"
RATE_LIMIT_PER_MINUTE = 120
LAST_USED_RESOLUTION = timedelta(minutes=1)


def generate_token() -> str:
    return TOKEN_PREFIX + secrets.token_urlsafe(30)[:40]  # 30 random bytes -> 40 url-safe chars


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def token_problem(row: ApiToken | None, now: datetime) -> str | None:
    """Why a token row can't be used, or None when it is valid."""
    if row is None:
        return "Invalid API token"
    if row.revoked:
        return "API token revoked"
    if row.expires_at is not None and row.expires_at <= now:
        return "API token expired"
    return None


def token_out(t: ApiToken) -> dict:
    now = datetime.now(UTC)
    return {
        "id": t.id, "name": t.name, "prefix": t.prefix, "created_by": t.created_by, "created_at": t.created_at,
        "last_used_at": t.last_used_at, "expires_at": t.expires_at, "revoked": t.revoked,
        "status": "revoked" if t.revoked else "expired" if t.expires_at and t.expires_at <= now else "active",
    }


# --------------------------------------------------------------------------- admin endpoints

class TokenIn(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    expires_at: datetime | None = None


@router.get("", dependencies=[require(Role.ADMIN)])
async def list_tokens(session: Session):
    return [token_out(t) for t in await session.scalars(select(ApiToken).order_by(ApiToken.created_at.desc()))]


@router.post("")
async def create_token(body: TokenIn, session: Session, user=require(Role.ADMIN)):
    expires = body.expires_at
    if expires is not None:
        if expires.tzinfo is None:
            expires = expires.replace(tzinfo=UTC)
        if expires <= datetime.now(UTC):
            raise HTTPException(400, "Expiry must be in the future")
    token = generate_token()
    row = ApiToken(name=body.name.strip(), token_hash=hash_token(token), prefix=token[:8],
                   created_by=user.username, expires_at=expires)
    session.add(row)
    await session.commit()
    # the only time the full token is ever returned
    return {**token_out(row), "token": token}


@router.delete("/{token_id}", dependencies=[require(Role.ADMIN)])
async def revoke_token(token_id: int, session: Session):
    row = await session.get(ApiToken, token_id)
    if not row:
        raise HTTPException(404, "Token not found")
    row.revoked = True
    await session.commit()
    return token_out(row)


# --------------------------------------------------------------------------- auth for /api/public

async def _rate_limited(token_id: int) -> bool:
    from netsync.alerting import redis

    key = f"netsync:rl:token:{token_id}:{int(time.time() // 60)}"
    try:
        count = await redis().incr(key)
        if count == 1:
            await redis().expire(key, 90)
        return count > RATE_LIMIT_PER_MINUTE
    except Exception:
        log.debug("rate limit check skipped (redis unavailable)", exc_info=True)
        return False


async def public_token(request: Request, session: Session) -> ApiToken:
    """Dependency of the public endpoints only: requires ``Authorization: Bearer nst_...``."""
    header = request.headers.get("authorization", "")
    scheme, _, value = header.partition(" ")
    value = value.strip()
    if scheme.lower() != "bearer" or not value.startswith(TOKEN_PREFIX):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "API token required",
                            headers={"WWW-Authenticate": "Bearer"})
    now = datetime.now(UTC)
    row = await session.scalar(select(ApiToken).where(ApiToken.token_hash == hash_token(value)))
    if problem := token_problem(row, now):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, problem, headers={"WWW-Authenticate": "Bearer"})
    if await _rate_limited(row.id):
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Rate limit exceeded (120 requests/minute)",
                            headers={"Retry-After": "60"})
    if row.last_used_at is None or now - row.last_used_at >= LAST_USED_RESOLUTION:
        row.last_used_at = now
        await session.commit()
    return row


PublicToken = Annotated[ApiToken, Depends(public_token)]
