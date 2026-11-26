"""The admin's bot DM (worker side of ``admin.alert``), on a real SQLite DB.

Only panel/node failures and customers' payments are DM kinds (``domain.messaging_policy``); the worker re-checks the policy, so a
payload of any other kind is dropped instead of messaging the admin.
"""

import types
import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import melorin.models  # noqa: F401  (registers every table)
from melorin.core.db import Base
from melorin.domain.notification_dedup import EVENT_ID_FIELD
from melorin.kernel.models.identity import Identity, User
from melorin.kernel.models.notifications import Notification
from melorin.worker import runner

PANEL_TEXT = "🔴 پنل «Panel-A» ناسالم شد\nخطا: timeout"


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


def _alert(kind="panel_unhealthy", text=PANEL_TEXT, event_id=None):
    return {"kind": kind, "text": text, EVENT_ID_FIELD: event_id or str(uuid.uuid4())}


async def test_only_active_super_admins_with_telegram_get_the_dm(session, sent):
    _user(session, admin=True, chat_id="111")
    _user(session, admin=True, active=False, chat_id="222")  # inactive admin
    _user(session, admin=False, chat_id="333")  # customer
    _user(session, admin=True)  # admin without telegram -> skipped, no error
    await session.commit()

    await runner._notify_admins(session, _alert())
    await session.commit()

    assert sent == [("111", PANEL_TEXT)]  # first line is the title, the rest the body: the text arrives unchanged


async def test_an_outbox_retry_does_not_resend_to_admins_already_notified(session, sent):
    _user(session, admin=True, chat_id="111")
    await session.commit()
    payload = _alert("payment_succeeded", "💳 پرداخت موفق\nمبلغ: 1,000 تومان")

    await runner._notify_admins(session, payload)
    await session.commit()
    await runner._notify_admins(session, payload)  # same event id: the retry
    await session.commit()

    assert len(sent) == 1
    rows = (await session.scalars(select(Notification))).all()
    assert len(rows) == 1 and rows[0].telegram_status == "sent" and rows[0].kind == "payment_succeeded"


async def test_a_different_event_is_a_new_dm(session, sent):
    _user(session, admin=True, chat_id="111")
    await session.commit()
    await runner._notify_admins(session, _alert())
    await runner._notify_admins(session, _alert())
    await session.commit()
    assert len(sent) == 2


@pytest.mark.parametrize(
    "kind",
    [
        "provisioning_failed",
        "panel_recovered",
        "node_recovered",
        "backup_failed",
        "outbox_failure",
        "admin_reseller_application",
        "payment_failed",
        "nope",
        "",
    ],
)
async def test_a_kind_outside_the_dm_set_never_messages_the_admin(session, sent, kind):
    _user(session, admin=True, chat_id="111")
    await session.commit()

    await runner._notify_admins(session, _alert(kind, "x\ny"))
    await session.commit()

    assert sent == []
    assert (await session.scalars(select(Notification))).all() == []
