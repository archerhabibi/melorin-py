"""Password proofs and account changes must serialize on the real PostgreSQL user row lock."""

import asyncio

import pytest
from sqlalchemy import select, text, update
from sqlalchemy.exc import DBAPIError

from _db import pg_url
from _http import PASSWORD, add_user, api_client
from test_identity_account_http import _admin_login
from test_identity_linking_http import _auth, _two_google
from melorin.core import security
from melorin.kernel.models.identity import User
from melorin.modules.identity.account_linking import linking
from melorin.modules.identity.routes import account

pytestmark = [pytest.mark.concurrency, pytest.mark.skipif(pg_url() is None, reason="PostgreSQL lane: set TEST_PG_URL")]


async def test_simultaneous_admin_password_changes_accept_only_one_old_password(monkeypatch):
    async with api_client() as (client, maker, _):
        headers = await _admin_login(client, maker)
        barrier = asyncio.Barrier(2)
        verify = account.verify_password

        async def verify_together(password, stored):
            valid = await verify(password, stored)
            await asyncio.wait_for(barrier.wait(), timeout=15)
            return valid

        monkeypatch.setattr(account, "verify_password", verify_together)
        new_passwords = ("another-strong-pass-1", "another-strong-pass-2")
        responses = await asyncio.wait_for(
            asyncio.gather(
                *(
                    client.post(
                        "/api/v1/auth/admin/password",
                        json={"current_password": PASSWORD, "new_password": password},
                        headers=headers,
                    )
                    for password in new_passwords
                )
            ),
            timeout=45,
        )
        assert sorted(response.status_code for response in responses) == [200, 401]
        winner = new_passwords[next(i for i, response in enumerate(responses) if response.status_code == 200)]
        async with maker() as session:
            admin = await session.scalar(select(User).where(User.email == "root@example.com"))
            assert await security.verify_password(winner, admin.password_hash)


async def test_unlink_holds_verified_password_lock_until_commit(monkeypatch):
    async with api_client() as (client, maker, main):
        user = await add_user(maker, email="pw@example.com")
        identity, _other = await _two_google(maker, user)
        replacement_hash = await security.hash_password("owner-rotated-pass-2")
        locked, release = asyncio.Event(), asyncio.Event()
        unlink = linking.unlink_identity

        async def pause_before_unlink(session, current, identity_id):
            locked.set()
            await asyncio.wait_for(release.wait(), timeout=30)
            return await unlink(session, current, identity_id)

        monkeypatch.setattr(linking, "unlink_identity", pause_before_unlink)
        request = asyncio.create_task(
            client.post(
                "/api/v1/identity/unlink",
                json={"identity_id": str(identity.id), "current_password": PASSWORD},
                headers=_auth(user, main),
            )
        )
        try:
            await asyncio.wait_for(locked.wait(), timeout=15)
            async with maker() as session:
                await session.execute(text("SET LOCAL lock_timeout = '500ms'"))
                with pytest.raises(DBAPIError) as exc:
                    await session.execute(update(User).where(User.id == user.id).values(password_hash=replacement_hash))
                assert exc.value.orig.sqlstate == "55P03"
                await session.rollback()
        finally:
            release.set()
            response = await asyncio.wait_for(request, timeout=30)
        assert response.status_code == 200, response.text
        async with maker() as session:
            await session.execute(update(User).where(User.id == user.id).values(password_hash=replacement_hash))
            await session.commit()
