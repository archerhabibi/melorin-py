"""Phase 4: outbox worker (claim/lease, retry/backoff, notifications, revoke/rollback) against real tables."""

from __future__ import annotations

import datetime as dt
import types
import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from _db import make_order, make_product, make_store, make_user, open_schema_engine
from melorin.core.crypto import encrypt
from melorin.core.db import utcnow
from melorin.kernel.models.identity import Identity
from melorin.kernel.models.notifications import Notification
from melorin.kernel.models.system import OutboxEvent
from melorin.kernel.models.vpn import Panel, VpnAccount
from melorin.kernel.models.webhooks import WebhookDelivery, WebhookEndpoint
from melorin.worker import runner


@pytest.fixture
async def maker(monkeypatch):
    async with open_schema_engine() as engine:
        m = async_sessionmaker(engine, expire_on_commit=False)
        monkeypatch.setattr(runner, "session_factory", lambda: m)
        yield m


def _aware(value):
    """SQLite hands back naive datetimes; PostgreSQL aware ones. Compare in UTC either way."""
    return value if value.tzinfo else value.replace(tzinfo=dt.UTC)


def _event(topic="x.unknown", payload=None, **kw):
    return OutboxEvent(topic=topic, payload=payload or {}, **kw)


# --- claim_batch ---------------------------------------------------------------------------------------------------


async def test_claim_batch_takes_due_pending_rows_in_order_and_marks_them_processing(maker):
    now = utcnow()
    async with maker() as s:
        s.add_all(
            [
                _event(created_at=now - dt.timedelta(minutes=3), dedup_key="a"),
                _event(created_at=now - dt.timedelta(minutes=2), dedup_key="b"),
                _event(created_at=now - dt.timedelta(minutes=1), dedup_key="c", available_at=now + dt.timedelta(hours=1)),
                _event(created_at=now, dedup_key="d", status="processed"),
            ]
        )
        await s.commit()
    async with maker() as s:
        rows = await runner.claim_batch(s, n=10)
    assert [r.dedup_key for r in rows] == ["a", "b"]
    assert all(r.status == "processing" and r.locked_at for r in rows)


async def test_claim_batch_respects_batch_size(maker):
    async with maker() as s:
        s.add_all([_event(dedup_key=f"k{i}") for i in range(5)])
        await s.commit()
    async with maker() as s:
        assert len(await runner.claim_batch(s, n=2)) == 2


async def test_claim_batch_recovers_rows_whose_worker_died_but_not_fresh_claims(maker):
    now = utcnow()
    async with maker() as s:
        s.add_all(
            [
                _event(dedup_key="dead", status="processing", locked_at=now - dt.timedelta(minutes=30)),
                _event(dedup_key="busy", status="processing", locked_at=now - dt.timedelta(minutes=1)),
            ]
        )
        await s.commit()
    async with maker() as s:
        rows = await runner.claim_batch(s)
    assert [r.dedup_key for r in rows] == ["dead"]  # the stale lease was released and re-claimed; the live one is untouched


# --- process_event -------------------------------------------------------------------------------------------------


async def _claimed(maker, topic="x.unknown", payload=None):
    async with maker() as s:
        e = _event(topic, payload, status="processing", locked_at=utcnow())
        s.add(e)
        await s.commit()
        return e


async def _reload(maker, e):
    async with maker() as s:
        return await s.get(OutboxEvent, e.id)


async def test_process_event_runs_handler_and_marks_processed(maker, monkeypatch):
    seen = []

    async def handler(session, p):
        seen.append(p)

    monkeypatch.setitem(runner._TOPIC_HANDLERS, "t.ok", handler)
    e = await _claimed(maker, "t.ok", {"a": 1})
    await runner.process_event(e)
    row = await _reload(maker, e)
    assert seen == [{"a": 1}] and row.status == "processed" and row.processed_at and row.last_error is None


async def test_process_event_acknowledges_unknown_topics_without_work(maker):
    e = await _claimed(maker, "nobody.listens")
    await runner.process_event(e)
    assert (await _reload(maker, e)).status == "processed"


async def test_process_event_ignores_rows_not_in_processing_state(maker):
    async with maker() as s:
        e = _event(status="processed")
        s.add(e)
        await s.commit()
    await runner.process_event(e)  # no exception, no state change
    assert (await _reload(maker, e)).status == "processed"
    await runner.process_event(types.SimpleNamespace(id=uuid.uuid4()))  # row vanished


async def test_process_event_failure_requeues_with_exponential_backoff(maker, monkeypatch):
    async def boom(session, p):
        raise RuntimeError("provider down")

    monkeypatch.setitem(runner._TOPIC_HANDLERS, "t.boom", boom)
    e = await _claimed(maker, "t.boom")
    for expected_attempts, max_delay in ((1, 2), (2, 4), (3, 8)):
        before = utcnow()
        async with maker() as s:  # simulate claim_batch re-claiming the retried row
            row = await s.get(OutboxEvent, e.id)
            row.status = "processing"
            await s.commit()
        await runner.process_event(e)
        row = await _reload(maker, e)
        assert (row.status, row.attempts, row.last_error) == ("pending", expected_attempts, "provider down")
        assert before < _aware(row.available_at) <= utcnow() + dt.timedelta(seconds=max_delay + 1)


# --- webhook fan-out -----------------------------------------------------------------------------------------------


async def test_webhook_enqueue_is_best_effort_and_needs_a_store(maker, monkeypatch, caplog):
    async with maker() as s:
        await runner._webhook(s, "order.completed", {}, "e1")  # no store_id -> silently nothing
        assert (await s.scalars(select(WebhookDelivery))).all() == []

        async def broken(*a, **k):
            raise RuntimeError("db hiccup")

        monkeypatch.setattr("melorin.modules.webhooks.service.enqueue_event", broken)
        await runner._webhook(s, "order.completed", {"store_id": str(uuid.uuid4())}, "e2")  # swallowed, logged
    assert "webhook enqueue failed" in caplog.text


async def test_webhook_enqueue_creates_a_delivery_for_a_subscribed_endpoint(maker):
    async with maker() as s:
        store = await make_store(s)
        s.add(WebhookEndpoint(store_id=store.id, url="https://h.example.com", events=["*"], secret_enc=encrypt("s")))
        await s.commit()
        await runner._webhook(s, "order.completed", {"store_id": str(store.id), "order_id": "o"}, "order.completed:o")
        await s.commit()
        (d,) = (await s.scalars(select(WebhookDelivery))).all()
        assert d.event_id == "order.completed:o" and d.store_id == store.id


async def test_notify_handler_fans_expiry_notifications_out_to_webhooks(maker, monkeypatch):
    calls = []

    async def fake_notify(session, p, kind, title, body):
        calls.append(("notify", kind, title, body))

    async def fake_webhook(session, name, p, eid):
        calls.append(("hook", name, eid))

    monkeypatch.setattr(runner, "_notify", fake_notify)
    monkeypatch.setattr(runner, "_webhook", fake_webhook)
    sid = str(uuid.uuid4())
    await runner._on_notify(None, {"kind": "vpn_expired", "store_id": sid, "dedup_key": "k1"})
    await runner._on_notify(None, {"kind": "general", "store_id": sid})
    assert calls == [
        ("notify", "vpn_expired", "Melorin", ""),
        ("hook", "vpn_account.expired", "vpn_expired:k1"),
        ("notify", "general", "Melorin", ""),
    ]


async def test_simple_handlers_delegate_to_their_collaborators(maker, monkeypatch):
    log = []

    async def rec(name, *a, **k):
        log.append(name)

    monkeypatch.setattr(runner, "_event_center", lambda s, p: rec("event_center"))
    monkeypatch.setattr(runner, "revoke_account", lambda s, i: rec(f"revoke:{i}"))
    monkeypatch.setattr(runner, "rollback_renewal", lambda s, p: rec("rollback"))
    acc = uuid.uuid4()
    await runner._on_event_center(None, {})
    await runner._on_vpn_revoke(None, {"vpn_account_id": str(acc)})
    await runner._on_vpn_renewal_rollback(None, {})
    assert log == ["event_center", f"revoke:{acc}", "rollback"]


async def test_order_topic_handlers_delegate_to_provisioning_referral_and_delivery(maker, monkeypatch):
    log = []
    oid = uuid.uuid4()

    async def rec(name, *a, **k):
        log.append(name)

    monkeypatch.setattr(runner.vpn, "provision_order", lambda s, i: rec(f"provision:{i}"))
    monkeypatch.setattr("melorin.modules.referral.service.on_order_completed", lambda s, i: rec("ref_done"))
    monkeypatch.setattr("melorin.modules.referral.service.on_order_refunded", lambda s, i: rec("ref_refund"))
    monkeypatch.setattr("melorin.modules.orders.delivery.deliver_order", lambda s, i: rec(f"deliver:{i}"))
    monkeypatch.setattr(runner, "_webhook", lambda s, name, p, eid: rec(f"hook:{eid}"))
    monkeypatch.setattr(runner, "_notify_admins_provisioning_failed", lambda s, p: rec("admins"))
    p = {"order_id": str(oid)}
    await runner._on_order_paid(None, p)
    await runner._on_order_completed(None, p)
    await runner._on_order_delivery(None, p)
    await runner._on_order_refunded(None, p)
    await runner._on_provisioning_failed(None, p)
    assert log == [
        f"provision:{oid}", "ref_done", f"hook:order.completed:{oid}", f"deliver:{oid}",
        "ref_refund", f"hook:order.refunded:{oid}", "admins", f"hook:order.provisioning_failed:{oid}",
    ]  # fmt: skip


async def test_event_center_consumer_only_logs(caplog):
    caplog.set_level("INFO", logger="melorin.worker")
    await runner._event_center(None, {"store_id": "s", "topic": "t", "text": "hello"})
    assert "event-center store=s topic=t text=hello" in caplog.text


# --- _notify -------------------------------------------------------------------------------------------------------


class FakeTelegram:
    sent: list = []
    fail = False

    def __init__(self, token, web_url, kind):
        self.token, self.kind = token, kind

    async def send_message(self, chat, text):
        if FakeTelegram.fail:
            raise RuntimeError("telegram 502")
        FakeTelegram.sent.append((self.token, self.kind, chat, text))


@pytest.fixture
def tg(monkeypatch):
    FakeTelegram.sent, FakeTelegram.fail = [], False
    monkeypatch.setattr("melorin.channels.telegram.TelegramChannel", FakeTelegram)
    monkeypatch.setattr(runner, "get_settings", lambda: types.SimpleNamespace(main_bot_token="MAIN-TOKEN", store_web_url="https://shop"))
    return FakeTelegram


async def _tg_user(s, *, store=None, chat="555"):
    user = await make_user(s)
    s.add(Identity(user_id=user.id, provider="telegram", subject=chat))
    await s.flush()
    return user


async def test_notify_without_user_is_a_noop(maker, tg):
    async with maker() as s:
        await runner._notify(s, {}, "k", "t")
        assert (await s.scalars(select(Notification))).all() == []


async def test_notify_sends_via_main_bot_and_is_idempotent_by_dedup_key(maker, tg):
    async with maker() as s:
        user = await _tg_user(s)
        p = {"user_id": user.id, "dedup_key": "dk"}
        await runner._notify(s, p, "kind", "Title", "Body")
        await runner._notify(s, p, "kind", "Title", "Body")  # already sent -> no second message
        await s.commit()
        (n,) = (await s.scalars(select(Notification))).all()
    assert n.telegram_status == "sent"
    assert tg.sent == [("MAIN-TOKEN", "main", "555", "Title\nBody")]


async def test_notify_uses_the_store_bot_for_reseller_stores(maker, tg):
    async with maker() as s:
        owner = await make_user(s)
        store = await make_store(s, kind="reseller", owner=owner)
        store.bot_token_enc = encrypt("STORE-TOKEN")
        user = await _tg_user(s)
        await runner._notify(s, {"user_id": user.id, "store_id": store.id}, "k", "T", "B")
        await s.commit()
    assert tg.sent == [("STORE-TOKEN", "reseller", "555", "T\nB")]


async def test_notify_skips_users_without_telegram_or_without_any_bot_token(maker, tg, monkeypatch):
    async with maker() as s:
        plain = await make_user(s)
        await runner._notify(s, {"user_id": plain.id, "dedup_key": "a"}, "k", "T")
        monkeypatch.setattr(runner, "get_settings", lambda: types.SimpleNamespace(main_bot_token="", store_web_url=""))
        linked = await _tg_user(s)
        await runner._notify(s, {"user_id": linked.id, "dedup_key": "b"}, "k", "T")
        await s.commit()
        st = {n.dedup_key: n.telegram_status for n in (await s.scalars(select(Notification))).all()}
    assert st == {"a": "skipped", "b": "skipped"} and tg.sent == []


async def test_notify_marks_failure_and_reraises_so_the_outbox_retries_then_resends(maker, tg):
    async with maker() as s:
        user = await _tg_user(s)
        p = {"user_id": user.id, "dedup_key": "retry"}
        tg.fail = True
        with pytest.raises(RuntimeError):
            await runner._notify(s, p, "k", "T", "B")
        await s.commit()
        assert (await s.scalar(select(Notification.telegram_status))) == "failed"
        tg.fail = False
        await runner._notify(s, p, "k", "T", "B")  # same notification row is reused, not duplicated
        await s.commit()
        assert len((await s.scalars(select(Notification))).all()) == 1
    assert len(tg.sent) == 1


# --- provisioning-failed admin alert -------------------------------------------------------------------------------


async def test_provisioning_failed_alert_reaches_every_active_super_admin_once(maker, tg):
    async with maker() as s:
        store, buyer, product = await make_store(s), await make_user(s), await make_product(s)
        order = await make_order(s, user=buyer, store=store, product=product, status="refunded", number="A100")
        a1, a2 = await make_user(s, super_admin=True), await make_user(s, super_admin=True)
        gone = await make_user(s, super_admin=True)
        gone.is_active = False
        for u, chat in ((a1, "1"), (a2, "2"), (gone, "3")):
            s.add(Identity(user_id=u.id, provider="telegram", subject=chat))
        await s.flush()
        p = {"order_id": str(order.id), "error": "panel timeout"}
        await runner._notify_admins_provisioning_failed(s, p)
        await runner._notify_admins_provisioning_failed(s, p)  # outbox retry: nobody is messaged twice
        await s.commit()
    assert sorted(c for _, _, c, _ in tg.sent) == ["1", "2"]
    text = tg.sent[0][3]
    assert "A100" in text and "panel timeout" in text and "برگشت داده شد" in text


async def test_provisioning_failed_alert_reports_unrefunded_orders_and_survives_one_bad_admin(maker, tg):
    async with maker() as s:
        store, buyer, product = await make_store(s), await make_user(s), await make_product(s)
        order = await make_order(s, user=buyer, store=store, product=product, status="provisioning_failed")
        admin = await make_user(s, super_admin=True)
        s.add(Identity(user_id=admin.id, provider="telegram", subject="9"))
        await s.flush()
        tg.fail = True
        with pytest.raises(RuntimeError):
            await runner._notify_admins_provisioning_failed(s, {"order_id": str(order.id)})
        tg.fail = False
        await runner._notify_admins_provisioning_failed(s, {"order_id": str(order.id)})
        await s.commit()
    assert "بازگشت خودکار وجه انجام نشد" in tg.sent[0][3] and "نامشخص" in tg.sent[0][3]


async def test_provisioning_failed_alert_for_unknown_order_still_alerts_without_outcome(maker, tg):
    async with maker() as s:
        admin = await make_user(s, super_admin=True)
        s.add(Identity(user_id=admin.id, provider="telegram", subject="9"))
        await s.flush()
        oid = uuid.uuid4()
        await runner._notify_admins_provisioning_failed(s, {"order_id": str(oid), "error": "x"})
        await s.commit()
    assert str(oid)[:8] in tg.sent[0][3] and "✅" not in tg.sent[0][3] and "❌" not in tg.sent[0][3]


# --- revoke / rollback ---------------------------------------------------------------------------------------------


class _PanelAdapter:
    def __init__(self):
        self.revoked, self.extended = [], []

    async def revoke_account(self, username):
        self.revoked.append(username)

    async def extend_account(self, username, *, expire_at, traffic_bytes):
        self.extended.append((username, expire_at, traffic_bytes))
        return types.SimpleNamespace(expire_at=expire_at, traffic_limit_bytes=traffic_bytes)


async def _vpn(s, *, with_panel=True, username="acc1"):
    store, user, product = await make_store(s), await make_user(s), await make_product(s)
    order = await make_order(s, user=user, store=store, product=product)
    panel = Panel(name="p", kind="mock", base_url="http://p")
    s.add(panel)
    await s.flush()
    a = VpnAccount(
        username=username, user_id=user.id, store_id=store.id, order_id=order.id, product_id=product.id,
        panel_id=panel.id if with_panel else None, status="active", traffic_limit_bytes=999,
    )  # fmt: skip
    s.add(a)
    await s.flush()
    return a


async def test_revoke_account_calls_the_panel_and_marks_revoked(maker, monkeypatch):
    adapter = _PanelAdapter()
    monkeypatch.setattr(runner, "build_adapter", lambda panel: adapter)
    async with maker() as s:
        a = await _vpn(s)
        await runner.revoke_account(s, a.id)
        assert adapter.revoked == ["acc1"] and a.status == "revoked"
        await runner.revoke_account(s, uuid.uuid4())  # unknown account: nothing happens
        orphan = await _vpn(s, with_panel=False, username="orphan")
        await runner.revoke_account(s, orphan.id)
        assert adapter.revoked == ["acc1"] and orphan.status == "active"


async def test_rollback_renewal_restores_expiry_and_traffic_from_the_snapshot(maker, monkeypatch):
    adapter = _PanelAdapter()
    monkeypatch.setattr(runner, "build_adapter", lambda panel: adapter)
    before_exp = dt.datetime(2026, 1, 1, tzinfo=dt.UTC)
    async with maker() as s:
        a = await _vpn(s)
        await runner.rollback_renewal(
            s, {"vpn_account_id": str(a.id), "before": {"expires_at": before_exp.isoformat(), "traffic_limit_bytes": 5}}
        )
        assert adapter.extended == [("acc1", before_exp, 5)]
        assert a.traffic_limit_bytes == 5 and a.expires_at.replace(tzinfo=dt.UTC) == before_exp
        # a snapshot without values rolls back to "no expiry / no limit"
        await runner.rollback_renewal(s, {"vpn_account_id": str(a.id)})
        assert adapter.extended[-1] == ("acc1", None, 0)
        await runner.rollback_renewal(s, {"vpn_account_id": str(uuid.uuid4())})
        assert len(adapter.extended) == 2


# --- webhook queue -------------------------------------------------------------------------------------------------


async def _delivery(s, **kw):
    store = await make_store(s)
    e = WebhookEndpoint(store_id=store.id, url="https://h.example.com", events=["*"], secret_enc=encrypt("s"))
    s.add(e)
    await s.flush()
    d = WebhookDelivery(endpoint_id=e.id, store_id=store.id, event_id=uuid.uuid4().hex, event_type="order.completed", payload={}, **kw)
    s.add(d)
    await s.flush()
    return d


async def test_claim_webhook_batch_claims_due_pending_and_recovers_stuck_deliveries(maker):
    now = utcnow()
    async with maker() as s:
        due = await _delivery(s)
        future = await _delivery(s, next_attempt_at=now + dt.timedelta(hours=1))
        stuck = await _delivery(s, status="delivering")
        stuck.updated_at = now - dt.timedelta(minutes=30)
        fresh = await _delivery(s, status="delivering")
        fresh.updated_at = now
        await s.commit()
    async with maker() as s:
        rows = await runner.claim_webhook_batch(s)
    assert {r.id for r in rows} == {due.id, stuck.id}
    async with maker() as s:
        st = {d.id: d.status for d in (await s.scalars(select(WebhookDelivery))).all()}
    assert st[future.id] == "pending" and st[fresh.id] == "delivering" and st[due.id] == "delivering"


async def test_process_webhook_delegates_and_never_raises(maker, monkeypatch, caplog):
    got = []

    async def ok(session, delivery_id):
        got.append(delivery_id)

    monkeypatch.setattr("melorin.modules.webhooks.service.deliver_one", ok)
    d = types.SimpleNamespace(id=uuid.uuid4())
    await runner.process_webhook(d)
    assert got == [d.id]

    async def boom(session, delivery_id):
        raise RuntimeError("x")

    monkeypatch.setattr("melorin.modules.webhooks.service.deliver_one", boom)
    await runner.process_webhook(d)
    assert "webhook delivery failed" in caplog.text
