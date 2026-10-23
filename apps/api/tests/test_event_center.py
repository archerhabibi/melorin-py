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
from melorin.kernel.models.vpn import Panel
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


async def test_panel_health_notice_only_on_state_change():
    async with open_session() as s:
        await _world(s)
        panel = Panel(name="Panel-A", kind="mock", base_url="https://p.invalid")
        s.add(panel)
        await s.flush()

        async def queued():
            rows = (await s.scalars(select(OutboxEvent).where(OutboxEvent.topic == events.EVENT_CENTER))).all()
            return [r.payload["text"] for r in rows]

        panel.health_status, panel.last_health_error = "unhealthy", "timeout"
        await rules.notify_panel_health(s, panel, "healthy")
        await rules.notify_panel_health(s, panel, "unhealthy")  # still unhealthy: silent
        panel.health_status, panel.last_health_error = "healthy", None
        await rules.notify_panel_health(s, panel, "unknown")  # first check ok: silent
        await rules.notify_panel_health(s, panel, "unhealthy")  # recovered
        texts = await queued()
        assert len(texts) == 2 and "Panel-A" in texts[0] and "timeout" in texts[0] and "دوباره سالم" in texts[1]
        e = (await s.scalars(select(OutboxEvent).where(OutboxEvent.topic == events.EVENT_CENTER))).first()
        assert e.payload["topic"] == "errors" and e.payload["store_id"] is None


async def test_customer_text_cannot_ping_people_in_the_group(monkeypatch):
    seen = []

    async def fake_send_to_topic(self, chat_id, text, *, thread_id=None):
        seen.append(text)
        return {"ok": True}

    monkeypatch.setattr(service.TelegramChannel, "send_to_topic", fake_send_to_topic)
    async with open_session() as s:
        _, _, reseller = await _world(s)
        dest = await service.get_destination(s, reseller.id)
        await service._send("tok-r", dest, "tickets", "🎫 تیکت جدید\nموضوع: سلام @admin_boss و @everyone")
    assert len(seen) == 1
    assert "@admin_boss" not in seen[0] and "@everyone" not in seen[0]
    assert seen[0].count("@\u200b") == 2


def test_outbox_backoff_never_retries_before_telegram_retry_after():
    from melorin.worker.runner import OUTBOX_MAX_RETRY_AFTER, _retry_delay

    assert _retry_delay(1, RuntimeError("x")) == 2  # plain exponential backoff is unchanged
    assert _retry_delay(20, RuntimeError("x")) == 256  # same cap as before: 2**8
    flood = TelegramApiError(429, "Too Many Requests", 90)
    assert _retry_delay(1, flood) == 91  # waits out the flood-wait, not the short backoff
    assert _retry_delay(8, TelegramApiError(429, "Too Many Requests", 5)) == 256  # a longer backoff still wins
    assert _retry_delay(1, TelegramApiError(429, "Too Many Requests", 999999)) == OUTBOX_MAX_RETRY_AFTER
    assert _retry_delay(1, TelegramApiError(500, "oops")) == 2  # no retry_after -> normal backoff


# ----- check + auto-provisioning of topics (Mirza-style "sync topics") -----
class FakeChannel:
    """Stands in for TelegramChannel; records which topics were created and can simulate rights / forum state."""

    def __init__(self, *, is_forum=True, status="administrator", manage=True, chat_type="supergroup", fail_on=None):
        self.is_forum, self.status, self.manage, self.chat_type, self.fail_on = is_forum, status, manage, chat_type, fail_on
        self.created: list[str] = []
        self.gone: set[int] = set()  # thread ids deleted in the group
        self.probe_error: TelegramApiError | None = None  # a failure that says nothing about the topic (rights, flood)
        self.probed: list[int] = []

    async def reopen_forum_topic(self, chat_id, thread_id):
        self.probed.append(thread_id)
        if self.probe_error is not None:
            raise self.probe_error
        if thread_id in self.gone:
            raise TelegramApiError(400, "Bad Request: message thread not found")
        raise TelegramApiError(400, "Bad Request: TOPIC_NOT_MODIFIED")  # what Telegram says about an open topic

    async def get_me(self):
        return {"id": 42, "username": "shop_bot"}

    async def get_chat(self, chat_id):
        return {"title": "Ops", "type": self.chat_type, "is_forum": self.is_forum}

    async def get_chat_member(self, chat_id, user_id):
        assert user_id == 42
        return {"status": self.status, "can_manage_topics": self.manage}

    async def create_forum_topic(self, chat_id, name):
        if self.fail_on == name:
            raise TelegramApiError(400, "Bad Request: not enough rights to create a topic")
        self.created.append(name)
        return 100 + len(self.created)


@pytest.fixture
def fake_channel(monkeypatch):
    holder = {}

    def install(**kw):
        holder["ch"] = FakeChannel(**kw)
        monkeypatch.setattr(service, "_channel", lambda token: holder["ch"])
        return holder["ch"]

    return install


async def test_check_reports_ok_and_missing_topics(fake_channel):
    ch = fake_channel()
    async with open_session() as s:
        _, _, reseller = await _world(s)
        res = await service.inspect(s, store=reseller)
        assert res["ok"] and res["is_forum"] and res["can_manage_topics"] and res["bot_username"] == "shop_bot"
        assert set(res["missing_topics"]) == {"debt", "tickets", "errors"}
        assert ch.created == []  # check never changes anything


async def test_check_explains_every_problem(fake_channel):
    fake_channel(is_forum=False, status="member", manage=False, chat_type="group")
    async with open_session() as s:
        _, _, reseller = await _world(s)
        res = await service.inspect(s, store=reseller)
        assert not res["ok"] and len(res["problems"]) == 2  # not a supergroup + Topics off (member can still post)
    fake_channel(status="left")
    async with open_session() as s:
        _, _, reseller = await _world(s)
        res = await service.inspect(s, store=reseller)
        assert any("عضو" in p for p in res["problems"])


async def test_provision_creates_only_missing_topics_and_keeps_existing_ids(fake_channel):
    ch = fake_channel()
    async with open_session() as s:
        _, _, reseller = await _world(s)
        res = await service.provision_topics(s, store=reseller, actor_id=uuid.uuid4())
        assert res["created"] == 3 and len(ch.created) == 3
        dest = await service.get_destination(s, reseller.id)
        assert dest.topics["payments"] == 11 and dest.topics["orders"] == 12  # untouched
        assert set(dest.topics) == set(service.TOPICS) and all(isinstance(v, int) for v in dest.topics.values())
        again = await service.provision_topics(s, store=reseller, actor_id=uuid.uuid4())
        assert again["created"] == 0 and len(ch.created) == 3  # idempotent: no duplicate topics


async def test_provision_recreates_a_topic_that_was_deleted_in_the_group(fake_channel):
    ch = fake_channel()
    async with open_session() as s:
        _, _, reseller = await _world(s)
        await service.provision_topics(s, store=reseller, actor_id=uuid.uuid4())  # fills debt / tickets / errors
        saved = set((await service.get_destination(s, reseller.id)).topics.values())
        ch.gone, ch.probed, before = {11}, [], len(ch.created)  # the owner deletes the "payments" topic (thread 11) in Telegram
        res = await service.provision_topics(s, store=reseller, actor_id=uuid.uuid4())
        statuses = {r["topic"]: r["status"] for r in res["results"]}
        assert statuses["payments"] == "recreated" and statuses["orders"] == "kept"
        assert res["recreated"] == 1 and res["created"] == 0 and ch.created[before:] == [service.TOPICS["payments"]]
        dest = await service.get_destination(s, reseller.id)
        assert dest.topics["payments"] not in saved and dest.topics["orders"] == 12  # only the dead id is replaced
        assert set(ch.probed) == saved  # every saved id was checked against Telegram
        again = await service.provision_topics(s, store=reseller, actor_id=uuid.uuid4())
        assert again["recreated"] == 0 and again["created"] == 0  # stable afterwards


async def test_provision_does_not_recreate_when_the_probe_fails_for_another_reason(fake_channel):
    ch = fake_channel()
    async with open_session() as s:
        _, _, reseller = await _world(s)
        ch.probe_error = TelegramApiError(429, "Too Many Requests: retry after 5", 5)
        res = await service.provision_topics(s, store=reseller, actor_id=uuid.uuid4())
        assert [r["status"] for r in res["results"]] == ["failed"]  # stops at the first problem, nothing duplicated
        assert ch.created == [] and res["recreated"] == 0
        dest = await service.get_destination(s, reseller.id)
        assert dest.topics["payments"] == 11 and dest.topics["orders"] == 12  # ids untouched, error recorded
        assert dest.last_error.startswith("429")


async def test_provision_refuses_without_forum_or_rights(fake_channel):
    async with open_session() as s:
        _, _, reseller = await _world(s)
        fake_channel(is_forum=False)
        with pytest.raises(AppError) as e:
            await service.provision_topics(s, store=reseller, actor_id=uuid.uuid4())
        assert e.value.code == "EVENT_CENTER_NOT_FORUM"
        fake_channel(manage=False)
        with pytest.raises(AppError) as e:
            await service.provision_topics(s, store=reseller, actor_id=uuid.uuid4())
        assert e.value.code == "EVENT_CENTER_NO_RIGHTS"


async def test_provision_keeps_progress_when_a_topic_fails_midway(fake_channel):
    ch = fake_channel(fail_on=service.TOPICS["tickets"])
    async with open_session() as s:
        _, _, reseller = await _world(s)
        res = await service.provision_topics(s, store=reseller, actor_id=uuid.uuid4())
        statuses = {r["topic"]: r["status"] for r in res["results"]}
        assert statuses["debt"] == "created" and statuses["tickets"] == "failed" and "errors" not in statuses
        dest = await service.get_destination(s, reseller.id)
        assert "debt" in dest.topics and "tickets" not in dest.topics and dest.last_error.startswith("400")
        ch.fail_on = None  # the owner fixes the right and retries: only the rest is created
        res2 = await service.provision_topics(s, store=reseller, actor_id=uuid.uuid4())
        assert res2["created"] == 2 and ch.created.count(service.TOPICS["debt"]) == 1


async def test_check_and_provision_need_a_configured_group(fake_channel):
    fake_channel()
    async with open_session() as s:
        await make_store(s, kind="main")
        await s.commit()
        for fn in (service.inspect,):
            with pytest.raises(AppError) as e:
                await fn(s, store=None)
            assert e.value.code == "EVENT_CENTER_NOT_SET"


def test_telegram_errors_become_actionable_messages():
    cases = {
        (401, "Unauthorized"): "EVENT_CENTER_BAD_TOKEN",
        (400, "Bad Request: chat not found"): "EVENT_CENTER_CHAT_NOT_FOUND",
        (400, "Bad Request: the chat is not a forum"): "EVENT_CENTER_NOT_FORUM",
        (400, "Bad Request: not enough rights to manage topics"): "EVENT_CENTER_NO_RIGHTS",
        (403, "Forbidden: bot was kicked from the supergroup chat"): "EVENT_CENTER_BOT_REMOVED",
        (429, "Too Many Requests"): "EVENT_CENTER_TELEGRAM_UNAVAILABLE",
    }
    for (code, desc), expected in cases.items():
        assert service.tg_error(TelegramApiError(code, desc)).code == expected
