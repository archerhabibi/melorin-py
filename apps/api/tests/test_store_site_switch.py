"""Reseller stores are created with the website OFF and the bot ON; the Main Store keeps both; the site channel obeys the switch."""

import types

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import melorin.models  # noqa: F401
from melorin.core import channel
from melorin.core.db import Base
from melorin.core.errors import AppError
from melorin.kernel.models.stores import Store
from melorin.modules.catalog.router import store_by_domain, store_by_slug, tls_ask


@pytest.fixture
async def session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    for table in Base.metadata.sorted_tables:
        try:
            async with engine.begin() as conn:
                await conn.run_sync(lambda c, t=table: t.create(c, checkfirst=True))
        except Exception:
            pass
    async with async_sessionmaker(engine, expire_on_commit=False)() as s:
        yield s
    await engine.dispose()


def _req(host):
    return types.SimpleNamespace(client=types.SimpleNamespace(host="203.0.113.9"), headers={"host": host})


async def _stores(session, site_enabled):
    main = Store(kind="main", name="Main", slug="main", currency="IRT", domain="main.example.com")
    session.add(main)
    await session.flush()
    rs = Store(kind="reseller", name="R", slug="r", domain="r.example.com", parent_store_id=main.id, site_enabled=site_enabled)
    session.add(rs)
    await session.flush()
    return main, rs


async def test_main_store_has_both_channels_on_by_default(session):
    main, _ = await _stores(session, False)
    assert main.site_enabled is True and main.bot_enabled is True


async def test_reseller_site_off_is_refused_but_main_site_is_served(session):
    await _stores(session, False)
    with pytest.raises(AppError) as exc:
        await channel.site_channel(session, _req("r.example.com"))
    assert exc.value.code == "CHANNEL_DISABLED"
    ch = await channel.site_channel(session, _req("main.example.com"))
    assert ch.store_kind == "main"


async def test_reseller_site_on_is_served(session):
    _, rs = await _stores(session, True)
    ch = await channel.site_channel(session, _req("r.example.com"))
    assert ch.store_id == rs.id


async def test_site_off_does_not_stop_the_bot(session):
    _, rs = await _stores(session, False)
    ch = await channel.bot_channel(session, channel.BotService("any"), rs.id)
    assert ch.kind == "bot" and ch.store_id == rs.id


async def test_public_lookup_and_tls_gate_follow_the_switch(session):
    _, rs = await _stores(session, False)
    with pytest.raises(Exception):
        await store_by_domain("r.example.com", session)
    with pytest.raises(Exception):
        await store_by_slug("r", session)
    with pytest.raises(Exception):
        await tls_ask("r.example.com", session)
    rs.site_enabled = True
    await session.flush()
    assert (await tls_ask("r.example.com", session))["ok"] is True
    assert (await store_by_slug("r", session)).slug == "r"


async def test_main_store_is_never_hidden_by_the_switch(session):
    main, _ = await _stores(session, False)
    main.site_enabled = False  # ignored for the Main Store
    await session.flush()
    assert (await store_by_domain("main.example.com", session)).slug == "main"
    assert (await tls_ask("main.example.com", session))["ok"] is True
