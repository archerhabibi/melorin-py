"""Ticket desk: priority, internal notes, message editing, staff-reply notifications (migration 0015)."""

import types
import uuid
from pathlib import Path

import pytest
from _chan import admin_auth, auth_for
from _source import read_source
from sqlalchemy import select

import melorin.models  # noqa: F401  (registers every table so FKs resolve)
from melorin.core import db, events
from melorin.core.errors import AppError
from melorin.modules.admin import router as admin
from melorin.modules.identity.models import Identity, User
from melorin.modules.stores.models import Store
from melorin.modules.system.models import AuditEvent, OutboxEvent
from melorin.modules.tickets import router as customer
from melorin.modules.tickets.models import Ticket, TicketMessage
from melorin.modules.tickets.schemas import AddMessage, AdminAddMessage, AdminUpdateTicket, EditMessage, UpdateTicket

ROOT = Path(__file__).parents[1]
TABLES = [
    User.__table__,
    Identity.__table__,
    Store.__table__,
    Ticket.__table__,
    TicketMessage.__table__,
    OutboxEvent.__table__,
    AuditEvent.__table__,
]


@pytest.fixture
async def world(tmp_path):
    db.configure(f"sqlite+aiosqlite:///{tmp_path}/tickets.db")
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
        await s.flush()
        s.add(TicketMessage(ticket_id=t.id, author_id=cust.id, is_staff=False, body="کمک می‌خواهم"))
        await s.commit()
        yield types.SimpleNamespace(
            s=s, cust=cust, staff=staff, other=other, t=t, cust_auth=auth_for(cust, store), staff_auth=admin_auth(staff), other_auth=auth_for(other, store)
        )
    await db.engine().dispose()


async def test_admin_list_has_customer_priority_and_filters(world):
    rows = await admin.tickets(world.staff, world.s, status=None, priority=None, store_id=None, q=None)
    assert rows[0]["customer"]["email"] == "c@example.com" and rows[0]["priority"] == "normal" and rows[0]["message_count"] == 1
    assert rows[0]["last_message"] == "کمک می‌خواهم" and rows[0]["last_from_staff"] is False
    assert await admin.tickets(world.staff, world.s, status="closed", priority=None, store_id=None, q=None) == []
    assert len(await admin.tickets(world.staff, world.s, status=None, priority=None, store_id=None, q="ab23")) == 1


async def test_staff_reply_notifies_customer_and_internal_note_does_not(world):
    await admin.ticket_reply(world.t.id, AdminAddMessage(body="یادداشت داخلی", internal=True), world.staff, world.s)
    assert (await world.s.scalars(select(OutboxEvent).where(OutboxEvent.topic == events.NOTIFY))).first() is None
    await world.s.refresh(world.t)
    assert world.t.status == "open"

    out = await admin.ticket_reply(world.t.id, AdminAddMessage(body="پاسخ شما"), world.staff, world.s)
    assert out["ticket_status"] == "answered" and out["is_internal"] is False
    ev = (await world.s.scalars(select(OutboxEvent).where(OutboxEvent.topic == events.NOTIFY))).one()
    assert ev.payload["kind"] == "ticket_reply" and ev.payload["user_id"] == str(world.cust.id)


async def test_customer_never_sees_internal_notes(world):
    await admin.ticket_reply(world.t.id, AdminAddMessage(body="فقط ادمین", internal=True), world.staff, world.s)
    await admin.ticket_reply(world.t.id, AdminAddMessage(body="برای مشتری"), world.staff, world.s)
    mine = await customer.messages(world.t.id, world.cust_auth, world.s)
    assert [m.body for m in mine] == ["کمک می‌خواهم", "برای مشتری"]
    detail = await admin.ticket_detail(world.t.id, world.staff, world.s)
    assert [m["is_internal"] for m in detail["messages"]] == [False, True, False]
    assert detail["messages"][1]["author_name"] == "پشتیبان"
    assert [m["mine"] for m in detail["messages"]] == [False, True, True]


async def test_admin_can_edit_subject_priority_status_and_it_is_audited(world):
    row = await admin.update_ticket(
        world.t.id, AdminUpdateTicket(subject="موضوع جدید", priority="urgent", status="closed", department="billing"), world.staff, world.s
    )
    assert (row["subject"], row["priority"], row["status"], row["department"]) == ("موضوع جدید", "urgent", "closed", "billing")
    log = (await world.s.scalars(select(AuditEvent).where(AuditEvent.action == "ticket.admin_updated"))).one()
    assert log.data["before"]["priority"] == "normal" and log.data["after"]["priority"] == "urgent"


async def test_message_edit_is_author_only_and_stamped(world):
    first = (await customer.messages(world.t.id, world.cust_auth, world.s))[0]
    edited = await customer.edit_message(world.t.id, first.id, EditMessage(body="متن اصلاح‌شده"), world.cust_auth, world.s)
    assert edited.body == "متن اصلاح‌شده" and edited.edited_at is not None
    with pytest.raises(AppError):  # someone else's ticket is a 404, not a leak
        await customer.edit_message(world.t.id, first.id, EditMessage(body="x"), world.other_auth, world.s)
    with pytest.raises(AppError):  # staff cannot rewrite the customer's words
        await admin.ticket_edit_message(world.t.id, first.id, EditMessage(body="x"), world.staff, world.s)
    reply = await admin.ticket_reply(world.t.id, AdminAddMessage(body="غلط"), world.staff, world.s)
    fixed = await admin.ticket_edit_message(world.t.id, uuid.UUID(reply["id"]), EditMessage(body="درست"), world.staff, world.s)
    assert fixed["body"] == "درست" and fixed["edited_at"]


async def test_admin_reply_and_edit_reject_whitespace_only_text(world):
    for body in ("   ", "\n\t "):
        with pytest.raises(AppError) as e:
            await admin.ticket_reply(world.t.id, AdminAddMessage(body=body), world.staff, world.s)
        assert e.value.status == 422
    reply = await admin.ticket_reply(world.t.id, AdminAddMessage(body="پاسخ"), world.staff, world.s)
    with pytest.raises(AppError) as e:
        await admin.ticket_edit_message(world.t.id, uuid.UUID(reply["id"]), EditMessage(body="   "), world.staff, world.s)
    assert e.value.status == 422
    msgs = await customer.messages(world.t.id, world.staff_auth, world.s)
    assert [m.body for m in msgs][-1] == "پاسخ" and len(msgs) == 2


async def test_customer_can_rename_close_and_reopen_but_not_closed_edit(world):
    out = await customer.update_ticket(world.t.id, UpdateTicket(subject="عنوان تازه", priority="high"), world.cust_auth, world.s)
    assert out.subject == "عنوان تازه" and out.priority == "high"
    out = await customer.update_ticket(world.t.id, UpdateTicket(status="closed"), world.cust_auth, world.s)
    assert out.status == "closed"
    first = (await customer.messages(world.t.id, world.cust_auth, world.s))[0]
    with pytest.raises(AppError):
        await customer.edit_message(world.t.id, first.id, EditMessage(body="بعد از بستن"), world.cust_auth, world.s)
    assert (await customer.update_ticket(world.t.id, UpdateTicket(status="open"), world.cust_auth, world.s)).status == "open"
    with pytest.raises(AppError):
        await customer.update_ticket(world.t.id, UpdateTicket(subject="x" * 5), world.other_auth, world.s)


async def test_customer_reply_reopens_and_staff_reply_via_legacy_endpoint_notifies(world):
    await admin.update_ticket(world.t.id, AdminUpdateTicket(status="answered"), world.staff, world.s)
    await customer.add_message(world.t.id, AddMessage(body="ممنون، یک سؤال دیگر"), world.cust_auth, world.s)
    await world.s.refresh(world.t)
    assert world.t.status == "open"
    await customer.add_message(world.t.id, AddMessage(body="جواب"), world.staff_auth, world.s)
    assert (await world.s.scalars(select(OutboxEvent).where(OutboxEvent.topic == events.NOTIFY))).first() is not None


def test_migration_0015_chains_from_0014_and_models_match():
    src = read_source(ROOT / "alembic" / "versions" / "0015_ticket_upgrade.py")
    assert 'revision = "0015_ticket_upgrade"' in src and 'down_revision = "0014_short_codes"' in src
    assert len("0015_ticket_upgrade") <= 32  # alembic_version.version_num is VARCHAR(32)
    for col in ("priority", "is_internal", "edited_at"):
        assert col in src
    assert Ticket.__table__.c.priority.nullable is False
    assert TicketMessage.__table__.c.is_internal.nullable is False
    assert TicketMessage.__table__.c.edited_at.nullable is True


# ---------------------------------------------------------------- Telegram bot (Core + Telegram mocked)
import asyncio  # noqa: E402
import importlib.util  # noqa: E402
import json  # noqa: E402

import httpx  # noqa: E402

APPS = Path(__file__).parents[2]


def _load(name, rel):
    spec = importlib.util.spec_from_file_location(name, APPS / rel)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


class _Core:
    def __init__(self):
        self.sent, self.calls = [], []
        self.msgs = [
            {"id": "m1", "is_staff": False, "body": "اینترنت وصل نمی‌شود", "edited_at": None},
            {"id": "m2", "is_staff": True, "body": "لطفاً آپدیت کنید", "edited_at": None},
        ]

    def handler(self, request: httpx.Request) -> httpx.Response:
        url, body = str(request.url), (request.content or b"")
        if "api.telegram.org" in url:
            if url.endswith(("/sendMessage", "/editMessageText")):
                self.sent.append(json.loads(body))
            return httpx.Response(200, json={"ok": True, "result": {}})
        p, m = request.url.path, request.method
        self.calls.append((m, p, json.loads(body) if body else None))
        if p == "/api/v1/stores/main":
            return httpx.Response(200, json={"id": "s1", "name": "Main"})
        if p == "/api/v1/auth/telegram/bot":
            return httpx.Response(200, json={"access_token": "A", "refresh_token": "R"})
        tk = {"id": "t1", "number": "AB23CD", "subject": "قطعی", "status": "answered", "priority": "high"}
        if p == "/api/v1/stores/s1/tickets" and m == "GET":
            return httpx.Response(200, json=[tk])
        if p == "/api/v1/stores/s1/tickets" and m == "POST":
            return httpx.Response(201, json={**tk, "subject": json.loads(body)["subject"], "status": "open"})
        if p == "/api/v1/tickets/t1" and m == "GET":
            return httpx.Response(200, json=tk)
        if p == "/api/v1/tickets/t1/messages" and m == "GET":
            return httpx.Response(200, json=self.msgs)
        if p.startswith("/api/v1/tickets/t1") and m == "PATCH":
            return httpx.Response(200, json={**tk, **(json.loads(body) if "messages" not in p else {})})
        if p == "/api/v1/tickets/t1/messages" and m == "POST":
            return httpx.Response(200, json={})
        return httpx.Response(404, json={})


@pytest.fixture
def bot(tmp_path, monkeypatch):
    for k, v in {
        "MELORIN_TELEGRAM_TOKEN": "tok",
        "MELORIN_CORE_URL": "http://core",
        "MELORIN_BOT_SERVICE_SECRET": "sek",
        "MELORIN_TELEGRAM_OFFSET_FILE": str(tmp_path / "o.json"),
    }.items():
        monkeypatch.setenv(k, v)
    mod = _load("tg_main_n01", "telegram-main/runner.py")
    r, core = mod.TelegramRunner(), _Core()
    r.client = httpx.AsyncClient(transport=httpx.MockTransport(core.handler))
    return r, core


def _msg(text, uid=1):
    return {"update_id": uid, "message": {"chat": {"id": 9}, "from": {"id": 7, "first_name": "A"}, "text": text}}


def _cb(data, uid=2):
    return {
        "update_id": uid,
        "callback_query": {"id": f"cb{uid}", "from": {"id": 7}, "data": data, "message": {"chat": {"id": 9}, "message_id": 5}},
    }


def test_bot_ticket_list_shows_number_status_and_new_button(bot):
    r, core = bot
    asyncio.run(r.handle(_msg("/tickets")))
    out = core.sent[-1]
    flat = [b for row in out["reply_markup"]["inline_keyboard"] for b in row]
    assert any("#AB23CD" in b["text"] and "🟢" in b["text"] and b["callback_data"] == "ticket:t1" for b in flat)
    assert any(b["callback_data"] == "tnew:1" for b in flat)


def test_bot_ticket_view_offers_reply_edit_rename_close(bot):
    r, core = bot
    asyncio.run(r.handle(_cb("ticket:t1")))
    out = core.sent[-1]
    assert "#AB23CD" in out["text"] and "لطفاً آپدیت کنید" in out["text"] and "مهم" in out["text"]
    data = {b["callback_data"] for row in out["reply_markup"]["inline_keyboard"] for b in row}
    assert {"reply:t1", "tedit:t1", "tsubj:t1", "tclose:t1"} <= data


def test_bot_guided_new_ticket_asks_subject_then_body_and_reports_number(bot):
    r, core = bot
    asyncio.run(r.handle(_cb("tnew:1", 3)))
    asyncio.run(r.handle(_msg("اتصال قطع است", 4)))
    assert r.state["9"] == {"new_ticket_subject": "اتصال قطع است"}
    asyncio.run(r.handle(_msg("از دیشب وصل نمی‌شود", 5)))
    posted = [c for c in core.calls if c[0] == "POST" and c[1].endswith("/tickets")][0][2]
    assert posted == {"subject": "اتصال قطع است", "body": "از دیشب وصل نمی‌شود"}
    assert "#AB23CD" in core.sent[-1]["text"] and not r.state.get("9")


def test_bot_edit_my_last_message_patches_only_my_message(bot):
    r, core = bot
    asyncio.run(r.handle(_cb("tedit:t1", 6)))
    assert r.state["9"] == {"edit_ticket": "t1", "edit_msg": "m1"}  # m2 is staff and must never be targeted
    asyncio.run(r.handle(_msg("اینترنت همچنان وصل نمی‌شود", 7)))
    assert ("PATCH", "/api/v1/tickets/t1/messages/m1", {"body": "اینترنت همچنان وصل نمی‌شود"}) in core.calls


def test_bot_rename_and_close_and_reopen(bot):
    r, core = bot
    asyncio.run(r.handle(_cb("tsubj:t1", 8)))
    asyncio.run(r.handle(_msg("موضوع تازه", 9)))
    asyncio.run(r.handle(_cb("tclose:t1", 10)))
    asyncio.run(r.handle(_cb("treopen:t1", 11)))
    patches = [c for c in core.calls if c[0] == "PATCH"]
    assert [c[2] for c in patches] == [{"subject": "موضوع تازه"}, {"status": "closed"}, {"status": "open"}]


# ---------------------------------------------------------------- web front-ends
def test_web_ticket_screens_use_the_new_edit_endpoints():
    admin_ui = (APPS / "admin-web" / "src" / "TicketsView.jsx").read_text()
    for needle in ("/api/v1/admin/tickets", "/messages/${m.id}", 'method: "PATCH"', "internal", "ویرایش‌شده"):
        assert needle in admin_ui
    assert "TicketsView" in (APPS / "admin-web" / "src" / "AdminExtra.jsx").read_text()
    store_ui = (APPS / "store-web" / "src" / "Dashboard.jsx").read_text()
    for needle in ("/api/v1/tickets/${t.id}/messages/${m.id}", "ویرایش موضوع", "بستن تیکت"):
        assert needle in store_ui
