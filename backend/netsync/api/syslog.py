from datetime import datetime

from fastapi import APIRouter
from sqlalchemy import select

from netsync.api.deps import CurrentUser, Session, device_scope
from netsync.api.schemas import SyslogOut
from netsync.models import AIJob, Role, SyslogMessage

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
    rows = [SyslogOut.model_validate(m) for m in await session.scalars(query)]
    if rows:
        # latest AI analysis per message (sticker in the UI)
        jobs = await session.execute(
            select(AIJob.syslog_id, AIJob.id, AIJob.status)
            .where(AIJob.kind == "syslog", AIJob.syslog_id.in_([r.id for r in rows]))
            .order_by(AIJob.created_at)
        )
        latest = {sid: {"job_id": jid, "status": st} for sid, jid, st in jobs}
        for r in rows:
            r.ai = latest.get(r.id)
    return rows
