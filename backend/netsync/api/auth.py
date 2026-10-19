from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sqlalchemy import select

from netsync.api.deps import CurrentUser, Session
from netsync.models import User
from netsync.security import create_token, hash_password, verify_password

router = APIRouter(prefix="/auth", tags=["auth"])


class LoginIn(BaseModel):
    username: str
    password: str


class MeOut(BaseModel):
    id: int
    username: str
    email: str | None
    role: str
    groups: list[str]


class PasswordIn(BaseModel):
    current: str
    new: str


@router.post("/login")
async def login(body: LoginIn, session: Session):
    user = await session.scalar(select(User).where(User.username == body.username))
    if not user or not user.is_active or not verify_password(body.password, user.password_hash):
        raise HTTPException(401, "Invalid username or password")
    return {"token": create_token(user.id)}


@router.get("/me", response_model=MeOut)
async def me(user: CurrentUser):
    return MeOut(id=user.id, username=user.username, email=user.email, role=user.role,
                 groups=[g.name for g in user.groups])


@router.post("/password")
async def change_password(body: PasswordIn, user: CurrentUser, session: Session):
    if not verify_password(body.current, user.password_hash):
        raise HTTPException(400, "Current password is wrong")
    if len(body.new) < 8:
        raise HTTPException(400, "Password must be at least 8 characters")
    u = await session.get(User, user.id)
    u.password_hash = hash_password(body.new)
    await session.commit()
    return {"ok": True}
