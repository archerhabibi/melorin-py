"""Event Center extra topics: nightly report, affiliate, test accounts, backup (SRS §17, Mirza-style report topics)."""

import datetime as dt
import uuid

import pytest
from sqlalchemy import select

from _db import make_order, make_product, make_store, make_user, open_session
from melorin.core import events
from melorin.core.crypto import encrypt
from melorin.core.db import utcnow
from melorin.core.errors import AppError
from melorin.kernel.models.notifications import TelegramEventDestination
from melorin.kernel.models.payments import Payment
from melorin.kernel.models.referral import CommissionRule, ReferralRelationship
from melorin.kernel.models.system import BackupRun, OutboxEvent
from melorin.kernel.models.tickets import Ticket
from melorin.modules.eventcenter import report, rules, service
from melorin.modules.eventcenter.topics import ADMIN_ONLY_TOPICS, TOPICS, topics_for
from melorin.modules.referral import service as referral

ADMIN_GROUP, STORE_GROUP = "-1001111111111", "-1002222222222"


@pytest.fixture(autouse=True)
def fake_tokens(monkeypatch):
    monkeypatch.setattr(service, "_store_token", lambda store: "tok-r" if store is not None and store.kind == "reseller" else "tok-main")


async def _world(s, *, store_enabled=True):
    main = await make_store(s, kind="main")
    reseller = await make_store(s, kind="reseller", owner=await make_user(s))
    reseller.bot_token_enc = encrypt("123:abc")
    s.add(TelegramEventDestination(store_id=None, chat_id=ADMIN_GROUP, topics={}, is_enabled=True))
    s.add(TelegramEventDestination(store_id=reseller.id, chat_id=STORE_GROUP, topics={}, is_enabled=store_enabled))
    await s.commit()
    return main, reseller


async def _delivered(s, topic):
    rows = (await s.scalars(select(OutboxEvent).where(OutboxEvent.topic == events.EVENT_CENTER_DELIVER))).all()
    return [r.payload for r in rows if r.payload["topic"] == topic]


async def _queued(s, topic):
    rows = (await s.scalars(select(OutboxEvent).where(OutboxEvent.topic == events.EVENT_CENTER))).all()
    return [r.payload for r in rows if r.payload["topic"] == topic]


# ----- which destination has which topic -----
def test_platform_topics_exist_only_for_the_admin():
    assert set(topics_for(True)) == set(TOPICS) and len(TOPICS) == 9
    reseller = topics_for(False)
    assert not (set(reseller) & ADMIN_ONLY_TOPICS) and {"daily", "tests"} <= set(reseller)
    assert {"backup", "affiliate"} == set(ADMIN_ONLY_TOPICS)
    assert service.parse_topics({"backup": 5}) == {"backup": 5}  # known to the admin
    with pytest.raises(AppError) as e:
        service.parse_topics({"backup": 5}, topics_for(False))
    assert e.value.code == "INVALID_TOPICS"


async def test_a_reseller_cannot_save_or_see_platform_topics_but_the_admin_can():
    async with open_session() as s:
        _, reseller = await _world(s)
        with pytest.raises(AppError) as e:
            await service.save(
                s, store=reseller, actor_id=uuid.uuid4(), chat_id=STORE_GROUP, topics={"affiliate": 9}, is_enabled=True, note=None
            )
        assert e.value.code == "INVALID_TOPICS"
        await service.save(
            s, store=None, actor_id=uuid.uuid4(), chat_id=ADMIN_GROUP, topics={"backup": 9, "daily": 8}, is_enabled=True, note=None
        )
        admin_dest = await service.get_destination(s, None)
        keys = lambda d, admin: [t["key"] for t in service.view(d, bot_ready=True, admin=admin)["topics"]]  # noqa: E731
        assert "backup" in keys(admin_dest, True) and "affiliate" in keys(admin_dest, True)
        store_dest = await service.get_destination(s, reseller.id)
        assert not ({"backup", "affiliate"} & set(keys(store_dest, False))) and "daily" in keys(store_dest, False)


async def test_admin_provisioning_creates_every_topic_including_backup(monkeypatch):
    from test_event_center import FakeChannel

    ch = FakeChannel()
    monkeypatch.setattr(service, "_channel", lambda token: ch)
    async with open_session() as s:
        await _world(s)
        res = await service.provision_topics(s, store=None, actor_id=uuid.uuid4())
        assert res["created"] == 9 and service.TOPICS["backup"] in ch.created
        dest = await service.get_destination(s, None)
        assert set(dest.topics) == set(TOPICS)


async def test_backup_events_never_reach_a_reseller_group():
    async with open_session() as s:
        _, reseller = await _world(s)
        assert await service.publish(s, store_id=reseller.id, topic="backup", text="x", source_key="b1") == 0
        assert await service.publish(s, store_id=None, topic="backup", text="x", source_key="b2") == 1
        await s.commit()
        assert [p["destination_id"] for p in await _delivered(s, "backup")] == [str((await service.get_destination(s, None)).id)]


# ----- backup -----
def test_backup_text_is_short_and_never_shows_the_server_path():
    ok = rules.backup_text("succeeded", 5 * 1024 * 1024, "encrypted artifact and checksum verification completed; copied to S3")
    assert "موفق" in ok and "5.0 MB" in ok and "S3" in ok
    local = rules.backup_text("succeeded", 2048, "encrypted artifact and checksum verification completed; local only")
    assert "2 KB" in local and "فقط روی سرور" in local
    partial = rules.backup_text("partial", 1024, "x" * 1000)
    assert "ناموفق" in partial and len(partial) < 400
    failed = rules.backup_text("failed", None, "disk full /var/backups/secret.tar")
    assert "🔴" in failed and "نامشخص" not in failed.split("\n")[0]


async def test_a_backup_run_is_announced_once_to_the_admin_backup_topic():
    async with open_session() as s:
        await _world(s)
        run = BackupRun(status="failed", location=None, size=None, details="no space left", created_at=utcnow())
        s.add(run)
        await s.flush()
        await rules.notify_backup(s, run)
        await rules.notify_backup(s, run)  # a retry of the job must not double-post
        await s.commit()
        queued = await _queued(s, "backup")
        assert len(queued) == 1 and queued[0]["store_id"] is None and "no space left" in queued[0]["text"]


# ----- test accounts -----
async def test_a_completed_test_order_goes_to_the_tests_topic_not_the_orders_topic():
    async with open_session() as s:
        _, reseller = await _world(s)
        user, product = await make_user(s), await make_product(s)
        test = await make_order(s, user=user, store=reseller, product=product, total=0, status="completed")
        test.kind = "test"
        real = await make_order(s, user=user, store=reseller, product=product, total=1000, status="completed")
        await s.commit()
        hit = await rules._completed(s, None, {"order_id": test.id})
        assert hit[0] == reseller.id and hit[1] == "tests" and test.number in hit[2] and "اکانت تست" in hit[2]
        assert await rules._paid(s, None, {"order_id": test.id}) is None  # a free test has no sale
        assert await rules._refunded(s, None, {"order_id": test.id}) is None
        sale = await rules._completed(s, None, {"order_id": real.id})
        assert sale[1] == "orders" and "1,000" in sale[2]


# ----- affiliate -----
async def _referral_world(s):
    referrer, referred = await make_user(s), await make_user(s)
    main, reseller = await _world(s)
    product = await make_product(s)
    s.add(ReferralRelationship(store_id=main.id, referrer_user_id=referrer.id, referred_user_id=referred.id))
    s.add(CommissionRule(store_id=main.id, kind="signup_reward", model="fixed", value=500, is_active=True))
    await s.commit()
    return referrer, referred, main, reseller, product


async def test_new_referral_commission_and_its_reversal_are_announced_to_the_admin():
    async with open_session() as s:
        referrer, referred, main, _, product = await _referral_world(s)
        newcomer = await make_user(s)
        await referral.attach(s, main.id, newcomer, referrer)
        await referral.attach(s, main.id, newcomer, referrer)  # first-touch: the second call is ignored
        order = await make_order(s, user=referred, store=main, product=product, status="completed", number="777001")
        order.completed_at = utcnow()
        await s.commit()
        await referral.on_order_completed(s, order.id)
        await s.commit()
        texts = [p["text"] for p in await _queued(s, "affiliate")]
        assert sum("معرف جدید" in t for t in texts) == 1
        assert any("777001" in t and "500" in t and "اولین خرید" in t for t in texts)
        await referral.on_order_refunded(s, order.id)
        await s.commit()
        texts = [p["text"] for p in await _queued(s, "affiliate")]
        assert any("برگشت خورد" in t and "777001" in t and "500" in t for t in texts)
        # every one of them lands in the admin's group (the main store has no group of its own)
        for p in await _queued(s, "affiliate"):
            e = OutboxEvent(topic=events.EVENT_CENTER, payload=p)
            assert await rules.tap(s, e) == 1
        await s.commit()
        assert {p["destination_id"] for p in await _delivered(s, "affiliate")} == {str((await service.get_destination(s, None)).id)}


# ----- nightly report -----
async def _payment(s, user, store, status, amount):
    p = Payment(
        user_id=user.id,
        store_id=store.id,
        purpose="wallet_topup",
        provider="manual_card",
        amount=amount,
        currency=store.currency,
        status=status,
    )
    s.add(p)
    await s.flush()
    return p


async def _busy_night(s):
    referrer, referred, main, reseller, product = await _referral_world(s)
    sale = await make_order(s, user=referred, store=reseller, product=product, total=2500, status="completed")
    sale.completed_at = utcnow()
    main_sale = await make_order(s, user=referred, store=main, product=product, total=1000, status="completed")
    main_sale.completed_at = utcnow()
    test = await make_order(s, user=referred, store=reseller, product=product, total=0, status="completed")
    test.kind, test.completed_at = "test", utcnow()
    await _payment(s, referred, reseller, "succeeded", 2500)
    await _payment(s, referred, reseller, "failed", 100)
    await _payment(s, referred, main, "awaiting_review", 900)
    s.add(Ticket(user_id=referred.id, store_id=reseller.id, number="900001", subject="s", status="open"))
    await s.commit()
    return main, reseller


async def test_nightly_report_of_a_store_counts_only_its_own_numbers():
    async with open_session() as s:
        main, reseller = await _busy_night(s)
        end = utcnow() + dt.timedelta(minutes=1)
        text = await report.build(s, reseller.id, end - dt.timedelta(hours=24), end, "2026-10-24")
        assert "2026-10-24" in text and "فروشگاه شما" in text
        assert "1 سفارش — 2,500 IRT" in text  # the main store's 1,000 is not mixed in
        assert "اکانت تست: 1" in text and "تیکت جدید: 1" in text and "ناموفق: 1" in text
        assert "معرف" not in text  # the referral program belongs to the Main Store only
        assert "رسید 0" in text  # the pending receipt belongs to the main store


async def test_nightly_report_of_the_admin_covers_the_whole_platform():
    async with open_session() as s:
        await _busy_night(s)
        end = utcnow() + dt.timedelta(minutes=1)
        text = await report.build(s, None, end - dt.timedelta(hours=24), end, "2026-10-24")
        assert "کل پلتفرم" in text and "2 سفارش — 3,500 IRT" in text and "معرف جدید" in text and "رسید 1" in text


async def test_nightly_run_queues_one_report_per_enabled_group_and_only_once_per_night():
    async with open_session() as s:
        _, reseller = await _world(s)
        now = utcnow()
        assert await report.run(s, now=now) == 2
        await s.commit()
        await report.run(s, now=now)  # a doubled or restarted cron: routed again, but deduplicated into no new row
        await s.commit()
        rows = await _delivered(s, "daily")
        assert len(rows) == 2 and {("فروشگاه شما" in r["text"]) for r in rows} == {True, False}
        await report.run(s, now=now + dt.timedelta(days=1))  # the next night is a new report
        await s.commit()
        assert len(await _delivered(s, "daily")) == 4


async def test_nightly_run_skips_a_disabled_group():
    async with open_session() as s:
        await _world(s, store_enabled=False)
        assert await report.run(s, now=utcnow()) == 1  # only the admin's group


def test_the_report_is_scheduled_at_tehran_midnight():
    from melorin.worker import arq_app

    assert any(c.name == "cron:daily_report_job" and c.hour == 20 and c.minute == 30 for c in arq_app.WorkerSettings.cron_jobs)
    assert arq_app.daily_report_job in arq_app.WorkerSettings.functions
