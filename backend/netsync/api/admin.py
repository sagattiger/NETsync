"""Users, device groups, plugins and nodes."""

from fastapi import APIRouter, HTTPException
from sqlalchemy import select

from netsync.api.deps import CurrentUser, Session, require
from netsync.api.schemas import GroupIn, GroupOut, UserIn, UserOut, UserUpdate
from netsync.models import DeviceGroup, Node, Role, User
from netsync.plugins.registry import registry
from netsync.security import hash_password

router = APIRouter(tags=["admin"])


async def _groups(session, ids: list[int]) -> list[DeviceGroup]:
    return list(await session.scalars(select(DeviceGroup).where(DeviceGroup.id.in_(ids))))


@router.get("/users", response_model=list[UserOut], dependencies=[require(Role.ADMIN)])
async def list_users(session: Session):
    return list(await session.scalars(select(User).order_by(User.username)))


@router.post("/users", response_model=UserOut, dependencies=[require(Role.ADMIN)])
async def add_user(body: UserIn, session: Session):
    if await session.scalar(select(User.id).where(User.username == body.username)):
        raise HTTPException(409, "User exists")
    user = User(username=body.username, email=body.email, role=body.role,
                password_hash=hash_password(body.password), groups=await _groups(session, body.group_ids))
    session.add(user)
    await session.commit()
    return user


@router.patch("/users/{user_id}", response_model=UserOut, dependencies=[require(Role.ADMIN)])
async def update_user(user_id: int, body: UserUpdate, session: Session):
    user = await session.get(User, user_id)
    if not user:
        raise HTTPException(404)
    data = body.model_dump(exclude_unset=True)
    if (pw := data.pop("password", None)) is not None:
        user.password_hash = hash_password(pw)
    if (gids := data.pop("group_ids", None)) is not None:
        user.groups = await _groups(session, gids)
    for k, v in data.items():
        setattr(user, k, v)
    await session.commit()
    return user


@router.delete("/users/{user_id}")
async def delete_user(user_id: int, session: Session, me=require(Role.ADMIN)):
    if user_id == me.id:
        raise HTTPException(400, "You cannot delete yourself")
    user = await session.get(User, user_id)
    if user:
        await session.delete(user)
        await session.commit()
    return {"ok": True}


@router.get("/groups", response_model=list[GroupOut])
async def list_groups(user: CurrentUser, session: Session):
    q = select(DeviceGroup).order_by(DeviceGroup.name)
    if user.role != Role.ADMIN:
        q = q.where(DeviceGroup.id.in_([g.id for g in user.groups]))
    return list(await session.scalars(q))


@router.post("/groups", response_model=GroupOut, dependencies=[require(Role.ADMIN)])
async def add_group(body: GroupIn, session: Session):
    group = DeviceGroup(**body.model_dump())
    session.add(group)
    await session.commit()
    return group


@router.delete("/groups/{group_id}", dependencies=[require(Role.ADMIN)])
async def delete_group(group_id: int, session: Session):
    group = await session.get(DeviceGroup, group_id)
    if group:
        await session.delete(group)
        await session.commit()
    return {"ok": True}


@router.get("/plugins")
async def plugins(user: CurrentUser):
    return [
        {
            "name": p.name,
            "version": p.version,
            "description": p.description,
            "builtin": p.builtin,
            "modules": [m.name for m in p.modules],
            "channels": [c.name for c in p.channels],
            "services": [s.name for s in p.services],
            "ui_tabs": [t.__dict__ for t in p.ui_tabs],
        }
        for p in registry.plugins.values()
    ]


@router.get("/nodes")
async def nodes(user: CurrentUser, session: Session):
    return [
        {"id": n.id, "name": n.name, "is_local": n.is_local, "last_seen": n.last_seen, "version": n.version}
        for n in await session.scalars(select(Node).order_by(Node.name))
    ]
