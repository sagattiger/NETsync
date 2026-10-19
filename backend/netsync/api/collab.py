"""Collaboration: device notes (markdown) and comments / pins on events."""

from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import and_, select

from netsync.api.deps import CurrentUser, Session, device_scope, get_device_for, require
from netsync.models import Device, DeviceNote, EventComment, Role, Service, StateChange, User

router = APIRouter(tags=["collaboration"])

NOTE_MAX = 100_000


# --------------------------------------------------------------------------- notes

class NoteIn(BaseModel):
    content: str = Field(max_length=NOTE_MAX)


@router.get("/devices/{device_id}/note")
async def get_note(device_id: int, user: CurrentUser, session: Session):
    await get_device_for(session, user, device_id)
    note = await session.get(DeviceNote, device_id)
    if not note:
        return {"content": "", "updated_at": None, "updated_by": None}
    return {"content": note.content, "updated_at": note.updated_at, "updated_by": note.updated_by}


@router.put("/devices/{device_id}/note")
async def save_note(device_id: int, body: NoteIn, session: Session, user=require(Role.OPERATOR)):
    await get_device_for(session, user, device_id)
    note = await session.get(DeviceNote, device_id)
    if note is None:
        note = DeviceNote(device_id=device_id)
        session.add(note)
    note.content = body.content
    note.updated_at = datetime.now(UTC)
    note.updated_by = user.username
    await session.commit()
    return {"content": note.content, "updated_at": note.updated_at, "updated_by": note.updated_by}


# --------------------------------------------------------------------------- event comments

class CommentIn(BaseModel):
    service_id: int
    event_time: datetime
    body: str = Field(min_length=1, max_length=5000)
    pinned: bool = False


class CommentUpdate(BaseModel):
    body: str | None = Field(None, min_length=1, max_length=5000)
    pinned: bool | None = None


def comment_out(c: EventComment, avatars: dict[int, str | None]) -> dict:
    return {
        "id": c.id, "device_id": c.device_id, "service_id": c.service_id, "event_time": c.event_time,
        "body": c.body, "pinned": c.pinned, "author": c.author, "author_id": c.author_id,
        "author_avatar": avatars.get(c.author_id) if c.author_id else None,
        "created_at": c.created_at, "updated_at": c.updated_at,
    }


async def author_avatars(session, comments: list[EventComment]) -> dict[int, str | None]:
    ids = {c.author_id for c in comments if c.author_id}
    if not ids:
        return {}
    rows = await session.execute(select(User.id, User.avatar_mime, User.avatar_version).where(User.id.in_(ids)))
    return {uid: f"/api/avatars/{uid}?v={ver}" if mime else None for uid, mime, ver in rows}


async def comments_for(session, device_ids: list[int] | None = None, pinned_only: bool = False) -> list[EventComment]:
    q = select(EventComment).order_by(EventComment.created_at)
    if device_ids is not None:
        q = q.where(EventComment.device_id.in_(device_ids))
    if pinned_only:
        q = q.where(EventComment.pinned.is_(True))
    return list(await session.scalars(q))


@router.post("/devices/{device_id}/events/comments")
async def add_comment(device_id: int, body: CommentIn, user: CurrentUser, session: Session):
    """Any user who can see the device may comment; pinning needs operator rights."""
    await get_device_for(session, user, device_id)
    if body.pinned and user.role == Role.VIEWER:
        raise HTTPException(403, "Only operators and admins can pin events")
    exists = await session.scalar(
        select(StateChange.service_id).where(
            StateChange.device_id == device_id,
            StateChange.service_id == body.service_id,
            StateChange.time == body.event_time,
        )
    )
    if exists is None:
        raise HTTPException(404, "Event not found")
    c = EventComment(device_id=device_id, service_id=body.service_id, event_time=body.event_time,
                     body=body.body.strip(), pinned=body.pinned, author_id=user.id, author=user.username)
    session.add(c)
    await session.commit()
    return comment_out(c, await author_avatars(session, [c]))


async def _own_comment(session, user: User, comment_id: int) -> EventComment:
    c = await session.get(EventComment, comment_id)
    if not c:
        raise HTTPException(404, "Comment not found")
    await get_device_for(session, user, c.device_id)
    return c


@router.patch("/events/comments/{comment_id}")
async def update_comment(comment_id: int, body: CommentUpdate, user: CurrentUser, session: Session):
    c = await _own_comment(session, user, comment_id)
    if body.body is not None:
        if c.author_id != user.id and user.role != Role.ADMIN:
            raise HTTPException(403, "You can only edit your own comments")
        c.body = body.body.strip()
        c.updated_at = datetime.now(UTC)
    if body.pinned is not None:
        if user.role == Role.VIEWER:
            raise HTTPException(403, "Only operators and admins can pin events")
        c.pinned = body.pinned
    await session.commit()
    return comment_out(c, await author_avatars(session, [c]))


@router.delete("/events/comments/{comment_id}")
async def delete_comment(comment_id: int, user: CurrentUser, session: Session):
    c = await _own_comment(session, user, comment_id)
    if c.author_id != user.id and user.role != Role.ADMIN:
        raise HTTPException(403, "You can only delete your own comments")
    await session.delete(c)
    await session.commit()
    return {"ok": True}


async def pinned_events(session, user: User, device_id: int | None = None) -> list[dict]:
    """Events with at least one pinned comment, newest pin first, with all their comments."""
    q = device_scope(select(Device.id, Device.hostname), user)
    if device_id is not None:
        q = q.where(Device.id == device_id)
    hostnames = {did: h for did, h in await session.execute(q)}
    if not hostnames:
        return []
    comments = await comments_for(session, list(hostnames))
    by_event: dict[tuple, list[EventComment]] = {}
    for c in comments:
        by_event.setdefault((c.device_id, c.service_id, c.event_time), []).append(c)
    pinned_keys = [k for k, cs in by_event.items() if any(c.pinned for c in cs)]
    if not pinned_keys:
        return []
    avatars = await author_avatars(session, comments)

    out = []
    for did, sid, t in pinned_keys:
        row = (await session.execute(
            select(StateChange, Service.name)
            .join(Service, Service.id == StateChange.service_id, isouter=True)
            .where(and_(StateChange.device_id == did, StateChange.service_id == sid, StateChange.time == t))
        )).first()
        if not row:
            continue
        sc, name = row
        cs = by_event[(did, sid, t)]
        out.append({
            "device_id": did, "hostname": hostnames[did], "service_id": sid, "service": name, "time": sc.time,
            "old_state": sc.old_state, "new_state": sc.new_state, "output": sc.output,
            "pinned_at": max(c.created_at for c in cs if c.pinned),
            "comments": [comment_out(c, avatars) for c in cs],
        })
    out.sort(key=lambda e: e["pinned_at"], reverse=True)
    return out


@router.get("/events/pinned")
async def all_pinned(user: CurrentUser, session: Session):
    return await pinned_events(session, user)


@router.get("/devices/{device_id}/events/pinned")
async def device_pinned(device_id: int, user: CurrentUser, session: Session):
    await get_device_for(session, user, device_id)
    return await pinned_events(session, user, device_id)
