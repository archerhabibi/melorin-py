"""One delivery post after a wallet purchase: QR photo + subscription link + wallet balance."""
import types
import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import melorin.models  # noqa: F401  (registers every table)
from melorin.core.db import Base
from melorin.modules.identity.models import Identity, User
from melorin.modules.notifications.models import Notification
from melorin.modules.orders import delivery
from melorin.modules.orders.models import Order
from melorin.modules.vpn.models import VpnAccount
from melorin.modules.wallet.models import LedgerEntry, LedgerTransaction, Wallet

SUB = "https://sub.example.com/sub/AbCdEf123"


@pytest.fixture
async def session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    for table in Base.metadata.sorted_tables:
        try:
            async with engine.begin() as conn:
                await conn.run_sync(lambda sync_conn, t=table: t.create(sync_conn, checkfirst=True))
        except Exception:
            pass
    async with async_sessionmaker(engine, expire_on_commit=False)() as s:
        yield s
    await engine.dispose()


@pytest.fixture
def tg(monkeypatch):
    calls = {"photo": [], "message": []}

    class FakeChannel:
        def __init__(self, *_a, **_k):
            pass

        async def send_photo(self, chat_id, photo, **kw):
            calls["photo"].append({"chat_id": str(chat_id), "photo": photo, **kw})

        async def send_message(self, chat_id, text, **kw):
            calls["message"].append({"chat_id": str(chat_id), "text": text, **kw})

    monkeypatch.setattr("melorin.channels.telegram.TelegramChannel", FakeChannel)
    monkeypatch.setattr(delivery, "get_settings", lambda: types.SimpleNamespace(main_bot_token="tok", store_web_url="http://x"))
    return calls


async def _seed(s, *, link=SUB, total=100_000, balance_after=400_000, kind="purchase", with_telegram=True):
    user = User(id=uuid.uuid4(), display_name="u", is_active=True)
    s.add(user)
    if with_telegram:
        s.add(Identity(user_id=user.id, provider="telegram", subject="555"))
    store_id = uuid.uuid4()
    order = Order(number="AB23CD", user_id=user.id, store_id=store_id, product_id=uuid.uuid4(), kind=kind, status="completed",
                  payment_method="wallet", currency="IRT", unit_price=total, total=total, pricing_snapshot={},
                  product_snapshot={"name": "۳۰ روزه ۵۰ گیگ"})
    s.add(order)
    await s.flush()
    acc = VpnAccount(username="m_ab23cd", user_id=user.id, store_id=store_id, order_id=order.id, product_id=order.product_id,
                     status="active", subscription_url=link, traffic_limit_bytes=50 * 1024**3)
    s.add(acc)
    await s.flush()
    order.vpn_account_id = acc.id
    if total:
        w = Wallet(user_id=user.id, store_id=store_id, kind="customer", currency="IRT", balance=balance_after + 5)  # current != after-payment
        s.add(w)
        await s.flush()
        tx = LedgerTransaction(kind="purchase", idempotency_key=f"order:{order.id}:payment", store_id=store_id, order_id=order.id, currency="IRT")
        s.add(tx)
        await s.flush()
        s.add(LedgerEntry(transaction_id=tx.id, account=f"wallet:{w.id}", wallet_id=w.id, amount=-total, balance_after=balance_after))
    await s.commit()
    return order


async def test_single_photo_post_has_qr_link_and_balance(session, tg):
    order = await _seed(session)
    assert await delivery.deliver_order(session, order.id) == "sent"

    assert len(tg["photo"]) == 1 and tg["message"] == []          # ONE post, no extra message
    post = tg["photo"][0]
    assert post["chat_id"] == "555" and post["photo"][:4] == b"\x89PNG"
    cap = post["caption"]
    assert SUB in cap                                              # subscription link
    assert "400,000" in cap and "موجودی کیف پول" in cap            # balance right after the purchase (ledger), not the later one
    assert "AB23CD" in cap and len(cap) <= delivery.CAPTION_LIMIT
    assert post["parse_mode"] == "HTML"


async def test_retry_after_success_does_not_send_twice(session, tg):
    order = await _seed(session)
    await delivery.deliver_order(session, order.id)
    assert await delivery.deliver_order(session, order.id) == "skipped"
    assert len(tg["photo"]) == 1
    n = (await session.scalars(select(Notification).where(Notification.dedup_key == f"delivery:{order.id}"))).all()
    assert len(n) == 1 and n[0].telegram_status == "sent" and SUB in n[0].body


async def test_transport_failure_raises_for_outbox_retry_then_succeeds(session, tg, monkeypatch):
    order = await _seed(session)
    boom = {"on": True}

    class Flaky:
        def __init__(self, *_a, **_k):
            pass

        async def send_photo(self, chat_id, photo, **kw):
            if boom["on"]:
                raise RuntimeError("telegram down")
            tg["photo"].append({"chat_id": str(chat_id), **kw})

    monkeypatch.setattr("melorin.channels.telegram.TelegramChannel", Flaky)
    with pytest.raises(RuntimeError):
        await delivery.deliver_order(session, order.id)
    boom["on"] = False
    assert await delivery.deliver_order(session, order.id) == "sent"
    assert len(tg["photo"]) == 1


async def test_html_in_values_is_escaped_and_xss_like_names_are_safe(session, tg):
    order = await _seed(session, link="https://s.example/sub/<b>x&y")
    await delivery.deliver_order(session, order.id)
    cap = tg["photo"][0]["caption"]
    assert "<b>x&y" not in cap and "&lt;b&gt;x&amp;y" in cap


async def test_test_account_has_no_balance_line(session, tg):
    order = await _seed(session, total=0, kind="test")
    await delivery.deliver_order(session, order.id)
    assert "موجودی کیف پول" not in tg["photo"][0]["caption"]


async def test_user_without_telegram_is_skipped_silently(session, tg):
    order = await _seed(session, with_telegram=False)
    assert await delivery.deliver_order(session, order.id) == "skipped"
    assert tg["photo"] == [] and tg["message"] == []


async def test_overlong_link_never_exceeds_caption_limit(session, tg):
    order = await _seed(session, link="https://s.example/sub/" + "a" * 1200)
    await delivery.deliver_order(session, order.id)
    assert len(tg["photo"][0]["caption"]) <= delivery.CAPTION_LIMIT
    assert len(tg["message"]) == 1  # full link follows as text


async def test_provisioning_emits_delivery_event_not_generic_notice():
    import inspect
    from melorin.modules.vpn import service
    src = inspect.getsource(service.provision_order)
    assert src.count("events.ORDER_DELIVERY") == 2          # normal path + reconcile path
    assert "notify:account" not in src
