"""Time-boxed manual review: a receipt nobody reviewed within N minutes is credited provisionally, then confirmed or revoked."""

from __future__ import annotations

import datetime as dt
import uuid

import pytest
from sqlalchemy import select

from _http import PASSWORD, add_user, api_client, totp_now
from melorin.core.db import utcnow
from melorin.domain import bank_sms as dom
from melorin.kernel.models.payments import BankSmsMessage, Payment
from melorin.kernel.models.stores import Store, StorePaymentConfiguration
from melorin.modules.payments import bank_sms, provisional
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
    r = await c.put(
        f"{ADMIN}/stores/{store_id}/receipt-review/settings", json={"enabled": True, "min_account_age_hours": 0, **kw}, headers=admin
    )
    assert r.status_code == 200, r.text
    return r.json()


async def _prove(s):
    """The grace credit now needs a readable proof signal (audit V-22): give every unproven receipt an OCR-style amount claim."""
    for pay in (await s.scalars(select(Payment))).all():
        meta = dict(pay.meta or {})
        if not (meta.get("receipt_claim") or {}).get("amount_rial") and not (meta.get("receipt_claim") or {}).get("reference"):
            rial = dom.to_rial(pay.amount, pay.currency)
            if rial is not None and pay.receipt_file_id:
                meta["receipt_claim"] = {**(meta.get("receipt_claim") or {}), "amount_rial": rial}
                pay.meta = meta
    await s.commit()


async def _sweep(maker, minutes_later):
    async with maker() as s:
        await _prove(s)
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


async def test_a_candidate_decided_by_a_human_meanwhile_is_not_credited_provisionally():
    async with api_client() as (c, maker, main):
        h, sid = await _login(c, maker)
        await _card(maker, main)
        admin = await _admin(c, maker)
        await _enable(c, admin, main.id)
        pid = await _topup(c, h, sid, key="grace-key-s1")
        async with maker() as stale:
            cfg = await provisional.get_config(stale, main.id)
            candidate = await stale.get(Payment, uuid.UUID(pid))  # read by the sweep before the human decided
            r = await c.post(f"{ADMIN}/payments/{pid}/review", json={"approve": False, "reason": "fake receipt"}, headers=admin)
            assert r.status_code == 200 and r.json()["status"] == "failed"
            assert await provisional._approve(stale, candidate, cfg) is False  # no false credit, no false notification
        assert await _balance(maker, sid) == 0
        async with maker() as s:
            p = await s.get(Payment, uuid.UUID(pid))
            assert (p.meta.get("provisional") or {}).get("state") != "open"


async def test_one_failing_payment_does_not_stop_the_rest_of_the_sweep(monkeypatch):
    async with api_client() as (c, maker, main):
        h, sid = await _login(c, maker)
        await _card(maker, main)
        admin = await _admin(c, maker)
        await _enable(c, admin, main.id, max_open_per_user=5)
        first = await _topup_unique(c, h, sid, key="grace-key-f1", n=1)
        await _topup_unique(c, h, sid, key="grace-key-f2", n=2)
        real = provisional._approve

        async def flaky(session, p, cfg):
            if str(p.id) == first:
                raise RuntimeError("boom")
            return await real(session, p, cfg)

        monkeypatch.setattr(provisional, "_approve", flaky)
        async with maker() as s:
            await _prove(s)
            out = await provisional.run_store(s, await s.get(Store, main.id), now=utcnow() + dt.timedelta(minutes=10))
        assert out["credited"] == 1 and out["failed"] == 1
        assert await _balance(maker, sid) == 150_000


async def test_site_upload_stores_a_keyed_network_tag_not_the_address():
    async with api_client() as (c, maker, main):
        h, sid = await _login(c, maker)
        await _card(maker, main)
        pid = await _topup(c, h, sid)
        async with maker() as s:
            p = await s.get(Payment, uuid.UUID(pid))
            tag = (p.meta or {}).get("receipt_origin")
        assert tag and len(tag) == 20 and "." not in tag and ":" not in tag


async def _claimed_pending(c, h, sid, *, key, n, paid_at):
    pid = await _topup(c, h, sid, key=key, receipt=False)
    image = b"\x89PNG\r\n\x1a\n" + str(n).encode() * 24
    response = await c.post(
        f"/api/v1/stores/{sid}/payments/{pid}/receipt",
        files={"file": ("r.png", image, "image/png")},
        data={"paid_at": paid_at},
        headers=h,
    )
    assert response.status_code == 200, response.text
    return pid


@pytest.mark.parametrize("pending_count", [1, 2])
async def test_sms_with_equally_matching_pending_and_provisional_receipts_is_ambiguous(pending_count):
    async with api_client() as (c, maker, main):
        h, sid = await _login(c, maker, "provisional@example.com")
        admin = await _admin(c, maker)
        token = await _setup_source(maker, main.id)
        await _enable(c, admin, main.id)
        when = _minute()
        stamp = dom.utc_to_jalali_text(when)
        provisional_id = await _topup(c, h, sid, key="sms-provisional", paid_at=stamp)
        assert await _sweep(maker, 6) == 1
        pending_ids = []
        for i in range(pending_count):
            other, _ = await _login(c, maker, f"pending{i}@example.com")
            pending_ids.append(await _claimed_pending(c, other, sid, key=f"sms-pending-{i}", n=i + 10, paid_at=stamp))
        response = await _sms(c, main.id, token, sms_text(when=when))
        assert response.json()["status"] == "ambiguous"
        async with maker() as session:
            original = await session.get(Payment, uuid.UUID(provisional_id))
            assert original.meta["provisional"]["state"] == "open"
            for pid in pending_ids:
                assert (await session.get(Payment, uuid.UUID(pid))).status == "awaiting_review"
        # A human can resolve the ambiguity in favor of the provisional receipt without reusing the SMS.
        async with maker() as session:
            sms = await session.scalar(select(BankSmsMessage))
            store = await session.get(Store, main.id)
            linked = await bank_sms.manual_link(session, store, sms.id, uuid.UUID(provisional_id), actor_id=None, actor_type="admin")
            assert linked.status == "matched" and str(linked.payment_id) == provisional_id
            assert (await session.get(Payment, uuid.UUID(provisional_id))).meta["provisional"]["state"] == "confirmed"
            assert (await bank_sms.reconcile_store(session, store))["matched"] == 0
            for pid in pending_ids:
                assert (await session.get(Payment, uuid.UUID(pid))).status == "awaiting_review"


@pytest.mark.parametrize("provisional_offset,pending_offset,selected", [(0, -4, "provisional"), (-4, 0, "pending")])
async def test_sms_selects_the_closest_receipt_across_pending_and_provisional(provisional_offset, pending_offset, selected):
    async with api_client() as (c, maker, main):
        h, sid = await _login(c, maker, "provisional@example.com")
        admin = await _admin(c, maker)
        token = await _setup_source(maker, main.id)
        await _enable(c, admin, main.id)
        when = _minute()
        provisional_id = await _topup(
            c, h, sid, key="sms-provisional", paid_at=dom.utc_to_jalali_text(when + dt.timedelta(minutes=provisional_offset))
        )
        assert await _sweep(maker, 6) == 1
        other, _ = await _login(c, maker, "pending@example.com")
        pending_id = await _claimed_pending(
            c, other, sid, key="sms-pending", n=10, paid_at=dom.utc_to_jalali_text(when + dt.timedelta(minutes=pending_offset))
        )
        response = await _sms(c, main.id, token, sms_text(when=when))
        assert response.json()["status"] == "matched"
        async with maker() as session:
            original = await session.get(Payment, uuid.UUID(provisional_id))
            pending = await session.get(Payment, uuid.UUID(pending_id))
            assert original.meta["provisional"]["state"] == ("confirmed" if selected == "provisional" else "open")
            assert pending.status == ("awaiting_review" if selected == "provisional" else "succeeded")


async def test_many_unrelated_payments_do_not_hide_a_competing_receipt():
    async with api_client() as (c, maker, main):
        first, sid = await _login(c, maker, "provisional@example.com")
        admin = await _admin(c, maker)
        token = await _setup_source(maker, main.id)
        await _enable(c, admin, main.id)
        when = _minute()
        stamp = dom.utc_to_jalali_text(when)
        await _topup(c, first, sid, key="sms-provisional", paid_at=stamp)
        assert await _sweep(maker, 6) == 1
        other, _ = await _login(c, maker, "pending@example.com")
        pending_id = await _claimed_pending(c, other, sid, key="sms-pending", n=10, paid_at=stamp)
        async with maker() as session:
            pending = await session.get(Payment, uuid.UUID(pending_id))
            session.add_all(
                [
                    Payment(
                        user_id=pending.user_id,
                        store_id=pending.store_id,
                        purpose="wallet_topup",
                        provider="manual_card",
                        amount=1,
                        currency="IRT",
                        status="awaiting_review",
                        receipt_file_id=pending.receipt_file_id,
                        idempotency_key=f"older-unrelated-{i}",
                        created_at=pending.created_at - dt.timedelta(seconds=1),
                        meta={"receipt_claim": {"paid_at": pending.meta["receipt_claim"]["paid_at"]}},
                    )
                    for i in range(500)
                ]
            )
            await session.commit()
        response = await _sms(c, main.id, token, sms_text(when=when))
        assert response.json()["status"] == "ambiguous"
        async with maker() as session:
            assert (await session.get(Payment, uuid.UUID(pending_id))).status == "awaiting_review"
