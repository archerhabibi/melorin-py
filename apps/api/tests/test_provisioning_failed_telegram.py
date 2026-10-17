"""Telegram alert to super admins when provisioning fails (worker side), on a real SQLite DB."""

import types
import uuid

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import melorin.models  # noqa: F401  (registers every table)
from melorin.core.db import Base
from melorin.modules.identity.models import Identity, User
from melorin.modules.notifications.models import Notification
from melorin.modules.orders.models import Order
from melorin.worker import runner


@pytest.fixture
async def session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    # Tables one by one: one pre-existing model declares a duplicate index that breaks create_all on SQLite.
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
def sent(monkeypatch):
    messages: list[tuple[str, str]] = []

    class FakeChannel:
        def __init__(self, *_a, **_k):
            pass

        async def send_message(self, chat_id, text, **_k):
            messages.append((str(chat_id), text))

    monkeypatch.setattr("melorin.channels.telegram.TelegramChannel", FakeChannel)
    monkeypatch.setattr(runner, "get_settings", lambda: types.SimpleNamespace(main_bot_token="tok", store_web_url="http://x"))
    return messages


def _user(s, *, admin: bool, active: bool = True, chat_id: str | None = None):
    u = User(id=uuid.uuid4(), display_name="u", is_super_admin=admin, is_active=active)
    s.add(u)
    if chat_id:
        s.add(Identity(user_id=u.id, provider="telegram", subject=chat_id))
    return u


def _order(s, *, number: str, status: str):
    o = Order(
        number=number,
        user_id=uuid.uuid4(),
        store_id=uuid.uuid4(),
        product_id=uuid.uuid4(),
        status=status,
        payment_method="wallet",
        currency="IRT",
        unit_price=1,
        total=1,
        pricing_snapshot={},
        product_snapshot={},
    )
    s.add(o)
    return o


async def test_only_active_super_admins_with_telegram_get_the_alert(session, sent):
    _user(session, admin=True, chat_id="111")
    _user(session, admin=True, active=False, chat_id="222")  # inactive admin
    _user(session, admin=False, chat_id="333")  # customer
    _user(session, admin=True)  # admin without telegram -> skipped, no error
    order = _order(session, number="AB23CD", status="refunded")
    await session.commit()

    await runner._notify_admins_provisioning_failed(session, {"order_id": order.id, "error": "panel down"})
    await session.commit()

    assert [chat for chat, _ in sent] == ["111"]
    text = sent[0][1]
    assert "AB23CD" in text and "panel down" in text and "برگشت داده شد" in text


async def test_retry_does_not_resend_to_admins_already_notified(session, sent):
    _user(session, admin=True, chat_id="111")
    order = _order(session, number="ZZ99YY", status="refunded")
    await session.commit()
    payload = {"order_id": order.id, "error": "x"}

    await runner._notify_admins_provisioning_failed(session, payload)
    await session.commit()
    await runner._notify_admins_provisioning_failed(session, payload)
    await session.commit()

    assert len(sent) == 1
    from sqlalchemy import select

    rows = (await session.scalars(select(Notification))).all()
    assert len(rows) == 1 and rows[0].telegram_status == "sent"


async def test_message_says_manual_check_when_auto_refund_did_not_happen(session, sent):
    _user(session, admin=True, chat_id="111")
    order = _order(session, number="KK55MM", status="provisioning_failed")
    await session.commit()

    await runner._notify_admins_provisioning_failed(session, {"order_id": order.id, "error": "boom"})

    assert len(sent) == 1
    assert "دستی" in sent[0][1] and "برگشت داده شد" not in sent[0][1]
