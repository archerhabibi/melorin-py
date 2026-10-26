"""Tickets accept pictures: upload, attach to a message, authorised download, validation."""

import io
import types
import uuid

import pytest
from _chan import admin_auth, auth_for
from sqlalchemy import select
from starlette.datastructures import Headers, UploadFile

import melorin.models  # noqa: F401  (registers every table so FKs resolve)
from melorin.core import codes, db, storage
from melorin.core.errors import AppError
from melorin.kernel.models.identity import Identity, User
from melorin.kernel.models.stores import Store
from melorin.kernel.models.system import AuditEvent, FileObject, OutboxEvent
from melorin.kernel.models.tickets import Ticket, TicketMessage
from melorin.modules.admin import router as admin
from melorin.modules.tickets import router as customer
from melorin.modules.tickets.schemas import AddMessage, AdminAddMessage, CreateTicket

PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 64
JPEG = b"\xff\xd8\xff" + b"0" * 64
TABLES = [
    User.__table__,
    Identity.__table__,
    Store.__table__,
    Ticket.__table__,
    TicketMessage.__table__,
    FileObject.__table__,
    OutboxEvent.__table__,
    AuditEvent.__table__,
]


def upload(data: bytes, content_type: str, name: str = "shot.png") -> UploadFile:
    return UploadFile(io.BytesIO(data), filename=name, headers=Headers({"content-type": content_type}))


@pytest.fixture
async def world(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "_storage", storage.LocalStorage(str(tmp_path / "files")))
    db.configure(f"sqlite+aiosqlite:///{tmp_path}/att.db")
    async with db.engine().begin() as conn:
        await conn.run_sync(lambda c: db.Base.metadata.create_all(c, tables=TABLES))
    async with db.session_factory()() as s:
        cust = User(display_name="مشتری", email="c@example.com")
        staff = User(display_name="پشتیبان", email="a@example.com", is_super_admin=True)
        other = User(display_name="دیگری", email="o@example.com")
        store = Store(kind="main", name="Main", slug="main")
        s.add_all([cust, staff, other, store])
        await s.flush()
        t = Ticket(user_id=cust.id, store_id=store.id, number="AB23CD", subject="سلام", status="open", priority="normal")
        s.add(t)
        await s.commit()
        yield types.SimpleNamespace(
            s=s,
            cust=cust,
            staff=staff,
            t=t,
            store=store,
            ctx=types.SimpleNamespace(user=cust, store=store),
            other_ctx=types.SimpleNamespace(user=other, store=store),
            cust_auth=auth_for(cust, store),
            other_auth=auth_for(other, store),
            staff_auth=admin_auth(staff),
        )
    await db.engine().dispose()


async def test_image_only_message_is_stored_and_downloadable(world):
    att = await customer.upload_attachment(world.ctx, world.s, upload(PNG, "image/png"))
    assert att.content_type == "image/png" and att.size == len(PNG)
    msg = await customer.add_message(world.t.id, AddMessage(attachment_id=att.id), world.cust_auth, world.s)
    assert msg.body == "" and msg.attachment_id == att.id
    resp = await customer.message_attachment(world.t.id, msg.id, world.cust_auth, world.s)
    assert resp.body == PNG and resp.media_type == "image/png"
    assert resp.headers["x-content-type-options"] == "nosniff" and resp.headers["cache-control"] == "private, no-store"
    listed = await customer.messages(world.t.id, world.cust_auth, world.s)
    assert listed[-1].attachment_id == att.id


async def test_new_ticket_can_start_with_a_picture_and_text(world, monkeypatch):
    async def next_code(session, sequence):  # the real one uses a PostgreSQL sequence
        return "ZX98YW"

    monkeypatch.setattr(codes, "next_code", next_code)
    att = await customer.upload_attachment(world.ctx, world.s, upload(JPEG, "image/jpeg", "a.jpg"))
    t = await customer.create(CreateTicket(subject="مشکل اتصال", body="عکس خطا", attachment_id=att.id), world.ctx, world.s)
    first = (await customer.messages(t.id, world.cust_auth, world.s))[0]
    assert first.body == "عکس خطا" and first.attachment_id == att.id


async def test_non_images_wrong_signature_and_oversize_are_refused(world, monkeypatch):
    for data, ctype in ((b"%PDF-1.4 x", "application/pdf"), (b"hello", "text/plain"), (b"<svg/>", "image/svg+xml")):
        with pytest.raises(AppError) as e:
            await customer.upload_attachment(world.ctx, world.s, upload(data, ctype))
        assert e.value.status == 415
    with pytest.raises(AppError) as e:  # says image/png but is not one
        await customer.upload_attachment(world.ctx, world.s, upload(b"not a png at all", "image/png"))
    assert e.value.status == 415
    with pytest.raises(AppError) as e:
        await customer.upload_attachment(world.ctx, world.s, upload(b"", "image/png"))
    assert e.value.status == 422
    monkeypatch.setattr("melorin.modules.tickets.service.get_settings", lambda: types.SimpleNamespace(max_upload_bytes=16))
    with pytest.raises(AppError) as e:
        await customer.upload_attachment(world.ctx, world.s, upload(PNG, "image/png"))
    assert e.value.status == 413
    assert (await world.s.scalars(select(FileObject))).first() is None


async def test_empty_message_needs_text_or_picture(world):
    with pytest.raises(AppError) as e:
        await customer.add_message(world.t.id, AddMessage(body="   "), world.cust_auth, world.s)
    assert e.value.status == 422
    with pytest.raises(ValueError):
        AddMessage()


async def test_picture_cannot_be_reused_or_borrowed(world):
    att = await customer.upload_attachment(world.ctx, world.s, upload(PNG, "image/png"))
    await customer.add_message(world.t.id, AddMessage(attachment_id=att.id), world.cust_auth, world.s)
    with pytest.raises(AppError) as e:  # already attached to a message
        await customer.add_message(world.t.id, AddMessage(body="دوباره", attachment_id=att.id), world.cust_auth, world.s)
    assert e.value.status == 409
    other = await customer.upload_attachment(world.other_ctx, world.s, upload(PNG, "image/png"))
    with pytest.raises(AppError) as e:  # someone else's upload is "missing"
        await customer.add_message(world.t.id, AddMessage(body="x", attachment_id=other.id), world.cust_auth, world.s)
    assert e.value.status == 404


async def test_only_ticket_owner_and_staff_can_download(world):
    att = await customer.upload_attachment(world.ctx, world.s, upload(PNG, "image/png"))
    msg = await customer.add_message(world.t.id, AddMessage(attachment_id=att.id), world.cust_auth, world.s)
    with pytest.raises(AppError):
        await customer.message_attachment(world.t.id, msg.id, world.other_auth, world.s)
    resp = await admin.ticket_message_attachment(world.t.id, msg.id, world.staff, world.s)
    assert resp.body == PNG


async def test_staff_reply_with_picture_notifies_customer_and_internal_note_stays_hidden(world):
    att = await admin.ticket_upload_attachment(world.staff, world.s, upload(PNG, "image/png"))
    out = await admin.ticket_reply(world.t.id, AdminAddMessage(attachment_id=att.id), world.staff, world.s)
    assert out["body"] == "" and out["attachment_id"] == str(att.id)
    rows = await admin.tickets(world.staff, world.s, status=None, priority=None, store_id=None, q=None)
    assert rows[0]["last_message"] == "📎 تصویر"
    shown = await customer.message_attachment(world.t.id, uuid.UUID(out["id"]), world.cust_auth, world.s)
    assert shown.body == PNG
    note_att = await admin.ticket_upload_attachment(world.staff, world.s, upload(JPEG, "image/jpeg"))
    note = await admin.ticket_reply(
        world.t.id, AdminAddMessage(body="داخلی", internal=True, attachment_id=note_att.id), world.staff, world.s
    )
    with pytest.raises(AppError):  # a staff-only note's picture is never served to the customer
        await customer.message_attachment(world.t.id, uuid.UUID(note["id"]), world.cust_auth, world.s)
    assert all(m.attachment_id != note_att.id for m in await customer.messages(world.t.id, world.cust_auth, world.s))
