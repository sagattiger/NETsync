from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from netsync.db import get_session
from netsync.models import Device, Role, User, device_group_members
from netsync.security import decode_token

bearer = HTTPBearer(auto_error=False)

Session = Annotated[AsyncSession, Depends(get_session)]


async def current_user(
    session: Session, creds: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)]
) -> User:
    user_id = decode_token(creds.credentials) if creds else None
    user = await session.get(User, user_id) if user_id else None
    if not user or not user.is_active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not authenticated")
    return user


CurrentUser = Annotated[User, Depends(current_user)]

ROLE_RANK = {Role.VIEWER: 0, Role.OPERATOR: 1, Role.ADMIN: 2}


def require(role: Role):
    async def dep(user: CurrentUser) -> User:
        if ROLE_RANK[Role(user.role)] < ROLE_RANK[role]:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Insufficient permissions")
        return user

    return Depends(dep)


def device_scope(query, user: User, device_col=Device.id):
    """Restrict a query to devices the user may see (admins see everything)."""
    if user.role == Role.ADMIN:
        return query
    group_ids = [g.id for g in user.groups]
    allowed = select(device_group_members.c.device_id).where(device_group_members.c.group_id.in_(group_ids))
    return query.where(device_col.in_(allowed))


async def get_device_for(session: AsyncSession, user: User, device_id: int) -> Device:
    q = device_scope(select(Device).where(Device.id == device_id), user)
    device = await session.scalar(q)
    if not device:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Device not found")
    return device
