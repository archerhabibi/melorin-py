"""HTTP flow of wallet consolidation: user requests, admin approves, ledger moves the money exactly once (docs/25)."""

from __future__ import annotations

import pytest
import uuid

from sqlalchemy import select

from _db import make_user
from _http import add_user, api_client
from melorin.core.security import create_access_token
from melorin.domain.account_linking import Evidence
from melorin.kernel.models.person import WalletTransfer
from melorin.modules.identity.account_linking import linking
from melorin.modules.wallet import service as wallets


@pytest.fixture(autouse=True)
def _manual_consolidation(monkeypatch):
    """These tests exercise the manual-approval path (the exception path); automatic mode is the default and is tested separately."""
    from melorin.core.config import get_settings

    monkeypatch.setattr(get_settings(), "identity_consolidation_auto_approve", False)


ID = "/api/v1/identity"
ADMIN = "/api/v1/admin/identity"


def _err(r):
    body = r.json()
    return body.get("error", body).get("code") if isinstance(body, dict) else None


async def _linked_pair(maker, main, *, balance_b=500):
    """Two accounts of one person; the second holds ``balance_b`` in the main store."""
    async with maker() as s:
        a, b = await make_user(s), await make_user(s)
        await linking.attach_identity(s, a, "google", "ga", evidence=Evidence.OAUTH_GOOGLE)
        await linking.attach_identity(s, b, "google", "gb", evidence=Evidence.OAUTH_GOOGLE)
        err = None
        try:
            await linking.attach_identity(s, a, "google", "gb", evidence=Evidence.OAUTH_GOOGLE)
        except Exception as e:  # IDENTITY_IN_USE carries the operation to confirm
            err = e
        await linking.confirm_person_link(s, a, uuid.UUID(err.details["operation_id"]))
        wb = await wallets.get_wallet(s, b.id, main.id)
        if balance_b:
            pay = [wallets.Posting(balance_b, wallet=wb), wallets.Posting(-balance_b, account="gateway:x:clearing", min_balance=None)]
            await wallets.post(s, kind="topup", key=f"t-{uuid.uuid4().hex}", currency="IRT", postings=pay)
        await s.commit()
        return a, b, wb.id


def _user_headers(user, main):
    token, _ = create_access_token(user.id, False, store_id=main.id, channel="site")
    return {"Authorization": f"Bearer {token}"}


async def test_user_requests_admin_approves_and_money_moves_once():
    async with api_client() as (c, maker, main):
        a, _b, _wb_id = await _linked_pair(maker, main)
        admin = await add_user(maker, email="root@example.com", admin=True, totp=True)
        h = _user_headers(a, main)
        r = await c.post(f"{ID}/consolidation", json={"idempotency_key": "key-0001-http"}, headers=h)
        assert r.status_code == 200, r.text
        card = r.json()
        assert card["status"] == "pending_approval"
        again = await c.post(f"{ID}/consolidation", json={"idempotency_key": "key-0001-http"}, headers=h)
        assert again.json()["id"] == card["id"]
        # nothing moved before approval
        async with maker() as s:
            assert (await wallets.get_wallet(s, a.id, main.id)).balance == 0
        # a customer cannot approve their own consolidation
        r = await c.post(f"{ADMIN}/consolidations/{card['id']}/approve", json={"reason": "self"}, headers=h)
        assert r.status_code in (401, 403)
        token, _ = create_access_token(admin.id, True)
        ah = {"Authorization": f"Bearer {token}"}
        r = await c.post(f"{ADMIN}/consolidations/{card['id']}/approve", json={"reason": "verified owner"}, headers=ah)
        assert r.status_code == 200, r.text
        assert r.json()["status"] == "completed"
        r = await c.post(f"{ADMIN}/consolidations/{card['id']}/approve", json={"reason": "replay"}, headers=ah)
        assert r.status_code == 200 and r.json()["status"] == "completed"
        async with maker() as s:
            assert (await wallets.get_wallet(s, a.id, main.id, route=False)).balance == 500
            assert (await wallets.get_wallet(s, _b.id, main.id)).balance == 500  # routed to the central wallet
            assert len((await s.scalars(select(WalletTransfer))).all()) == 1
        status = (await c.get(f"{ID}/consolidation-status", headers=h)).json()
        assert status and status[0]["status"] == "completed"


async def test_single_account_has_nothing_to_consolidate():
    async with api_client() as (c, maker, main):
        async with maker() as s:
            solo = await make_user(s)
            await s.commit()
        r = await c.post(f"{ID}/consolidation", json={"idempotency_key": "key-0002-http"}, headers=_user_headers(solo, main))
        assert r.status_code == 409 and _err(r) == "NOTHING_TO_CONSOLIDATE"


async def test_idempotency_key_shape_is_validated():
    async with api_client() as (c, maker, main):
        a, _b, _ = await _linked_pair(maker, main, balance_b=0)
        r = await c.post(f"{ID}/consolidation", json={"idempotency_key": "short"}, headers=_user_headers(a, main))
        assert r.status_code == 422
