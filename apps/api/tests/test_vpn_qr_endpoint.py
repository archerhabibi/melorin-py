"""GET /stores/{store_id}/vpn-accounts/{id}/qr.png: PNG of the subscription link, only for its owner IN THAT STORE."""

import types
import uuid

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import melorin.models  # noqa: F401  (registers every table)
from melorin.core.db import Base
from melorin.core.errors import AppError
from melorin.modules.vpn import router as vpn_router
from melorin.modules.vpn.models import VpnAccount

SUB = "https://sub.example.com/sub/AbCdEf123"


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


STORE = uuid.uuid4()


def _ctx(user_id, store_id=STORE):
    return types.SimpleNamespace(user=types.SimpleNamespace(id=user_id), store=types.SimpleNamespace(id=store_id))


async def _account(s, owner, link=SUB):
    a = VpnAccount(
        username=f"m_{uuid.uuid4().hex[:8]}",
        user_id=owner,
        store_id=STORE,
        order_id=uuid.uuid4(),
        product_id=uuid.uuid4(),
        status="active",
        subscription_url=link,
    )
    s.add(a)
    await s.commit()
    return a


async def test_owner_gets_png(session):
    uid = uuid.uuid4()
    a = await _account(session, uid)
    r = await vpn_router.qr(a.id, _ctx(uid), session)
    assert r.media_type == "image/png" and r.body[:4] == b"\x89PNG"
    assert r.headers["cache-control"] == "private, no-store"


async def test_other_user_and_missing_link_are_404(session):
    uid = uuid.uuid4()
    a = await _account(session, uid)
    with pytest.raises(AppError):
        await vpn_router.qr(a.id, _ctx(uuid.uuid4()), session)
    b = await _account(session, uid, link=None)
    with pytest.raises(AppError):
        await vpn_router.qr(b.id, _ctx(uid), session)


async def test_same_owner_in_another_store_gets_404(session):
    uid = uuid.uuid4()
    a = await _account(session, uid)
    with pytest.raises(AppError):
        await vpn_router.qr(a.id, _ctx(uid, store_id=uuid.uuid4()), session)
