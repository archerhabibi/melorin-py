import uuid

from fastapi import APIRouter
from sqlalchemy import select

from melorin.core import audit, codes, events
from melorin.core.db import utcnow
from melorin.core.deps import CurrentUser, Session, StoreCtx
from melorin.core.errors import AppError, NotFound
from melorin.modules.tickets import service
from melorin.modules.tickets.models import Ticket, TicketMessage
from melorin.modules.tickets.schemas import AddMessage, CreateTicket, EditMessage, TicketMessageOut, TicketOut, UpdateTicket

router = APIRouter(tags=["tickets"])


def tout(t):
    return service.ticket_out(t)


async def _own_ticket(session, ticket_id: uuid.UUID, user) -> Ticket:
    t = await session.get(Ticket, ticket_id)
    if not t or (t.user_id != user.id and not user.is_super_admin):
        raise NotFound("تیکت")
    return t


@router.post("/stores/{store_id}/tickets", response_model=TicketOut, status_code=201)
async def create(body: CreateTicket, ctx: StoreCtx, session: Session):
    # number is NOT NULL: generate it before the INSERT is flushed.
    number = await codes.next_code(session, codes.TICKET_SEQ)
    t = Ticket(
        user_id=ctx.user.id,
        store_id=ctx.store.id,
        number=number,
        subject=body.subject.strip(),
        status="open",
        priority=body.priority,
        department=(body.department or "").strip() or None,
    )
    session.add(t)
    await session.flush()
    session.add(TicketMessage(ticket_id=t.id, author_id=ctx.user.id, is_staff=False, body=body.body))
    audit.record(session, "ticket.created", actor_id=ctx.user.id, entity_type="ticket", entity_id=t.id, store_id=ctx.store.id)
    await events.emit(session, events.TICKET_UPDATED, {"ticket_id": t.id, "store_id": ctx.store.id})
    await session.commit()
    return tout(t)


@router.get("/stores/{store_id}/tickets", response_model=list[TicketOut])
async def list_mine(ctx: StoreCtx, session: Session):
    return [
        tout(t)
        for t in (
            await session.scalars(
                select(Ticket).where(Ticket.user_id == ctx.user.id, Ticket.store_id == ctx.store.id).order_by(Ticket.updated_at.desc())
            )
        ).all()
    ]


@router.get("/tickets/{ticket_id}", response_model=TicketOut)
async def get_ticket(ticket_id: uuid.UUID, user: CurrentUser, session: Session):
    return tout(await _own_ticket(session, ticket_id, user))


@router.patch("/tickets/{ticket_id}", response_model=TicketOut)
async def update_ticket(ticket_id: uuid.UUID, body: UpdateTicket, user: CurrentUser, session: Session):
    """Customer-side edit: rename, change priority, close or re-open the ticket."""
    t = await _own_ticket(session, ticket_id, user)
    changes: dict = {}
    if body.subject is not None and body.subject.strip() != t.subject:
        if t.status == "closed" and body.status != "open":
            raise AppError("TICKET_CLOSED", "تیکت بسته شده است؛ ابتدا آن را دوباره باز کنید.", 409)
        changes["subject"] = (t.subject, body.subject.strip())
        t.subject = body.subject.strip()
    if body.priority is not None and body.priority != t.priority:
        changes["priority"] = (t.priority, body.priority)
        t.priority = body.priority
    if body.status is not None and body.status != t.status:
        if body.status == "open" and t.status == "closed":
            changes["status"] = (t.status, "open")
            t.status = "open"
        elif body.status == "closed":
            changes["status"] = (t.status, "closed")
            t.status = "closed"
    if changes:
        service.touch(t)
        audit.record(
            session,
            "ticket.updated",
            actor_id=user.id,
            entity_type="ticket",
            entity_id=t.id,
            store_id=t.store_id,
            data={k: {"from": a, "to": b} for k, (a, b) in changes.items()},
        )
        await events.emit(session, events.TICKET_UPDATED, {"ticket_id": t.id, "store_id": t.store_id})
        await session.commit()
    return tout(t)


@router.get("/tickets/{ticket_id}/messages", response_model=list[TicketMessageOut])
async def messages(ticket_id: uuid.UUID, user: CurrentUser, session: Session):
    t = await _own_ticket(session, ticket_id, user)
    rows = await service.list_messages(session, t.id, include_internal=bool(user.is_super_admin))
    return [service.message_out(x) for x in rows]


@router.post("/tickets/{ticket_id}/messages", response_model=TicketMessageOut)
async def add_message(ticket_id: uuid.UUID, body: AddMessage, user: CurrentUser, session: Session):
    t = await _own_ticket(session, ticket_id, user)
    m = TicketMessage(ticket_id=t.id, author_id=user.id, is_staff=user.is_super_admin, body=body.body)
    session.add(m)
    t.status = "answered" if user.is_super_admin else "open"
    service.touch(t)
    await session.flush()
    await events.emit(session, events.TICKET_UPDATED, {"ticket_id": t.id, "store_id": t.store_id})
    if user.is_super_admin and t.user_id != user.id:
        await service.notify_customer(session, t, body.body)
    await session.commit()
    return service.message_out(m)


@router.patch("/tickets/{ticket_id}/messages/{message_id}", response_model=TicketMessageOut)
async def edit_message(ticket_id: uuid.UUID, message_id: uuid.UUID, body: EditMessage, user: CurrentUser, session: Session):
    """Authors may edit their own messages; the edit is flagged with ``edited_at`` so nothing changes silently."""
    t = await _own_ticket(session, ticket_id, user)
    m = await session.get(TicketMessage, message_id)
    if not m or m.ticket_id != t.id or m.author_id != user.id or (m.is_internal and not user.is_super_admin):
        raise NotFound("پیام")
    if t.status == "closed" and not user.is_super_admin:
        raise AppError("TICKET_CLOSED", "تیکت بسته شده است؛ ابتدا آن را دوباره باز کنید.", 409)
    new = body.body.strip()
    if not new:
        raise AppError("EMPTY_MESSAGE", "متن پیام نمی‌تواند خالی باشد.", 422)
    if new != m.body:
        audit.record(
            session,
            "ticket.message_edited",
            actor_id=user.id,
            entity_type="ticket",
            entity_id=t.id,
            store_id=t.store_id,
            data={"message_id": str(m.id)},
        )
        m.body, m.edited_at = new, utcnow()
        service.touch(t)
        await session.commit()
    return service.message_out(m)
