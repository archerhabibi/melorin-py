"""Admin API - live panel events: status, connect / disconnect, list, process, retry failed (PG-03)."""

import datetime as dt
import logging
import uuid

from fastapi import APIRouter
from pydantic import BaseModel, Field

from melorin.core import audit
from melorin.core.deps import AdminUser, Session
from melorin.core.errors import AppError, NotFound
from melorin.kernel.models.vpn import Panel
from melorin.modules.panelops import panel_events
from melorin.modules.panelops import panel_events_admin

from melorin.modules.panelops import queries

router = APIRouter(prefix="/admin", tags=["admin"])
log = logging.getLogger("melorin.admin.panel_live_events")


# ------------------------------------------------------------------------------------------- live panel events (PG-03)
class EventsConnectIn(BaseModel):
    confirm: bool = Field(description="must be true: this writes the webhook target into the PANEL's settings")
    rotate_secret: bool = False


class EventOut(BaseModel):
    id: uuid.UUID
    action: str
    username: str | None = None
    status: str
    attempts: int
    outcome: str | None = None
    received_at: dt.datetime
    processed_at: dt.datetime | None = None
    enqueued_at: dt.datetime | None = None
    vpn_account_id: uuid.UUID | None = None


async def _panel_or_404(session, panel_id: uuid.UUID) -> Panel:
    panel = await session.get(Panel, panel_id)
    if not panel:
        raise NotFound("پنل")
    return panel


@router.get("/panels/{panel_id}/events/status")
async def panel_events_status(panel_id: uuid.UUID, _: AdminUser, session: Session, live: bool = False):
    """Connection state, counters and (``live=true``) what the panel itself has configured. Never returns the secret."""
    return await panel_events_admin.status(session, await _panel_or_404(session, panel_id), live=live)


@router.post("/panels/{panel_id}/events/connect")
async def panel_events_connect(panel_id: uuid.UUID, body: EventsConnectIn, admin: AdminUser, session: Session):
    if not body.confirm:
        raise AppError("CONFIRM_REQUIRED", "برای نوشتن تنظیمات روی پنل تأیید لازم است.", 422)
    panel = await _panel_or_404(session, panel_id)
    state = await panel_events_admin.connect(session, panel, rotate=body.rotate_secret)
    audit.record(
        session,
        "panel.events.connected",
        actor_id=admin.id,
        actor_type="admin",
        entity_type="panel",
        entity_id=panel.id,
        data={"rotate_secret": body.rotate_secret, "warnings": len(state["warnings"])},
    )
    await session.commit()
    return state


@router.post("/panels/{panel_id}/events/disconnect")
async def panel_events_disconnect(panel_id: uuid.UUID, admin: AdminUser, session: Session):
    panel = await _panel_or_404(session, panel_id)
    state = await panel_events_admin.disconnect(session, panel)
    audit.record(
        session, "panel.events.disconnected", actor_id=admin.id, actor_type="admin", entity_type="panel", entity_id=panel.id, data={}
    )
    await session.commit()
    return state


@router.get("/panels/{panel_id}/events")
async def panel_events_list(
    panel_id: uuid.UUID,
    _: AdminUser,
    session: Session,
    status: str | None = None,
    action: str | None = None,
    username: str | None = None,
    limit: int = 50,
    offset: int = 0,
):
    await _panel_or_404(session, panel_id)
    if status and status not in ("pending", "processing", "processed", "ignored", "failed"):
        raise AppError("BAD_STATUS", "وضعیت نامعتبر است.", 422)
    total, rows = await queries.event_rows(
        session, panel_id, status=status, action=action, username=username, limit=max(1, min(limit, 200)), offset=max(0, offset)
    )
    return {
        "total": total,
        "items": [
            EventOut(
                id=r.id,
                action=r.action,
                username=r.username,
                status=r.status,
                attempts=int(r.attempts or 0),
                outcome=r.outcome,
                received_at=r.received_at,
                processed_at=r.processed_at,
                enqueued_at=r.enqueued_at,
                vpn_account_id=r.vpn_account_id,
            )
            for r in rows
        ],
    }


@router.post("/panels/{panel_id}/events/process")
async def panel_events_process(panel_id: uuid.UUID, admin: AdminUser, session: Session):
    """Run one processing sweep for this panel now (the worker does the same every few seconds)."""
    await _panel_or_404(session, panel_id)
    stats = await panel_events.run_pending(panel_id=panel_id)
    audit.record(
        session,
        "panel.events.processed",
        actor_id=admin.id,
        actor_type="admin",
        entity_type="panel",
        entity_id=panel_id,
        data={"claimed": stats.claimed},
    )
    await session.commit()
    return {
        "claimed": stats.claimed,
        "processed": stats.processed,
        "ignored": stats.ignored,
        "retried": stats.retried,
        "failed": stats.failed,
    }


@router.post("/panels/{panel_id}/events/retry-failed")
async def panel_events_retry_failed(panel_id: uuid.UUID, admin: AdminUser, session: Session, event_id: uuid.UUID | None = None):
    await _panel_or_404(session, panel_id)
    n = await panel_events_admin.retry_failed(session, panel_id, event_id=event_id)
    audit.record(
        session, "panel.events.retry", actor_id=admin.id, actor_type="admin", entity_type="panel", entity_id=panel_id, data={"requeued": n}
    )
    await session.commit()
    return {"requeued": n}
