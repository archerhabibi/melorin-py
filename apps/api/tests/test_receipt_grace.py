"""Time-boxed manual review: a receipt nobody reviewed within N minutes is credited provisionally, then confirmed or revoked."""

from __future__ import annotations

import datetime as dt
import uuid

import pytest
from sqlalchemy import select

from _http import PASSWORD, add_user, api_client, totp_now
from melorin.core.db import utcnow
from melorin.domain import bank_sms as dom
from melorin.kernel.models.payments import Payment
from melorin.kernel.models.stores import Store, StorePaymentConfiguration
from melorin.modules.payments import provisional
from test_bank_sms_auto_verify import ADMIN, _balance, _login, _minute, _setup_source, _sms, _topup, sms_text  # noqa: F401


@pytest.fixture(autouse=True)
def _storage(tmp_path, monkeypatch):
    from melorin.core import storage

    monkeypatch.setattr(storage, "_storage", storage.LocalStorage(str(tmp_path)))


async def _topup_unique(c, h, sid, *, key, n):
    """Like ``_topup`` but every call uploads a different image (identical bytes are blocked as a replay)."""
    pid = await _topup(c, h, sid, key=key, receipt=False)
    img = b"\x89PNG\r\n\x1a\n" + str(n).encode() * 16
    r = await c.post(f"/api/v1/stores/{sid}/payments/{pid}/receipt", files={"file": ("r.png", img, "image/png")}, headers=h)
    assert r.status_code == 200, r.text
    return pid


async def _card(maker, main):
    async with maker() as s:
        s.add(
            StorePaymentConfiguration(
                store_id=main.id,
                provider="manual_card",
                is_enabled=True,
                public_config={"card_number": "6037997000000000", "holder": "Test"},
            )
        )
        await s.commit()


async def _admin(c, maker):
    await add_user(maker, email="root@example.com", admin=True, totp=True)
    r = await c.post("/api/v1/auth/password/login", json={"email": "root@example.com", "password": PASSWORD, "totp_code": totp_now()})
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


async def _enable(c, admin, store_id, **kw):
    r = await c.put(f"{ADMIN}/stores/{store_id}/receipt-review/settings", json={"enabled": True, **kw}, headers=admin)
    assert r.status_code == 200, r.text
    return r.json()


async def _sweep(maker, minutes_later):
    async with maker() as s:
        total = 0
        for sid in (await s.scalars(select(Store.id))).all():
            total += (await provisional.run_store(s, await s.get(Store, sid), now=utcnow() + dt.timedelta(minutes=minutes_later)))[
                "credited"
            ]
        return total


async def test_default_is_off_and_nothing_is_credited_without_a_human():
    async with api_client() as (c, maker, main):
        h, sid = await _login(c, maker)
        await _card(maker, main)
        await _topup(c, h, sid)
        assert await _sweep(maker, 30) == 0 and await _balance(maker, sid) == 0


async def test_unreviewed_receipt_is_credited_after_the_grace_and_not_a_minute_earlier():
    async with api_client() as (c, maker, main):
        h, sid = await _login(c, maker)
        await _card(maker, main)
        admin = await _admin(c, maker)
        assert (await _enable(c, admin, main.id))["minutes"] == 5
        pid = await _topup(c, h, sid)
        assert await _sweep(maker, 4) == 0 and await _balance(maker, sid) == 0
        q = (await c.get(f"{ADMIN}/stores/{main.id}/receipt-review", headers=admin)).json()
        assert [w["payment_id"] for w in q["waiting"]] == [pid] and q["waiting"][0]["auto_approve_at"]
        assert await _sweep(maker, 6) == 1 and await _balance(maker, sid) == 150_000
        assert await _sweep(maker, 7) == 0  # idempotent: never credits twice
        assert await _balance(maker, sid) == 150_000
        q = (await c.get(f"{ADMIN}/stores/{main.id}/receipt-review", headers=admin)).json()
        assert [x["payment_id"] for x in q["provisional"]] == [pid] and q["waiting"] == [] and q["exposure_rial"] == 1_500_000


async def test_admin_confirm_keeps_the_credit_and_revoke_reverses_it():
    async with api_client() as (c, maker, main):
        h, sid = await _login(c, maker)
        await _card(maker, main)
        admin = await _admin(c, maker)
        await _enable(c, admin, main.id)
        keep = await _topup(c, h, sid, key="grace-key-k1")
        assert await _sweep(maker, 6) == 1
        r = await c.post(f"{ADMIN}/stores/{main.id}/receipt-review/{keep}", json={"approve": True}, headers=admin)
        assert r.json()["provisional"]["state"] == "confirmed" and await _balance(maker, sid) == 150_000
        # a second customer top-up: revoked through the plain review route (same decision, other door)
        gone = await _topup_unique(c, h, sid, key="grace-key-k2", n=2)
        assert await _sweep(maker, 12) == 1 and await _balance(maker, sid) == 300_000
        r = await c.post(f"{ADMIN}/payments/{gone}/review", json={"approve": False, "reason": "fake receipt"}, headers=admin)
        assert r.status_code == 200 and r.json()["status"] == "failed"
        assert await _balance(maker, sid) == 150_000
        again = await c.post(f"{ADMIN}/stores/{main.id}/receipt-review/{gone}", json={"approve": False}, headers=admin)
        assert again.status_code == 200 and await _balance(maker, sid) == 150_000  # repeated click: no double reversal


async def test_guards_block_amount_cap_exposure_and_revoked_customers():
    async with api_client() as (c, maker, main):
        h, sid = await _login(c, maker)
        await _card(maker, main)
        admin = await _admin(c, maker)
        await _enable(c, admin, main.id, max_amount_rial=1_000_000)  # 150,000 IRT = 1,500,000 IRR is over the cap
        pid = await _topup(c, h, sid)
        assert await _sweep(maker, 10) == 0 and await _balance(maker, sid) == 0
        q = (await c.get(f"{ADMIN}/stores/{main.id}/receipt-review", headers=admin)).json()
        assert q["waiting"][0]["block"] == "over_amount_cap"
        await _enable(c, admin, main.id, max_amount_rial=5_000_000)
        async with maker() as s:  # the blocked marker is informational: raising the cap releases it
            p = await s.get(Payment, uuid.UUID(pid))
            p.meta = {**p.meta, "provisional": None}
            await s.commit()
        assert await _sweep(maker, 10) == 1
        await c.post(f"{ADMIN}/stores/{main.id}/receipt-review/{pid}", json={"approve": False}, headers=admin)
        again = await _topup(c, h, sid, key="grace-key-k9")
        assert await _sweep(maker, 40) == 0  # a customer whose provisional credit was revoked waits for a human from now on
        q = (await c.get(f"{ADMIN}/stores/{main.id}/receipt-review", headers=admin)).json()
        assert q["waiting"][0]["payment_id"] == again and q["waiting"][0]["block"] == "user_revoked_before"


async def test_the_same_receipt_image_is_never_credited_twice():
    async with api_client() as (c, maker, main):
        h, sid = await _login(c, maker)
        await _card(maker, main)
        admin = await _admin(c, maker)
        await _enable(c, admin, main.id, max_open_per_user=5)
        await _topup(c, h, sid, key="grace-key-a")
        await _topup(c, h, sid, key="grace-key-b")  # identical PNG bytes: same sha256
        assert await _sweep(maker, 10) == 0  # both share one image -> neither is auto-credited
        q = (await c.get(f"{ADMIN}/stores/{main.id}/receipt-review", headers=admin)).json()
        assert {w["block"] for w in q["waiting"]} == {"duplicate_image"}


async def test_a_late_bank_sms_makes_the_provisional_credit_final():
    async with api_client() as (c, maker, main):
        h, sid = await _login(c, maker)
        admin = await _admin(c, maker)
        token = await _setup_source(maker, main.id)
        await _enable(c, admin, main.id)
        when = _minute()
        pid = await _topup(c, h, sid, paid_at=dom.utc_to_jalali_text(when))
        assert await _sweep(maker, 6) == 1
        r = await _sms(c, main.id, token, sms_text(when=when))
        assert r.status_code == 200 and r.json()["status"] == "matched"
        q = (await c.get(f"{ADMIN}/stores/{main.id}/receipt-review", headers=admin)).json()
        assert q["provisional"] == [] and q["recent"][0]["payment_id"] == pid and q["recent"][0]["resolved_by"] == "bank_sms"
        assert await _balance(maker, sid) == 150_000


async def test_settings_are_validated():
    async with api_client() as (c, maker, main):
        admin = await _admin(c, maker)
        for bad in ({"minutes": 0}, {"minutes": 61}, {"max_amount_rial": -1}, {"enabled": "yes"}):
            r = await c.put(f"{ADMIN}/stores/{main.id}/receipt-review/settings", json=bad, headers=admin)
            assert r.status_code == 422, (bad, r.text)
