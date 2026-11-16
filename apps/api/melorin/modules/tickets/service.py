"""Shared ticket helpers used by the customer router and the admin router."""

import uuid

from fastapi import UploadFile
from fastapi.responses import Response
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from melorin.core import audit, events
from melorin.core.config import get_settings
from melorin.core.db import utcnow
from melorin.core.errors import AppError, NotFound
from melorin.core.storage import get_storage, validate_upload
from melorin.kernel.models.system import FileObject
from melorin.kernel.models.tickets import Ticket, TicketMessage
from melorin.modules.tickets.schemas import AttachmentOut, TicketMessageOut, TicketOut

# Tickets take pictures only (screenshots, photos of a receipt or an error); PDFs stay a payment-receipt thing.
TICKET_IMAGE_TYPES = {"image/jpeg", "image/png", "image/webp"}
IMAGE_PLACEHOLDER = "📎 تصویر"

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
        attachment_id=m.attachment_id,
    )


async def save_image(session: AsyncSession, *, user_id: uuid.UUID, store_id: uuid.UUID | None, file: UploadFile) -> AttachmentOut:
    """Validate (type, size, magic bytes) and store one image for a ticket message. Not attached to anything yet."""
    content_type = (file.content_type or "").lower()
    if content_type not in TICKET_IMAGE_TYPES:
        raise AppError("UNSUPPORTED_FILE", "فقط تصویر (JPG، PNG یا WebP) مجاز است.", 415)
    limit = get_settings().max_upload_bytes
    buf = bytearray()
    while chunk := await file.read(1024 * 1024):
        buf.extend(chunk)
        if len(buf) > limit:
            raise AppError("FILE_TOO_LARGE", "حجم تصویر زیاد است.", 413)
    data = bytes(buf)
    if not data:
        raise AppError("EMPTY_FILE", "فایل خالی است.", 422)
    digest = validate_upload(data, content_type)
    key = await get_storage().put(data, content_type)
    fo = FileObject(
        owner_user_id=user_id,
        store_id=store_id,
        purpose="ticket",
        storage_key=key,
        content_type=content_type,
        size=len(data),
        sha256=digest,
    )
    session.add(fo)
    await session.flush()
    out = AttachmentOut(id=fo.id, content_type=fo.content_type, size=fo.size)
    await session.commit()
    return out


async def claim_attachment(session: AsyncSession, attachment_id: uuid.UUID | None, *, user_id: uuid.UUID) -> uuid.UUID | None:
    """The uploader may attach his own unused ticket image to exactly one message."""
    if attachment_id is None:
        return None
    fo = await session.get(FileObject, attachment_id)
    if fo is None or fo.purpose != "ticket" or fo.owner_user_id != user_id:
        raise NotFound("تصویر")
    used = await session.scalar(select(func.count()).select_from(TicketMessage).where(TicketMessage.attachment_id == fo.id))
    if used:
        raise AppError("ATTACHMENT_USED", "این تصویر قبلاً به پیام دیگری پیوست شده است.", 409)
    return fo.id


async def attachment_response(session: AsyncSession, m: TicketMessage) -> Response:
    """Serve a message's image. Callers have already checked that the viewer may see this ticket and message."""
    fo = await session.get(FileObject, m.attachment_id) if m.attachment_id else None
    if fo is None:
        raise NotFound("تصویر")
    data = await get_storage().get(fo.storage_key)
    return Response(
        content=data,
        media_type=fo.content_type,
        headers={"Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff", "Content-Disposition": "inline"},
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
    preview = text.strip().replace("\n", " ") or IMAGE_PLACEHOLDER
    if len(preview) > 280:
        preview = preview[:277] + "…"
    await events.emit_user_notice(
        session,
        t.user_id,
        t.store_id,
        "ticket_reply",
        f"🎧 پاسخ جدید به تیکت #{t.number or str(t.id)[:6]}",
        f"{t.subject}\n\n{preview}",
        payload_dedup_key=f"ticket_reply:{t.id}:{uuid.uuid4().hex[:8]}",
    )


def touch(t: Ticket) -> None:
    t.updated_at = utcnow()


# ----------------------------------------------------------------------------------------------------------- staff-side lifecycle
# The admin router only authenticates, parses and serialises. Every state change below is owned here, so the customer-visible /
# internal-note rule, the audit trail and the TICKET_UPDATED event exist in exactly one place.


async def get_ticket(session: AsyncSession, ticket_id: uuid.UUID) -> Ticket:
    t = await session.get(Ticket, ticket_id)
    if not t:
        raise NotFound("تیکت")
    return t


async def staff_update(session: AsyncSession, t: Ticket, *, actor_id: uuid.UUID, raw: dict) -> bool:
    """Apply a staff edit (status/priority/subject/department ...). Returns True when something changed. Commits."""
    changes = {k: v for k, v in raw.items() if v is not None or k == "department"}
    if "subject" in changes:
        changes["subject"] = changes["subject"].strip()
    if "department" in changes:
        changes["department"] = (changes["department"] or "").strip() or None
    before = {k: getattr(t, k) for k in changes}
    changes = {k: v for k, v in changes.items() if v != before[k]}
    if not changes:
        return False
    for k, v in changes.items():
        setattr(t, k, v)
    touch(t)
    audit.record(
        session,
        "ticket.admin_updated",
        actor_id=actor_id,
        actor_type="admin",
        entity_type="ticket",
        entity_id=t.id,
        store_id=t.store_id,
        data={"before": {k: before[k] for k in changes}, "after": changes},
    )
    await events.emit(session, events.TICKET_UPDATED, {"ticket_id": t.id, "store_id": t.store_id})
    await session.commit()
    return True


async def staff_reply(
    session: AsyncSession, t: Ticket, *, actor_id: uuid.UUID, body: str, internal: bool, status: str | None, attachment_id: uuid.UUID | None
) -> TicketMessage:
    """Staff reply or internal note. Replies notify the customer; internal notes never leave the admin panel. Commits."""
    text = body.strip()
    if not text and not attachment_id:
        raise AppError("EMPTY_MESSAGE", "متن یا تصویر پیوست لازم است.", 422)
    claimed = await claim_attachment(session, attachment_id, user_id=actor_id)
    m = TicketMessage(ticket_id=t.id, author_id=actor_id, is_staff=True, is_internal=internal, body=text, attachment_id=claimed)
    session.add(m)
    if not internal:
        t.status = status or "answered"
    elif status:
        t.status = status
    touch(t)
    await session.flush()
    audit.record(
        session,
        "ticket.note_added" if internal else "ticket.replied",
        actor_id=actor_id,
        actor_type="admin",
        entity_type="ticket",
        entity_id=t.id,
        store_id=t.store_id,
    )
    await events.emit(session, events.TICKET_UPDATED, {"ticket_id": t.id, "store_id": t.store_id, "message_id": m.id})
    if not internal and t.user_id != actor_id:
        await notify_customer(session, t, body)
    await session.commit()
    return m


async def staff_edit_message(session: AsyncSession, t: Ticket, m: TicketMessage, *, actor_id: uuid.UUID, body: str) -> TicketMessage:
    """Staff may correct their own replies/notes; edits are stamped and audited. Commits."""
    if m.author_id != actor_id:
        raise AppError("FORBIDDEN", "فقط نویسندهٔ پیام می‌تواند آن را ویرایش کند.", 403)
    new = body.strip()
    if not new:
        raise AppError("EMPTY_MESSAGE", "متن پیام نمی‌تواند خالی باشد.", 422)
    if new != m.body:
        m.body, m.edited_at = new, utcnow()
        touch(t)
        audit.record(
            session,
            "ticket.message_edited",
            actor_id=actor_id,
            actor_type="admin",
            entity_type="ticket",
            entity_id=t.id,
            store_id=t.store_id,
            data={"message_id": str(m.id)},
        )
        await session.commit()
    return m
