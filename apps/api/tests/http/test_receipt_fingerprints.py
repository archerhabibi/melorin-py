"""Duplicate card-receipt detection by picture fingerprint (sha256 + Telegram file_unique_id), independent of bank SMS."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import func, select

from _db import make_store
from _http import PASSWORD, add_user, api_client, totp_now
from melorin.core.errors import AppError
from melorin.kernel.models.payments import Payment, PaymentReceiptFingerprint
from melorin.kernel.models.stores import Store, StorePaymentConfiguration
from melorin.kernel.models.system import FileObject, OutboxEvent
from melorin.modules.payments import receipt_fingerprints as rf
from test_bank_sms_auto_verify import ADMIN, _err, _login, _setup_source, _topup

PNG_A = b"\x89PNG\r\n\x1a\n" + b"A" * 64
PNG_B = b"\x89PNG\r\n\x1a\n" + b"B" * 64


@pytest.fixture(autouse=True)
def _storage(tmp_path, monkeypatch):
    from melorin.core import storage

    monkeypatch.setattr(storage, "_storage", storage.LocalStorage(str(tmp_path)))


async def _admin(c, maker):
    await add_user(maker, email="root@example.com", admin=True, totp=True)
    r = await c.post("/api/v1/auth/password/login", json={"email": "root@example.com", "password": PASSWORD, "totp_code": totp_now()})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


async def _pending(c, h, sid, key):
    """A card top-up that is waiting for its receipt."""
    return await _topup(c, h, sid, key=key, receipt=False)


async def _send(c, h, sid, pid, img=PNG_A, *, unique_id=None):
    return await c.post(
        f"/api/v1/stores/{sid}/payments/{pid}/receipt",
        files={"file": ("r.png", img, "image/png")},
        data={"file_unique_id": unique_id} if unique_id else {},
        headers=h,
    )


async def _payment(maker, pid) -> Payment:
    async with maker() as s:
        return await s.get(Payment, uuid.UUID(pid))


async def _set_policy(c, admin, store_id, policy):
    return await c.put(f"{ADMIN}/stores/{store_id}/receipt-duplicates/settings", json={"policy": policy}, headers=admin)


async def test_first_receipt_is_clean_and_stores_a_fingerprint():
    async with api_client() as (c, maker, main):
        h, sid = await _login(c, maker)
        await _setup_source(maker, main.id, auto=False)
        pid = await _pending(c, h, sid, "key-first-1")
        r = await _send(c, h, sid, pid, unique_id="AQADfirst")
        assert r.status_code == 200, r.text
        p = await _payment(maker, pid)
        assert "receipt_duplicate" not in (p.meta or {})
        async with maker() as s:
            fp = (await s.scalars(select(PaymentReceiptFingerprint))).one()
        assert fp.file_unique_id == "AQADfirst" and len(fp.sha256) == 64 and str(fp.payment_id) == pid


async def test_default_policy_is_warn_accepts_and_flags_the_reviewers():
    async with api_client() as (c, maker, main):
        h, sid = await _login(c, maker)
        await _setup_source(maker, main.id, auto=False)
        admin = await _admin(c, maker)
        first = await _pending(c, h, sid, "key-warn-first")
        assert (await _send(c, h, sid, first)).status_code == 200
        second = await _pending(c, h, sid, "key-warn-second")
        r = await _send(c, h, sid, second)
        assert r.status_code == 200 and r.json()["status"] == "awaiting_review"  # warn never costs the customer the upload

        dup = (await _payment(maker, second)).meta["receipt_duplicate"]
        assert dup["payments"] == [{"id": first, "status": "awaiting_review", "by": ["sha256"]}] and dup["other_stores"] == 0
        async with maker() as s:
            texts = [e.payload.get("text", "") for e in await s.scalars(select(OutboxEvent))]
        assert any("رسید تکراری" in t and first[:8] in t for t in texts)  # the notice names the earlier payment

        listing = {x["id"]: x for x in (await c.get(f"{ADMIN}/payments", headers=admin)).json()}
        assert listing[second]["receipt_duplicate"] is True and listing[first]["receipt_duplicate"] is False
        r = await c.get(f"{ADMIN}/payments/{second}/receipt-duplicates", headers=admin)
        assert r.status_code == 200
        assert [(d["payment_id"], d["matched_by"]) for d in r.json()["duplicates"]] == [(first, ["sha256"])]
        # symmetric: the older payment now sees the newer one, so a reviewer working top-down notices it as well
        r = await c.get(f"{ADMIN}/payments/{first}/receipt-duplicates", headers=admin)
        assert [d["payment_id"] for d in r.json()["duplicates"]] == [second]


async def test_block_policy_refuses_before_storing_anything():
    async with api_client() as (c, maker, main):
        h, sid = await _login(c, maker)
        await _setup_source(maker, main.id, auto=False)
        admin = await _admin(c, maker)
        assert (await _set_policy(c, admin, main.id, "block")).json() == {"policy": "block"}
        first = await _pending(c, h, sid, "key-block-first")
        assert (await _send(c, h, sid, first)).status_code == 200
        second = await _pending(c, h, sid, "key-block-second")
        files_before = await _count(maker, FileObject)
        r = await _send(c, h, sid, second)
        assert r.status_code == 409 and _err(r) == "RECEIPT_DUPLICATE", r.text
        assert "پذیرفته نمی" in r.json()["error"]["message"] and first not in r.text  # nothing about the other payment leaks
        p = await _payment(maker, second)
        assert p.status == "pending" and p.receipt_file_id is None  # still open: the customer can send the right picture
        assert await _count(maker, FileObject) == files_before and await _count(maker, PaymentReceiptFingerprint) == 1
        assert (await _send(c, h, sid, second, PNG_B)).status_code == 200  # a different picture is accepted


async def test_resending_the_same_picture_for_the_same_payment_is_not_a_duplicate():
    async with api_client() as (c, maker, main):
        h, sid = await _login(c, maker)
        await _setup_source(maker, main.id, auto=False)
        admin = await _admin(c, maker)
        await _set_policy(c, admin, main.id, "block")
        pid = await _pending(c, h, sid, "key-retry-1")
        assert (await _send(c, h, sid, pid, unique_id="AQADretry")).status_code == 200
        assert (await _send(c, h, sid, pid, unique_id="AQADretry")).status_code == 200  # a retry after a flaky connection
        assert "receipt_duplicate" not in ((await _payment(maker, pid)).meta or {})


async def test_telegram_file_unique_id_catches_a_recompressed_copy_and_junk_ids_are_ignored():
    async with api_client() as (c, maker, main):
        h, sid = await _login(c, maker)
        await _setup_source(maker, main.id, auto=False)
        first = await _pending(c, h, sid, "key-fid-first")
        assert (await _send(c, h, sid, first, PNG_A, unique_id="AQADshared")).status_code == 200
        second = await _pending(c, h, sid, "key-fid-second")
        assert (await _send(c, h, sid, second, PNG_B, unique_id="AQADshared")).status_code == 200  # other bytes, same Telegram file
        assert (await _payment(maker, second)).meta["receipt_duplicate"]["payments"][0]["by"] == ["file_unique_id"]
        third = await _pending(c, h, sid, "key-fid-third")
        assert (await _send(c, h, sid, third, b"\x89PNG\r\n\x1a\n" + b"C" * 64, unique_id="bad id; DROP")).status_code == 200
        assert "receipt_duplicate" not in ((await _payment(maker, third)).meta or {})
        async with maker() as s:
            fps = (await s.scalars(select(PaymentReceiptFingerprint).where(PaymentReceiptFingerprint.payment_id == uuid.UUID(third)))).all()
        assert len(fps) == 1 and fps[0].file_unique_id is None and fps[0].sha256  # malformed id dropped, hash still kept


async def test_block_lets_a_picture_through_that_only_a_rejected_payment_used_but_warn_still_lists_it():
    async with api_client() as (c, maker, main):
        h, sid = await _login(c, maker)
        await _setup_source(maker, main.id, auto=False)
        admin = await _admin(c, maker)
        first = await _pending(c, h, sid, "key-dead-first")
        assert (await _send(c, h, sid, first)).status_code == 200
        r = await c.post(f"{ADMIN}/payments/{first}/review", json={"approve": False, "reason": "wrong amount"}, headers=admin)
        assert r.status_code == 200, r.text
        await _set_policy(c, admin, main.id, "block")
        second = await _pending(c, h, sid, "key-dead-second")
        assert (await _send(c, h, sid, second)).status_code == 200  # the earlier payment failed: a retry must be possible
        dup = (await _payment(maker, second)).meta["receipt_duplicate"]
        assert dup["payments"][0]["id"] == first and dup["payments"][0]["status"] == "failed"
        # ...but a picture that a live payment holds is blocked
        third = await _pending(c, h, sid, "key-dead-third")
        assert _err(await _send(c, h, sid, third)) == "RECEIPT_DUPLICATE"


async def test_duplicate_picture_is_not_provisionally_credited_even_with_the_flag_only():
    """The grace sweep reads the fingerprint verdict, so a flagged receipt stays with a human."""
    from melorin.modules.payments import provisional

    async with api_client() as (c, maker, main):
        h, sid = await _login(c, maker)
        await _setup_source(maker, main.id, auto=False)
        first = await _pending(c, h, sid, "key-grace-first")
        assert (await _send(c, h, sid, first)).status_code == 200
        second = await _pending(c, h, sid, "key-grace-second")
        assert (await _send(c, h, sid, second)).status_code == 200
        async with maker() as s:
            p = await s.get(Payment, uuid.UUID(second))
            history = [p]
            assert await provisional._block_reason(s, p, {**provisional.DEFAULT, "max_amount_rial": 10**12}, history) == "duplicate_image"


async def test_policy_endpoint_validates_and_is_audited():
    async with api_client() as (c, maker, main):
        admin = await _admin(c, maker)
        assert (await c.get(f"{ADMIN}/stores/{main.id}/receipt-duplicates/settings", headers=admin)).json() == {"policy": "warn"}
        r = await _set_policy(c, admin, main.id, "ban-everyone")
        assert r.status_code == 422 and _err(r) == "RECEIPT_DUP_POLICY_INVALID"
        assert (await _set_policy(c, admin, main.id, "block")).status_code == 200
        assert (await c.get(f"{ADMIN}/stores/{main.id}/receipt-duplicates/settings", headers=admin)).json() == {"policy": "block"}
        r = await c.put(f"{ADMIN}/stores/{main.id}/receipt-duplicates/settings", json={"policy": "warn", "x": 1}, headers=admin)
        assert r.status_code == 422  # unknown fields are refused


async def test_a_reseller_owner_sees_only_their_own_store_and_other_stores_are_only_counted():
    async with api_client() as (c, maker, main):
        owner = await add_user(maker, email="owner@example.com")
        async with maker() as s:
            shop = await make_store(s, kind="reseller", owner=owner, slug="shop-one")
            other = await make_store(s, kind="reseller", owner=await _make_owner(s), slug="shop-two")
            s.add(
                StorePaymentConfiguration(
                    store_id=shop.id,
                    provider="manual_card",
                    is_enabled=True,
                    public_config={"card_number": "6037997000000000", "holder": "T"},
                )
            )
            mine = await _payment_row(s, shop, owner)
            theirs = await _payment_row(s, other, owner)
            twin = await _payment_row(s, shop, owner)
            for pay in (mine, theirs, twin):
                s.add(PaymentReceiptFingerprint(payment_id=pay.id, store_id=pay.store_id, sha256="ab" * 32))
            await s.commit()
            shop_id, mine_id, theirs_id, twin_id = shop.id, mine.id, theirs.id, twin.id
        r = await c.post("/api/v1/auth/password/login", json={"email": "owner@example.com", "password": PASSWORD})
        h = {"Authorization": f"Bearer {r.json()['access_token']}"}
        base = f"/api/v1/stores/{shop_id}/reseller"
        r = await c.get(f"{base}/payments/{mine_id}/receipt-duplicates", headers=h)
        assert r.status_code == 200, r.text
        body = r.json()
        assert [d["payment_id"] for d in body["duplicates"]] == [str(twin_id)] and body["other_stores"] == 1
        assert str(theirs_id) not in r.text  # the other store's payment id never reaches this owner
        assert (await c.put(f"{base}/receipt-duplicates/settings", json={"policy": "block"}, headers=h)).json() == {"policy": "block"}
        assert (await c.get(f"{base}/receipt-duplicates/settings", headers=h)).json() == {"policy": "block"}


def test_helpers_summarize_and_text():
    store, other = uuid.uuid4(), uuid.uuid4()
    pid = uuid.uuid4()
    m = [rf.Match(pid, store, "succeeded", ("sha256",)), rf.Match(uuid.uuid4(), other, "failed", ("file_unique_id",))]
    s = rf.summarize(m, store_id=store)
    assert s == {"payments": [{"id": str(pid), "status": "succeeded", "by": ["sha256"]}], "other_stores": 1}
    assert str(pid)[:8] in rf.warning_text(s) and "فروشگاه دیگر" in rf.warning_text(s)
    assert rf.summarize([], store_id=store) is None and rf.warning_text(None) == ""
    assert (
        rf.clean_file_unique_id(" AQAD-x_1 ") == "AQAD-x_1"
        and rf.clean_file_unique_id("a b") is None
        and rf.clean_file_unique_id("") is None
    )
    with pytest.raises(AppError) as exc:
        rf.reject_if_blocked("block", [rf.Match(pid, store, "awaiting_review", ("sha256",))])
    assert exc.value.code == "RECEIPT_DUPLICATE" and exc.value.status == 409
    rf.reject_if_blocked("block", [rf.Match(pid, store, "failed", ("sha256",))])
    rf.reject_if_blocked("warn", [rf.Match(pid, store, "succeeded", ("sha256",))])


async def _count(maker, model) -> int:
    async with maker() as s:
        return await s.scalar(select(func.count()).select_from(model))


async def _make_owner(s):
    from _db import make_user

    return await make_user(s)


async def _payment_row(s, store: Store, user) -> Payment:
    p = Payment(
        user_id=user.id,
        store_id=store.id,
        purpose="wallet_topup",
        provider="manual_card",
        amount=100_000,
        currency=store.currency,
        status="awaiting_review",
        idempotency_key=uuid.uuid4().hex,
        meta={},
    )
    s.add(p)
    await s.flush()
    return p
