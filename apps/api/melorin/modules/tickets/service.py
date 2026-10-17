"""Shared ticket helpers used by the customer router and the admin router."""

import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from melorin.core import events
from melorin.core.db import utcnow
from melorin.modules.tickets.models import Ticket, TicketMessage
from melorin.modules.tickets.schemas import TicketMessageOut, TicketOut

EDIT_BODY_MAX = 10_000


def ticket_out(t: Ticket) -> TicketOut:
    return TicketOut(
        id=t.id,
        store_id=t.store_id,
        number=t.number,
        subject=t.subject,
        status=t.status,
        priority=t.priority or "normal",
        department=t.department,
        created_at=t.created_at,
        updated_at=t.updated_at,
    )


def message_out(m: TicketMessage) -> TicketMessageOut:
    return TicketMessageOut(
        id=m.id,
        author_id=m.author_id,
        is_staff=m.is_staff,
        is_internal=bool(m.is_internal),
        body=m.body,
        created_at=m.created_at,
        edited_at=m.edited_at,
    )


async def list_messages(session: AsyncSession, ticket_id: uuid.UUID, *, include_internal: bool) -> list[TicketMessage]:
    q = select(TicketMessage).where(TicketMessage.ticket_id == ticket_id).order_by(TicketMessage.created_at)
    if not include_internal:
        q = q.where(TicketMessage.is_internal.is_(False))
    return list((await session.scalars(q)).all())


async def message_counts(session: AsyncSession, ticket_ids: list[uuid.UUID]) -> dict[uuid.UUID, int]:
    if not ticket_ids:
        return {}
    rows = await session.execute(
        select(TicketMessage.ticket_id, func.count())
        .where(TicketMessage.ticket_id.in_(ticket_ids), TicketMessage.is_internal.is_(False))
        .group_by(TicketMessage.ticket_id)
    )
    return {tid: n for tid, n in rows.all()}


async def last_messages(session: AsyncSession, ticket_ids: list[uuid.UUID]) -> dict[uuid.UUID, TicketMessage]:
    """Latest customer-visible message for each ticket (used for list previews)."""
    if not ticket_ids:
        return {}
    latest = (
        select(TicketMessage.ticket_id, func.max(TicketMessage.created_at).label("at"))
        .where(TicketMessage.ticket_id.in_(ticket_ids), TicketMessage.is_internal.is_(False))
        .group_by(TicketMessage.ticket_id)
        .subquery()
    )
    rows = await session.scalars(
        select(TicketMessage)
        .join(latest, (TicketMessage.ticket_id == latest.c.ticket_id) & (TicketMessage.created_at == latest.c.at))
        .where(TicketMessage.is_internal.is_(False))
    )
    return {m.ticket_id: m for m in rows.all()}


async def notify_customer(session: AsyncSession, t: Ticket, text: str) -> None:
    """Queue a Telegram/in-app notification for the ticket owner (delivered by the outbox worker)."""
    preview = text.strip().replace("\n", " ")
    if len(preview) > 280:
        preview = preview[:277] + "…"
    await events.emit(
        session,
        events.NOTIFY,
        {
            "user_id": t.user_id,
            "store_id": t.store_id,
            "kind": "ticket_reply",
            "title": f"🎧 پاسخ جدید به تیکت #{t.number or str(t.id)[:6]}",
            "body": f"{t.subject}\n\n{preview}",
            "dedup_key": f"ticket_reply:{t.id}:{uuid.uuid4().hex[:8]}",
        },
    )


def touch(t: Ticket) -> None:
    t.updated_at = utcnow()
