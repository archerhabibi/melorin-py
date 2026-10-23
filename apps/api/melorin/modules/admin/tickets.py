"""Admin API - tickets routes (split from the former 1,900-line router; paths unchanged)."""

import logging
import uuid
from fastapi import APIRouter, Query
from sqlalchemy import select
from melorin.core import audit
from melorin.core.deps import AdminUser, Session
from melorin.core.errors import AppError, NotFound
from melorin.kernel.models.identity import User
from melorin.kernel.models.stores import Store
from melorin.kernel.models.tickets import Ticket
from melorin.modules.tickets.schemas import AdminAddMessage, AdminUpdateTicket, EditMessage as EditTicketMessage

router = APIRouter(prefix="/admin", tags=["admin"])
log = logging.getLogger("melorin.admin")


def _ticket_row(t, user, store, count, last):
    return {
        "id": t.id,
        "number": t.number,
        "user_id": t.user_id,
        "store_id": t.store_id,
        "subject": t.subject,
        "status": t.status,
        "priority": t.priority or "normal",
        "department": t.department,
        "created_at": t.created_at,
        "updated_at": t.updated_at,
        "customer": {"id": user.id, "name": user.display_name, "email": user.email} if user else None,
        "store_name": store.name if store else None,
        "message_count": count,
        "last_message": (last.body[:140] if last else None),
        "last_from_staff": bool(last.is_staff) if last else None,
    }


async def _ticket_rows(session, tickets):
    from melorin.modules.tickets import service as ticket_service

    ids = [t.id for t in tickets]
    users = (
        {u.id: u for u in (await session.scalars(select(User).where(User.id.in_({t.user_id for t in tickets})))).all()} if tickets else {}
    )
    stores_ = (
        {s.id: s for s in (await session.scalars(select(Store).where(Store.id.in_({t.store_id for t in tickets})))).all()}
        if tickets
        else {}
    )
    counts = await ticket_service.message_counts(session, ids)
    last = await ticket_service.last_messages(session, ids)
    return [_ticket_row(t, users.get(t.user_id), stores_.get(t.store_id), counts.get(t.id, 0), last.get(t.id)) for t in tickets]


@router.get("/tickets", response_model=list[dict])
async def tickets(
    _: AdminUser,
    session: Session,
    status: str | None = Query(default=None),
    priority: str | None = Query(default=None),
    store_id: uuid.UUID | None = Query(default=None),
    q: str | None = Query(default=None, max_length=100),
):
    from sqlalchemy import or_

    stmt = select(Ticket).order_by(Ticket.updated_at.desc()).limit(500)
    if status:
        stmt = stmt.where(Ticket.status == status)
    if priority:
        stmt = stmt.where(Ticket.priority == priority)
    if store_id:
        stmt = stmt.where(Ticket.store_id == store_id)
    if q:
        like = f"%{q.strip()}%"
        stmt = stmt.where(or_(Ticket.subject.ilike(like), Ticket.number.ilike(like)))
    return await _ticket_rows(session, list((await session.scalars(stmt)).all()))


@router.get("/tickets/{ticket_id}", response_model=dict)
async def ticket_detail(ticket_id: uuid.UUID, admin: AdminUser, session: Session):
    from melorin.modules.tickets import service as ticket_service

    t = await session.get(Ticket, ticket_id)
    if not t:
        raise NotFound("تیکت")
    row = (await _ticket_rows(session, [t]))[0]
    msgs = await ticket_service.list_messages(session, t.id, include_internal=True)
    authors = {u.id: u for u in (await session.scalars(select(User).where(User.id.in_({m.author_id for m in msgs})))).all()} if msgs else {}
    row["messages"] = [
        {
            **ticket_service.message_out(m).model_dump(mode="json"),
            "author_name": (authors[m.author_id].display_name or authors[m.author_id].email) if m.author_id in authors else None,
            "mine": m.author_id == admin.id,
        }
        for m in msgs
    ]
    return row


@router.patch("/tickets/{ticket_id}", response_model=dict)
async def update_ticket(ticket_id: uuid.UUID, body: AdminUpdateTicket, admin: AdminUser, session: Session):
    from melorin.core import events
    from melorin.modules.tickets import service as ticket_service

    t = await session.get(Ticket, ticket_id)
    if not t:
        raise NotFound("تیکت")
    changes = {k: v for k, v in body.model_dump(exclude_unset=True).items() if v is not None or k == "department"}
    if "subject" in changes:
        changes["subject"] = changes["subject"].strip()
    if "department" in changes:
        changes["department"] = (changes["department"] or "").strip() or None
    before = {k: getattr(t, k) for k in changes}
    changes = {k: v for k, v in changes.items() if v != before[k]}
    if changes:
        for k, v in changes.items():
            setattr(t, k, v)
        ticket_service.touch(t)
        audit.record(
            session,
            "ticket.admin_updated",
            actor_id=admin.id,
            actor_type="admin",
            entity_type="ticket",
            entity_id=t.id,
            store_id=t.store_id,
            data={"before": {k: before[k] for k in changes}, "after": changes},
        )
        await events.emit(session, events.TICKET_UPDATED, {"ticket_id": t.id, "store_id": t.store_id})
        await session.commit()
    return (await _ticket_rows(session, [t]))[0]


@router.post("/tickets/{ticket_id}/messages", response_model=dict)
async def ticket_reply(ticket_id: uuid.UUID, body: AdminAddMessage, admin: AdminUser, session: Session):
    """Staff reply or internal note. Replies notify the customer; internal notes never leave the admin panel."""
    from melorin.core import events
    from melorin.modules.tickets import service as ticket_service
    from melorin.kernel.models.tickets import TicketMessage

    t = await session.get(Ticket, ticket_id)
    if not t:
        raise NotFound("تیکت")
    text = body.body.strip()
    if not text:
        raise AppError("EMPTY_MESSAGE", "متن پیام نمی‌تواند خالی باشد.", 422)
    m = TicketMessage(ticket_id=t.id, author_id=admin.id, is_staff=True, is_internal=body.internal, body=text)
    session.add(m)
    if not body.internal:
        t.status = body.status or "answered"
    elif body.status:
        t.status = body.status
    ticket_service.touch(t)
    await session.flush()
    audit.record(
        session,
        "ticket.note_added" if body.internal else "ticket.replied",
        actor_id=admin.id,
        actor_type="admin",
        entity_type="ticket",
        entity_id=t.id,
        store_id=t.store_id,
    )
    await events.emit(session, events.TICKET_UPDATED, {"ticket_id": t.id, "store_id": t.store_id, "message_id": m.id})
    if not body.internal and t.user_id != admin.id:
        await ticket_service.notify_customer(session, t, body.body)
    await session.commit()
    return {**ticket_service.message_out(m).model_dump(mode="json"), "ticket_status": t.status}


@router.patch("/tickets/{ticket_id}/messages/{message_id}", response_model=dict)
async def ticket_edit_message(ticket_id: uuid.UUID, message_id: uuid.UUID, body: EditTicketMessage, admin: AdminUser, session: Session):
    """Staff may correct their own replies/notes; edits are stamped and audited."""
    from melorin.core.db import utcnow
    from melorin.modules.tickets import service as ticket_service
    from melorin.kernel.models.tickets import TicketMessage

    m = await session.get(TicketMessage, message_id)
    if not m or m.ticket_id != ticket_id:
        raise NotFound("پیام")
    if m.author_id != admin.id:
        raise AppError("FORBIDDEN", "فقط نویسندهٔ پیام می‌تواند آن را ویرایش کند.", 403)
    t = await session.get(Ticket, ticket_id)
    new = body.body.strip()
    if not new:
        raise AppError("EMPTY_MESSAGE", "متن پیام نمی‌تواند خالی باشد.", 422)
    if new != m.body:
        m.body, m.edited_at = new, utcnow()
        ticket_service.touch(t)
        audit.record(
            session,
            "ticket.message_edited",
            actor_id=admin.id,
            actor_type="admin",
            entity_type="ticket",
            entity_id=t.id,
            store_id=t.store_id,
            data={"message_id": str(m.id)},
        )
        await session.commit()
    return ticket_service.message_out(m).model_dump(mode="json")
