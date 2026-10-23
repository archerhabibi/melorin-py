"""Telegram Event Center (SRS §17): validation, routing/isolation, fan-out idempotency, delivery outcomes, worker tap."""

import uuid

import pytest
from sqlalchemy import select

from _db import make_store, make_user, open_session
from melorin.channels.telegram.bot_api import TelegramApiError
from melorin.core import events
from melorin.core.crypto import encrypt
from melorin.core.errors import AppError
from melorin.kernel.models.notifications import TelegramEventDestination
from melorin.kernel.models.system import OutboxEvent
from melorin.kernel.models.tickets import Ticket, TicketMessage
from melorin.modules.eventcenter import rules, service

GROUP = "-1001234567890"


@pytest.fixture(autouse=True)
def fake_tokens(monkeypatch):
    monkeypatch.setattr(service, "_store_token", lambda store: "tok-r" if store is not None and store.kind == "reseller" else "tok-main")


@pytest.fixture
def sent(monkeypatch):
    calls = []

    async def fake_send(token, dest, topic, text):
        calls.append({"token": token, "chat": dest.chat_id, "topic": topic, "thread": (dest.topics or {}).get(topic), "text": text})

    monkeypatch.setattr(service, "_send", fake_send)
    return calls


async def _world(s):
    admin = await make_user(s, super_admin=True)
    main = await make_store(s, kind="main")
    owner = await make_user(s)
    reseller = await make_store(s, kind="reseller", owner=owner)
    reseller.bot_token_enc = encrypt("123:abc")
    s.add(
        TelegramEventDestination(store_id=None, chat_id="-1001111111111", topics={"debt": 5, "errors": 6, "payments": 7}, is_enabled=True)
    )
    s.add(TelegramEventDestination(store_id=reseller.id, chat_id="-1002222222222", topics={"payments": 11, "orders": 12}, is_enabled=True))
    await s.commit()
    return admin, main, reseller


def test_chat_id_and_topics_validation():
    assert service.parse_chat_id("-1001234567890") == GROUP
    assert service.parse_chat_id("-۱۰۰۱۲۳۴۵۶۷۸۹۰") == GROUP  # Persian digits accepted
    for bad in ("@mygroup", "12345", "-12345", "", None, "-100abc"):
        with pytest.raises(AppError):
            service.parse_chat_id(bad)
    assert service.parse_topics({"payments": "12", "orders": "", "debt": None}) == {"payments": 12}
    assert service.parse_topics(None) == {}
    for bad in ({"nope": 1}, {"payments": "x"}, {"payments": 0}, {"payments": -3}, ["a"]):
        with pytest.raises(AppError):
            service.parse_topics(bad)


async def test_save_creates_then_replaces_one_destination_and_resets_health():
    async with open_session() as s:
        admin = await make_user(s, super_admin=True)
        await make_store(s, kind="main")
        await s.commit()
        d = await service.save(s, store=None, actor_id=admin.id, chat_id=GROUP, topics={"payments": 3}, is_enabled=True, note="x")
        d.last_error = "403 Forbidden"
        await s.commit()
        d2 = await service.save(s, store=None, actor_id=admin.id, chat_id="-1009999999999", topics={}, is_enabled=False, note=None)
        await s.commit()
        assert d2.id == d.id and d2.last_error is None and d2.is_enabled is False
        assert len((await s.scalars(select(TelegramEventDestination))).all()) == 1


async def test_reseller_cannot_save_without_own_bot():
    async with open_session() as s:
        owner = await make_user(s)
        store = await make_store(s, kind="reseller", owner=owner)
        await s.commit()
        with pytest.raises(AppError) as e:
            await service.save(s, store=store, actor_id=owner.id, chat_id=GROUP, topics={}, is_enabled=True, note=None)
        assert e.value.code == "EVENT_CENTER_NO_BOT"


async def test_reseller_event_goes_only_to_his_group_and_admin_copy_only_for_debt_and_errors():
    async with open_session() as s:
        _, _, reseller = await _world(s)
        assert await service.publish(s, store_id=reseller.id, topic="payments", text="p", source_key="k1") == 1
        assert await service.publish(s, store_id=reseller.id, topic="debt", text="d", source_key="k2") == 2
        assert await service.publish(s, store_id=reseller.id, topic="errors", text="e", source_key="k3") == 2
        await s.commit()
        rows = (await s.scalars(select(OutboxEvent).where(OutboxEvent.topic == events.EVENT_CENTER_DELIVER))).all()
        admin_dest = await service.get_destination(s, None)
        admin_rows = [r for r in rows if r.payload["destination_id"] == str(admin_dest.id)]
        assert sorted(r.payload["topic"] for r in admin_rows) == ["debt", "errors"]
        assert all(r.payload["text"].startswith(f"[{reseller.name}] ") for r in admin_rows)


async def test_main_store_event_goes_to_admin_and_disabled_or_missing_destination_is_skipped():
    async with open_session() as s:
        _, main, reseller = await _world(s)
        assert await service.publish(s, store_id=main.id, topic="payments", text="m", source_key="a") == 1
        (await service.get_destination(s, reseller.id)).is_enabled = False
        assert await service.publish(s, store_id=reseller.id, topic="payments", text="x", source_key="b") == 0
        with pytest.raises(ValueError):
            await service.publish(s, store_id=None, topic="bogus", text="x", source_key="c")


async def test_publish_is_idempotent_per_source_event_and_destination():
    async with open_session() as s:
        _, _, reseller = await _world(s)
        for _ in range(3):
            await service.publish(s, store_id=reseller.id, topic="payments", text="p", source_key="same")
            await s.flush()
        await s.commit()
        n = len((await s.scalars(select(OutboxEvent).where(OutboxEvent.topic == events.EVENT_CENTER_DELIVER))).all())
        assert n == 1


async def test_deliver_uses_the_right_bot_thread_and_records_success(sent):
    async with open_session() as s:
        _, _, reseller = await _world(s)
        dest = await service.get_destination(s, reseller.id)
        dest.last_error = "old"
        await service.deliver(s, {"destination_id": dest.id, "topic": "orders", "text": "hi"})
        await s.commit()
        assert sent == [{"token": "tok-r", "chat": "-1002222222222", "topic": "orders", "thread": 12, "text": "hi"}]
        assert dest.last_error is None and dest.last_sent_at is not None


async def test_permanent_error_is_recorded_not_raised_transient_is_raised(monkeypatch):
    async def forbidden(*a, **k):
        raise TelegramApiError(403, "Forbidden: bot was kicked")

    async def flood(*a, **k):
        raise TelegramApiError(429, "Too Many Requests", 3)

    async with open_session() as s:
        _, _, reseller = await _world(s)
        dest = await service.get_destination(s, reseller.id)
        payload = {"destination_id": dest.id, "topic": "orders", "text": "x"}
        monkeypatch.setattr(service, "_send", forbidden)
        await service.deliver(s, payload)  # no exception: retrying cannot help
        assert dest.last_error.startswith("403")
        monkeypatch.setattr(service, "_send", flood)
        with pytest.raises(TelegramApiError):
            await service.deliver(s, payload)
        assert dest.last_error.startswith("429")


async def test_deleted_topic_falls_back_to_general_once(monkeypatch):
    seen = []

    async def fake(self, chat, text, *, thread_id=None):
        seen.append(thread_id)
        if thread_id:
            raise TelegramApiError(400, "Bad Request: message thread not found")
        return {"ok": True}

    monkeypatch.setattr("melorin.channels.telegram.bot_api.TelegramChannel.send_to_topic", fake)
    async with open_session() as s:
        _, _, reseller = await _world(s)
        dest = await service.get_destination(s, reseller.id)
        await service._send("tok", dest, "orders", "hello")
        assert seen == [12, None]


async def test_send_test_reports_per_topic_outcome(monkeypatch):
    async def partly(token, dest, topic, text):
        if topic == "orders":
            raise TelegramApiError(400, "Bad Request: chat not found")

    monkeypatch.setattr(service, "_send", partly)
    async with open_session() as s:
        _, _, reseller = await _world(s)
        res = await service.send_test(s, store=reseller)
        assert {r["topic"]: r["ok"] for r in res} == {"payments": True, "orders": False}
        assert (await service.get_destination(s, reseller.id)).last_error.startswith("400")


# ----- rules + worker tap -----
async def test_manual_event_center_event_is_published_through_the_tap():
    async with open_session() as s:
        _, _, reseller = await _world(s)
        await events.emit(s, events.EVENT_CENTER, {"store_id": reseller.id, "topic": "payments", "text": "🧾 رسید"})
        await s.commit()
        e = await s.scalar(select(OutboxEvent).where(OutboxEvent.topic == events.EVENT_CENTER))
        assert await rules.tap(s, e) == 1
        await s.commit()
        d = await s.scalar(select(OutboxEvent).where(OutboxEvent.topic == events.EVENT_CENTER_DELIVER))
        assert d.payload["topic"] == "payments" and d.payload["text"] == "🧾 رسید"


async def test_debt_rule_texts_and_unknown_state_is_silent():
    async with open_session() as s:
        _, _, reseller = await _world(s)
        reached = await rules._debt(s, None, {"store_id": reseller.id, "state": "reached"})
        assert reached[1] == "debt" and "سقف" in reached[2]
        near = await rules._debt(s, None, {"store_id": reseller.id, "state": "near", "balance": -80, "limit": 100})
        assert near[1] == "debt" and "-80" in near[2]
        assert await rules._debt(s, None, {"store_id": reseller.id, "state": "ok"}) is None


async def test_tap_never_raises_and_ignores_unrelated_topics():
    async with open_session() as s:
        await _world(s)
        junk = OutboxEvent(topic=events.ORDER_PAID, payload={"order_id": str(uuid.uuid4())})
        other = OutboxEvent(topic=events.VPN_REVOKE, payload={})
        assert await rules.tap(s, junk) == 0 and await rules.tap(s, other) == 0


async def test_repeated_outbox_failure_is_reported_once_to_admin_errors_topic():
    async with open_session() as s:
        await _world(s)
        e = OutboxEvent(topic=events.ORDER_PAID, payload={}, attempts=rules.OUTBOX_FAILURE_THRESHOLD, last_error="boom")
        s.add(e)
        await s.flush()
        await rules.report_outbox_failure(s, e)
        await rules.report_outbox_failure(s, e)
        await s.commit()
        rows = (await s.scalars(select(OutboxEvent).where(OutboxEvent.topic == events.EVENT_CENTER_DELIVER))).all()
        assert len(rows) == 1 and rows[0].payload["topic"] == "errors"
        e.attempts = 2
        await rules.report_outbox_failure(s, e)  # below the threshold: silent


async def _ticket(s, reseller, customer, number="100001"):
    t = Ticket(user_id=customer.id, store_id=reseller.id, number=number, subject="مشکل اتصال", status="open")
    s.add(t)
    await s.flush()
    return t


async def _msg(s, ticket, author, *, staff=False, internal=False):
    m = TicketMessage(ticket_id=ticket.id, author_id=author.id, is_staff=staff, is_internal=internal, body="متن")
    s.add(m)
    await s.flush()
    return m


async def test_ticket_rule_announces_only_the_customers_own_message():
    async with open_session() as s:
        admin, _, reseller = await _world(s)
        customer = await make_user(s)
        t = await _ticket(s, reseller, customer)
        first = await _msg(s, t, customer)
        hit = await rules._ticket(s, None, {"ticket_id": t.id, "message_id": first.id})
        assert hit[0] == reseller.id and hit[1] == "tickets" and "تیکت جدید" in hit[2] and t.number in hit[2]
        reply = await _msg(s, t, customer)
        hit = await rules._ticket(s, None, {"ticket_id": t.id, "message_id": reply.id})
        assert "پاسخ جدید مشتری" in hit[2]
        staff = await _msg(s, t, admin, staff=True)
        note = await _msg(s, t, admin, staff=True, internal=True)
        assert await rules._ticket(s, None, {"message_id": staff.id}) is None
        assert await rules._ticket(s, None, {"message_id": note.id}) is None


async def test_ticket_status_change_does_not_repeat_the_last_customer_reply():
    """Regression: a status/priority change (no message_id) used to re-announce the last customer message every time."""
    async with open_session() as s:
        _, _, reseller = await _world(s)
        customer = await make_user(s)
        t = await _ticket(s, reseller, customer)
        await _msg(s, t, customer)
        await s.commit()
        for payload in ({"ticket_id": str(t.id), "store_id": str(reseller.id)}, {"ticket_id": str(t.id), "message_id": str(uuid.uuid4())}):
            e = OutboxEvent(topic=events.TICKET_UPDATED, payload=payload)
            s.add(e)
            await s.flush()
            assert await rules.tap(s, e) == 0
