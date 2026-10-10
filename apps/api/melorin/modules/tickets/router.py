import uuid

from fastapi import APIRouter
from sqlalchemy import select

from melorin.core import audit, events
from melorin.core.deps import CurrentUser, Session, StoreCtx
from melorin.core.errors import NotFound
from melorin.modules.tickets.models import Ticket, TicketMessage
from melorin.modules.tickets.schemas import AddMessage, CreateTicket, TicketMessageOut, TicketOut

router = APIRouter(tags=["tickets"])


def tout(t):
    return TicketOut(id=t.id, store_id=t.store_id, subject=t.subject, status=t.status, created_at=t.created_at, updated_at=t.updated_at)


@router.post("/stores/{store_id}/tickets", response_model=TicketOut, status_code=201)
async def create(body: CreateTicket, ctx: StoreCtx, session: Session):
    t = Ticket(user_id=ctx.user.id, store_id=ctx.store.id, subject=body.subject, status="open")
    session.add(t)
    await session.flush()
    session.add(TicketMessage(ticket_id=t.id, author_id=ctx.user.id, is_staff=False, body=body.body))
    audit.record(session, "ticket.created", actor_id=ctx.user.id, entity_type="ticket", entity_id=t.id, store_id=ctx.store.id)
    await events.emit(session, events.TICKET_UPDATED, {"ticket_id": t.id, "store_id": ctx.store.id})
    await session.commit()
    return tout(t)


@router.get("/stores/{store_id}/tickets", response_model=list[TicketOut])
async def list_mine(ctx: StoreCtx, session: Session):
    return [tout(t) for t in (await session.scalars(select(Ticket).where(Ticket.user_id == ctx.user.id, Ticket.store_id == ctx.store.id).order_by(Ticket.updated_at.desc()))).all()]


@router.get("/tickets/{ticket_id}/messages", response_model=list[TicketMessageOut])
async def messages(ticket_id: uuid.UUID, user: CurrentUser, session: Session):
    t = await session.get(Ticket, ticket_id)
    if not t or (t.user_id != user.id and not user.is_super_admin):
        raise NotFound("تیکت")
    rows = (await session.scalars(select(TicketMessage).where(TicketMessage.ticket_id == t.id).order_by(TicketMessage.created_at))).all()
    return [TicketMessageOut(id=x.id, author_id=x.author_id, is_staff=x.is_staff, body=x.body, created_at=x.created_at) for x in rows]


@router.post("/tickets/{ticket_id}/messages", response_model=TicketMessageOut)
async def add_message(ticket_id: uuid.UUID, body: AddMessage, user: CurrentUser, session: Session):
    t = await session.get(Ticket, ticket_id)
    if not t or (t.user_id != user.id and not user.is_super_admin):
        raise NotFound("تیکت")
    m = TicketMessage(ticket_id=t.id, author_id=user.id, is_staff=user.is_super_admin, body=body.body)
    session.add(m)
    t.status = "answered" if user.is_super_admin else "open"
    await session.flush()
    await events.emit(session, events.TICKET_UPDATED, {"ticket_id": t.id, "store_id": t.store_id})
    await session.commit()
    return TicketMessageOut(id=m.id, author_id=m.author_id, is_staff=m.is_staff, body=m.body, created_at=m.created_at)
