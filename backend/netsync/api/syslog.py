from datetime import datetime

from fastapi import APIRouter
from sqlalchemy import select

from netsync.api.deps import CurrentUser, Session, device_scope
from netsync.api.schemas import SyslogOut
from netsync.models import Role, SyslogMessage

router = APIRouter(prefix="/syslog", tags=["syslog"])


@router.get("", response_model=list[SyslogOut])
async def search(
    user: CurrentUser,
    session: Session,
    device_id: int | None = None,
    q: str | None = None,
    program: str | None = None,
    max_severity: int = 7,
    before: datetime | None = None,
    limit: int = 200,
):
    query = select(SyslogMessage).where(SyslogMessage.severity <= max_severity)
    if device_id:
        query = query.where(SyslogMessage.device_id == device_id)
    if q:
        query = query.where(SyslogMessage.message.ilike(f"%{q}%"))
    if program:
        query = query.where(SyslogMessage.program == program)
    if before:
        query = query.where(SyslogMessage.time < before)
    if user.role != Role.ADMIN:
        # unmatched messages (no device) are only visible to admins
        query = device_scope(query.where(SyslogMessage.device_id.is_not(None)), user, SyslogMessage.device_id)
    query = query.order_by(SyslogMessage.time.desc()).limit(min(limit, 2000))
    return list(await session.scalars(query))
