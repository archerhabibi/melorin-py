"""T04: the one resolver behind worker._notify and order delivery (Telegram identity + bot token -> channel + chat id)."""

import types
import uuid

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import melorin.models  # noqa: F401  (registers every table)
from melorin.core.db import Base
from melorin.kernel.models.identity import Identity, User
from melorin.modules.notifications.dispatch import telegram_target


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


class FakeChannel:
    def __init__(self, token, base_url, kind):
        self.token, self.base_url, self.kind = token, base_url, kind


@pytest.fixture(autouse=True)
def _fake_channel(monkeypatch):
    monkeypatch.setattr("melorin.channels.telegram.TelegramChannel", FakeChannel)


def _settings(token="MAIN"):
    return types.SimpleNamespace(main_bot_token=token, store_web_url="https://shop")


async def test_returns_main_channel_and_chat_id(session):
    u = User(id=uuid.uuid4(), display_name="u")
    session.add_all([u, Identity(user_id=u.id, provider="telegram", subject="555")])
    await session.flush()
    channel, chat_id = await telegram_target(session, u.id, None, _settings())
    assert (channel.token, channel.kind, chat_id) == ("MAIN", "main", "555")


async def test_skipped_without_identity_or_token(session):
    u = User(id=uuid.uuid4(), display_name="u")
    session.add(u)
    await session.flush()
    assert await telegram_target(session, u.id, None, _settings()) is None  # no Telegram identity
    session.add(Identity(user_id=u.id, provider="telegram", subject="555"))
    await session.flush()
    assert await telegram_target(session, u.id, None, _settings(token="")) is None  # no bot token anywhere
