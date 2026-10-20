import uuid

from fastapi import APIRouter
from sqlalchemy import select

from melorin.core import audit, codes, events
from melorin.core.db import utcnow
from melorin.core import channel
from melorin.core.deps import AuthSession, CurrentAuth, Session, StoreCtx
from melorin.core.errors import AppError, NotFound
from melorin.modules.tickets import service
from melorin.modules.tickets.models import Ticket, TicketMessage
from melorin.modules.tickets.schemas import AddMessage, CreateTicket, EditMessage, TicketMessageOut, TicketOut, UpdateTicket

router = APIRouter(tags=["tickets"])


def tout(t):
    return service.ticket_out(t)


async def _own_ticket(session, ticket_id: uuid.UUID, auth: AuthSession) -> Ticket:
    """A customer reaches only HIS tickets of the store his session is bound to (anything else answers like "missing");
    staff (admin-panel session) reach every ticket."""
    t = await session.get(Ticket, ticket_id)
    if not t:
        raise NotFound("تیکت")
    if not auth.is_admin_session and (t.user_id != auth.user.id or t.store_id != auth.claims.store_id):
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
async def get_ticket(ticket_id: uuid.UUID, auth: CurrentAuth, session: Session):
    return tout(await _own_ticket(session, ticket_id, auth))


@router.patch("/tickets/{ticket_id}", response_model=TicketOut)
async def update_ticket(ticket_id: uuid.UUID, body: UpdateTicket, auth: CurrentAuth, session: Session):
    user = auth.user
    """Customer-side edit: rename, change priority, close or re-open the ticket."""
    t = await _own_ticket(session, ticket_id, auth)
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
async def messages(ticket_id: uuid.UUID, auth: CurrentAuth, session: Session):
    t = await _own_ticket(session, ticket_id, auth)
    rows = await service.list_messages(session, t.id, include_internal=auth.is_admin_session)
    return [service.message_out(x) for x in rows]


@router.post("/tickets/{ticket_id}/messages", response_model=TicketMessageOut)
async def add_message(ticket_id: uuid.UUID, body: AddMessage, auth: CurrentAuth, session: Session):
    user = auth.user
    t = await _own_ticket(session, ticket_id, auth)
    m = TicketMessage(ticket_id=t.id, author_id=user.id, is_staff=auth.is_admin_session, body=body.body)
    session.add(m)
    t.status = "answered" if auth.is_admin_session else "open"
    service.touch(t)
    await session.flush()
    await events.emit(session, events.TICKET_UPDATED, {"ticket_id": t.id, "store_id": t.store_id})
    if auth.is_admin_session and t.user_id != user.id:
        await service.notify_customer(session, t, body.body)
    await session.commit()
    return service.message_out(m)


@router.patch("/tickets/{ticket_id}/messages/{message_id}", response_model=TicketMessageOut)
async def edit_message(ticket_id: uuid.UUID, message_id: uuid.UUID, body: EditMessage, auth: CurrentAuth, session: Session):
    user = auth.user
    """Authors may edit their own messages; the edit is flagged with ``edited_at`` so nothing changes silently."""
    t = await _own_ticket(session, ticket_id, auth)
    m = await session.get(TicketMessage, message_id)
    if not m or m.ticket_id != t.id or m.author_id != user.id or (m.is_internal and not auth.is_admin_session):
        raise NotFound("پیام")
    if t.status == "closed" and not auth.is_admin_session:
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
