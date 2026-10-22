"""Phase 4: in-process HTTP harness. Drives the REAL FastAPI app (routing, validation, error envelope, cookies,
dependencies) through ``httpx.ASGITransport`` against the per-test schema from ``_db`` (SQLite by default, PostgreSQL
with ``TEST_PG_URL``). No network, no Redis: the rate limiter uses its documented process-local fallback."""

from __future__ import annotations

import sys
import time
from contextlib import asynccontextmanager

import httpx
from sqlalchemy.ext.asyncio import async_sessionmaker

from _db import make_store, open_schema_engine
from melorin.app import app
from melorin.core import ratelimit
from melorin.core import db as core_db
from melorin.core.db import get_session
from melorin.core.security import _totp, hash_password
from melorin.kernel.models.identity import User

PASSWORD = "correct-horse-battery-staple"
TOTP_SECRET = "JBSWY3DPEHPK3PXP"


@asynccontextmanager
async def api_client(*, with_main_store: bool = True):
    """Yield ``(client, maker, main_store)``; every request gets its own session on the throw-away schema."""
    ratelimit._mem.clear()
    async with open_schema_engine() as engine:
        maker = async_sessionmaker(engine, expire_on_commit=False)

        async def override():
            async with maker() as session:
                try:
                    yield session
                finally:
                    if session.in_transaction():
                        await session.rollback()

        app.dependency_overrides[get_session] = override
        # Some helpers (e-mail settings, rate limits ...) open their own session via ``session_factory()`` instead of the
        # request one: point every module that imported it at the test schema, then restore.
        # Hermetic rate limiting: never share counters through an ambient Redis between tests (documented local fallback).
        real_get_redis, ratelimit.get_redis = ratelimit.get_redis, lambda: None
        original = core_db.session_factory
        patched = [
            (m, n)
            for m in list(sys.modules.values())
            if getattr(m, "__name__", "").startswith("melorin")
            for n in ("session_factory",)
            if getattr(m, n, None) is original
        ]
        for m, n in patched:
            setattr(m, n, lambda: maker)
        main = None
        if with_main_store:
            async with maker() as s:
                main = await make_store(s, kind="main")
                await s.commit()
        try:
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
                yield client, maker, main
        finally:
            app.dependency_overrides.pop(get_session, None)
            for m, n in patched:
                setattr(m, n, original)
            ratelimit.get_redis = real_get_redis
            ratelimit._mem.clear()


async def add_user(maker, *, email="user@example.com", password=PASSWORD, admin=False, totp=False, active=True) -> User:
    from melorin.core.crypto import encrypt

    async with maker() as s:
        user = User(
            email=email,
            display_name=email.split("@")[0],
            password_hash=await hash_password(password) if password else None,
            is_super_admin=admin,
            is_active=active,
            totp_enabled=totp,
            totp_secret_enc=encrypt(TOTP_SECRET) if totp else None,
        )
        s.add(user)
        await s.commit()
        return user


def totp_now(step_offset: int = 0) -> str:
    return _totp(TOTP_SECRET, int(time.time()) // 30 + step_offset)
