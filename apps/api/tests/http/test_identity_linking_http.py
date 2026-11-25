"""HTTP contract of ``/identity`` re-authentication and unlink (docs/25, spec 7.4)."""

from __future__ import annotations

import pytest
from sqlalchemy import select

from _http import PASSWORD, add_user, api_client
from melorin.core import security
from melorin.core.security import create_access_token
from melorin.domain.account_linking import Evidence
from melorin.kernel.models.identity import Identity, User
from melorin.modules.identity.account_linking import linking, reauth

ID = "/api/v1/identity"


def _err(r):
    body = r.json()
    return body.get("error", body).get("code") if isinstance(body, dict) else None


async def _two_google(maker, user):
    async with maker() as s:
        u = await s.merge(user)
        await linking.attach_identity(s, u, "google", "g-one", evidence=Evidence.OAUTH_GOOGLE)
        await linking.attach_identity(s, u, "google", "g-two", evidence=Evidence.OAUTH_GOOGLE)
        await s.commit()
        return (await s.scalars(select(Identity).where(Identity.person_id == u.person_id, Identity.provider == "google"))).all()


def _auth(user, main):
    token, _ = create_access_token(user.id, False, store_id=main.id, channel="site")
    return {"Authorization": f"Bearer {token}"}


async def test_reauth_method_follows_account_type():
    async with api_client() as (c, maker, main):
        pw = await add_user(maker, email="pw@example.com")
        nopw = await add_user(maker, email="nopw@example.com", password=None)
        assert (await c.get(f"{ID}/reauth", headers=_auth(pw, main))).json() == {"method": "password"}
        assert (await c.get(f"{ID}/reauth", headers=_auth(nopw, main))).json() == {"method": "email_code"}
        assert (await c.get(f"{ID}/reauth")).status_code == 401


async def test_unlink_with_password_requires_current_password():
    async with api_client() as (c, maker, main):
        user = await add_user(maker, email="pw@example.com")
        g1, _g2 = await _two_google(maker, user)
        r = await c.post(f"{ID}/unlink", json={"identity_id": str(g1.id)}, headers=_auth(user, main))
        assert r.status_code == 401 and _err(r) == "REAUTH_REQUIRED"
        r = await c.post(f"{ID}/unlink", json={"identity_id": str(g1.id), "current_password": "wrong"}, headers=_auth(user, main))
        assert _err(r) == "REAUTH_REQUIRED"
        r = await c.post(f"{ID}/unlink", json={"identity_id": str(g1.id), "current_password": PASSWORD}, headers=_auth(user, main))
        assert r.status_code == 200 and r.json()["status"] == "revoked"


@pytest.mark.parametrize("change", ["password", "inactive"])
async def test_unlink_rejects_password_proof_if_account_changes_during_verification(monkeypatch, change):
    async with api_client() as (client, maker, main):
        user = await add_user(maker, email="pw@example.com")
        identity, _other = await _two_google(maker, user)
        replacement_hash = await security.hash_password("owner-rotated-pass-2")
        verify = reauth.verify_password

        async def verify_then_change_account(password, stored):
            valid = await verify(password, stored)
            async with maker() as session:
                row = await session.get(User, user.id)
                if change == "password":
                    row.password_hash = replacement_hash
                else:
                    row.is_active = False
                await session.commit()
            return valid

        monkeypatch.setattr(reauth, "verify_password", verify_then_change_account)
        response = await client.post(
            f"{ID}/unlink", json={"identity_id": str(identity.id), "current_password": PASSWORD}, headers=_auth(user, main)
        )
        async with maker() as session:
            assert (await session.get(Identity, identity.id)).status == "active"
        assert (response.status_code, _err(response)) == (401, "REAUTH_REQUIRED")


async def test_passwordless_unlink_needs_a_fresh_email_code_used_once():
    async with api_client() as (c, maker, main):
        user = await add_user(maker, email="nopw@example.com", password=None)
        g1, g2 = await _two_google(maker, user)
        h = _auth(user, main)
        r = await c.post(f"{ID}/unlink", json={"identity_id": str(g1.id)}, headers=h)
        assert r.status_code == 401 and _err(r) == "REAUTH_REQUIRED"
        r = await c.post(f"{ID}/unlink", json={"identity_id": str(g1.id), "reauth_code": "000000"}, headers=h)
        assert _err(r) == "REAUTH_REQUIRED"
        started = await c.post(f"{ID}/reauth/email/start", headers=h)
        assert started.status_code == 200, started.text
        code = started.json()["dev_code"]
        r = await c.post(f"{ID}/unlink", json={"identity_id": str(g1.id), "reauth_code": code}, headers=h)
        assert r.status_code == 200 and r.json()["status"] == "revoked"
        # the code is single use: the next sensitive change needs a new one
        r = await c.post(f"{ID}/unlink", json={"identity_id": str(g2.id), "reauth_code": code}, headers=h)
        assert _err(r) == "REAUTH_REQUIRED"


async def test_reauth_email_start_is_refused_for_password_accounts():
    async with api_client() as (c, maker, main):
        user = await add_user(maker, email="pw@example.com")
        r = await c.post(f"{ID}/reauth/email/start", headers=_auth(user, main))
        assert r.status_code == 400 and _err(r) == "REAUTH_NOT_APPLICABLE"
