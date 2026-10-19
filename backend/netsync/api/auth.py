import base64
import binascii
import re
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, HTTPException, Response
from pydantic import BaseModel, Field
from sqlalchemy import select, update
from sqlalchemy.orm import undefer

from netsync.api.deps import CurrentUser, Session
from netsync.models import User
from netsync.security import create_token, hash_password, verify_password

router = APIRouter(prefix="/auth", tags=["auth"])
avatars = APIRouter(tags=["auth"])

AVATAR_MAX_BYTES = 512 * 1024
AVATAR_TYPES = {"image/png", "image/jpeg", "image/webp", "image/gif"}
DATA_URL = re.compile(r"^data:(image/[a-z+]+);base64,(.+)$", re.S)

# UI settings accepted in preferences, with allowed values (None = any string).
PREFERENCE_KEYS: dict[str, set | None] = {
    "theme": {"dark", "light", "system"},
    "default_range": {"1h", "6h", "24h", "7d", "30d", "1y"},
    "time_format": {"24h", "12h"},
    "refresh_interval": {"10", "30", "60", "300"},
    "landing_page": {"/", "/problems", "/devices"},
    "table_density": {"comfortable", "compact"},
}


class LoginIn(BaseModel):
    username: str
    password: str


class MeOut(BaseModel):
    id: int
    username: str
    email: str | None
    full_name: str | None
    phone: str | None
    job_title: str | None
    timezone: str | None
    role: str
    groups: list[str]
    preferences: dict[str, Any]
    avatar_url: str | None
    created_at: datetime
    last_login: datetime | None
    password_changed_at: datetime | None


class ProfileIn(BaseModel):
    email: str | None = Field(None, max_length=255)
    full_name: str | None = Field(None, max_length=128)
    phone: str | None = Field(None, max_length=64)
    job_title: str | None = Field(None, max_length=128)
    timezone: str | None = Field(None, max_length=64)
    preferences: dict[str, Any] | None = None


class PasswordIn(BaseModel):
    current: str
    new: str


class AvatarIn(BaseModel):
    data_url: str


def avatar_url(user: User) -> str | None:
    return f"/api/avatars/{user.id}?v={user.avatar_version}" if user.avatar_mime else None


def me_out(user: User) -> MeOut:
    return MeOut(
        id=user.id, username=user.username, email=user.email, full_name=user.full_name, phone=user.phone,
        job_title=user.job_title, timezone=user.timezone, role=user.role, groups=[g.name for g in user.groups],
        preferences=user.preferences or {}, avatar_url=avatar_url(user), created_at=user.created_at,
        last_login=user.last_login, password_changed_at=user.password_changed_at,
    )


@router.post("/login")
async def login(body: LoginIn, session: Session):
    user = await session.scalar(select(User).where(User.username == body.username))
    if not user or not user.is_active or not verify_password(body.password, user.password_hash):
        raise HTTPException(401, "Invalid username or password")
    user.last_login = datetime.now(UTC)
    await session.commit()
    return {"token": create_token(user.id)}


@router.get("/me", response_model=MeOut)
async def me(user: CurrentUser):
    return me_out(user)


@router.patch("/me", response_model=MeOut)
async def update_me(body: ProfileIn, user: CurrentUser, session: Session):
    u = await session.get(User, user.id)
    data = body.model_dump(exclude_unset=True)
    if (prefs := data.pop("preferences", None)) is not None:
        merged = dict(u.preferences or {})
        for key, value in prefs.items():
            allowed = PREFERENCE_KEYS.get(key, False)
            if allowed is False:
                raise HTTPException(400, f"Unknown preference {key}")
            if allowed is not None and str(value) not in allowed:
                raise HTTPException(400, f"Invalid value for {key}")
            merged[key] = str(value)
        u.preferences = merged
    for key, value in data.items():
        setattr(u, key, (value or "").strip() or None)
    await session.commit()
    return me_out(u)


@router.post("/password")
async def change_password(body: PasswordIn, user: CurrentUser, session: Session):
    if not verify_password(body.current, user.password_hash):
        raise HTTPException(400, "Current password is wrong")
    if len(body.new) < 8:
        raise HTTPException(400, "Password must be at least 8 characters")
    if body.new == body.current:
        raise HTTPException(400, "New password must be different")
    u = await session.get(User, user.id)
    u.password_hash = hash_password(body.new)
    u.password_changed_at = datetime.now(UTC)
    await session.commit()
    return {"ok": True}


@router.put("/me/avatar", response_model=MeOut)
async def set_avatar(body: AvatarIn, user: CurrentUser, session: Session):
    m = DATA_URL.match(body.data_url)
    if not m or m.group(1) not in AVATAR_TYPES:
        raise HTTPException(400, "Avatar must be a PNG, JPEG, WebP or GIF image")
    try:
        data = base64.b64decode(m.group(2), validate=True)
    except (binascii.Error, ValueError) as e:
        raise HTTPException(400, "Invalid image data") from e
    if len(data) > AVATAR_MAX_BYTES:
        raise HTTPException(400, "Avatar must be smaller than 512 KB")
    u = await session.get(User, user.id)
    u.avatar, u.avatar_mime, u.avatar_version = data, m.group(1), (u.avatar_version or 0) + 1
    await session.commit()
    return me_out(u)


@router.delete("/me/avatar", response_model=MeOut)
async def remove_avatar(user: CurrentUser, session: Session):
    await session.execute(update(User).where(User.id == user.id).values(avatar=None, avatar_mime=None))
    await session.commit()
    u = await session.get(User, user.id)
    await session.refresh(u)
    return me_out(u)


@avatars.get("/avatars/{user_id}")
async def get_avatar(user_id: int, session: Session):
    """Avatars are served without auth so <img> tags work; they are versioned via ?v= and cached."""
    u = await session.scalar(select(User).options(undefer(User.avatar)).where(User.id == user_id))
    if not u or not u.avatar:
        raise HTTPException(404)
    return Response(u.avatar, media_type=u.avatar_mime,
                    headers={"Cache-Control": "public, max-age=31536000, immutable"})
