"""Card-to-card auto verification end to end: forwarder webhook -> stored SMS -> matched receipt -> wallet credit.

Times are built from the current clock, so nothing here depends on the date the suite runs on.
"""

from __future__ import annotations

import datetime as dt

import pytest
from sqlalchemy import func, select

from _http import PASSWORD, add_user, api_client, totp_now
from melorin.domain import bank_sms as dom
from melorin.kernel.models.payments import BankSmsMessage, Payment
from melorin.kernel.models.stores import Store, StorePaymentConfiguration
from melorin.kernel.models.wallet import LedgerTransaction, Wallet
from melorin.modules.payments import bank_sms

AUTH = "/api/v1/auth"
ADMIN = "/api/v1/admin"
PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 64
SERIAL = "302570009152325001"


def _err(r):
    body = r.json()
    return body.get("error", body).get("code") if isinstance(body, dict) else None


def _minute(offset=1) -> dt.datetime:
    return (dt.datetime.now(dt.UTC) + dt.timedelta(minutes=offset)).replace(second=0, microsecond=0)


def sms_text(amount_rial=1_500_000, when=None, serial=SERIAL, balance=107_923_032, sign="+"):
    when = when or _minute()
    stamp = dom.utc_to_jalali_text(when)
    date, hm = stamp.split(" ")
    y, m, d = (int(x) for x in date.split("/"))
    return f"{serial}\n{amount_rial:,}{sign}\n{y}/{m}/{d}-{hm}\nمانده:{balance:,}"


async def _login(c, maker, email="user@example.com"):
    await add_user(maker, email=email)
    r = await c.post(f"{AUTH}/password/login", json={"email": email, "password": PASSWORD})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}, r.json()["store_id"]


async def _setup_source(maker, store_id, *, auto=True, **kw):
    async with maker() as s:
        store = await s.get(Store, store_id if not isinstance(store_id, str) else __import__("uuid").UUID(store_id))
        s.add(
            StorePaymentConfiguration(
                store_id=store.id,
                provider="manual_card",
                is_enabled=True,
                public_config={"card_number": "6037997000000000", "holder": "Test"},
            )
        )
        await s.commit()
        src, token = await bank_sms.save_source(s, store, actor_id=None, actor_type="system", auto_verify=auto, **kw)
        return token


async def _topup(c, h, sid, *, amount=150_000, key="manual-key-1", paid_at=None, receipt=True):
    r = await c.post(
        f"/api/v1/stores/{sid}/wallet/topups", json={"amount": amount, "provider": "manual_card"}, headers={**h, "Idempotency-Key": key}
    )
    assert r.status_code == 200, r.text
    pid = r.json()["id"]
    if receipt:
        r = await _receipt(c, h, sid, pid, paid_at=paid_at)
        assert r.status_code == 200, r.text
    return pid


async def _receipt(c, h, sid, pid, *, paid_at=None):
    data = {"paid_at": paid_at} if paid_at else {}
    return await c.post(f"/api/v1/stores/{sid}/payments/{pid}/receipt", files={"file": ("r.png", PNG, "image/png")}, data=data, headers=h)


async def _sms(c, store_id, token, text, *, sender=None, as_json=True):
    hdr = {"X-Webhook-Token": token}
    payload = {"text": text, **({"sender": sender} if sender else {})}
    return (
        await c.post(f"/api/v1/payments/bank-sms/{store_id}", json=payload, headers=hdr)
        if as_json
        else await c.post(f"/api/v1/payments/bank-sms/{store_id}", data=payload, headers=hdr)
    )


async def _balance(maker, sid):
    async with maker() as s:
        w = await s.scalar(select(Wallet).where(Wallet.store_id == __import__("uuid").UUID(sid)))
        return w.balance if w else 0


@pytest.fixture(autouse=True)
def _storage(tmp_path, monkeypatch):
    from melorin.core import storage

    monkeypatch.setattr(storage, "_storage", storage.LocalStorage(str(tmp_path)))


async def test_receipt_then_sms_credits_the_wallet_automatically():
    async with api_client() as (c, maker, main):
        h, sid = await _login(c, maker)
        token = await _setup_source(maker, main.id)
        when = _minute()
        pid = await _topup(c, h, sid, paid_at=dom.utc_to_jalali_text(when))
        assert (await c.get(f"/api/v1/stores/{sid}/payments/{pid}", headers=h)).json()["status"] == "awaiting_review"
        r = await _sms(c, main.id, token, sms_text(when=when))
        assert r.status_code == 200 and r.json() == {"ok": True, "status": "matched", "duplicate": False}
        assert (await c.get(f"/api/v1/stores/{sid}/payments/{pid}", headers=h)).json()["status"] == "succeeded"
        assert await _balance(maker, sid) == 150_000


async def test_sms_then_receipt_credits_when_the_receipt_arrives():
    async with api_client() as (c, maker, main):
        h, sid = await _login(c, maker)
        token = await _setup_source(maker, main.id)
        when = _minute()
        r = await c.post(
            f"/api/v1/stores/{sid}/wallet/topups",
            json={"amount": 150_000, "provider": "manual_card"},
            headers={**h, "Idempotency-Key": "manual-key-1"},
        )
        pid = r.json()["id"]
        assert (await _sms(c, main.id, token, sms_text(when=when))).json()["status"] == "unmatched"  # no receipt yet
        r = await _receipt(c, h, sid, pid, paid_at=dom.utc_to_jalali_text(when))
        assert r.json()["status"] == "succeeded"
        assert await _balance(maker, sid) == 150_000


async def test_duplicate_sms_never_credits_twice():
    async with api_client() as (c, maker, main):
        h, sid = await _login(c, maker)
        token = await _setup_source(maker, main.id)
        when = _minute()
        await _topup(c, h, sid, paid_at=dom.utc_to_jalali_text(when))
        first = await _sms(c, main.id, token, sms_text(when=when))
        again = await _sms(c, main.id, token, sms_text(when=when), as_json=False)  # forwarder retry, other body shape
        assert first.json()["status"] == "matched" and again.json()["duplicate"] is True
        assert await _balance(maker, sid) == 150_000
        async with maker() as s:
            assert await s.scalar(select(func.count()).select_from(BankSmsMessage)) == 1
            assert await s.scalar(select(func.count()).select_from(LedgerTransaction).where(LedgerTransaction.kind == "topup")) == 1


async def test_wrong_time_wrong_amount_or_no_claim_is_never_auto_approved():
    async with api_client() as (c, maker, main):
        h, sid = await _login(c, maker)
        token = await _setup_source(maker, main.id)
        when = _minute()
        wrong_time = await _topup(c, h, sid, key="k-wrong-time", paid_at=dom.utc_to_jalali_text(when - dt.timedelta(minutes=20)))
        no_claim = await _topup(c, h, sid, key="k-no-claim")
        other_amount = await _topup(c, h, sid, key="k-amount", amount=200_000, paid_at=dom.utc_to_jalali_text(when))
        r = await _sms(c, main.id, token, sms_text(when=when))
        assert r.json()["status"] == "unmatched"
        for pid in (wrong_time, no_claim, other_amount):
            assert (await c.get(f"/api/v1/stores/{sid}/payments/{pid}", headers=h)).json()["status"] == "awaiting_review"
        assert await _balance(maker, sid) == 0


async def test_two_identical_receipts_are_flagged_ambiguous_and_not_guessed():
    async with api_client() as (c, maker, main):
        h1, sid = await _login(c, maker, "a@example.com")
        h2, _ = await _login(c, maker, "b@example.com")
        token = await _setup_source(maker, main.id)
        when = _minute()
        stamp = dom.utc_to_jalali_text(when)
        p1 = await _topup(c, h1, sid, key="idem-key-a", paid_at=stamp)
        p2 = await _topup(c, h2, sid, key="idem-key-b", paid_at=stamp)
        r = await _sms(c, main.id, token, sms_text(when=when))
        assert r.json()["status"] == "ambiguous"
        assert await _balance(maker, sid) == 0
        # a human resolves it: the SMS is linked to exactly one payment
        async with maker() as s:
            sms = await s.scalar(select(BankSmsMessage))
            store = await s.get(Store, main.id)
            await bank_sms.manual_link(s, store, sms.id, __import__("uuid").UUID(p2), actor_id=None, actor_type="admin")
        assert (await c.get(f"/api/v1/stores/{sid}/payments/{p2}", headers=h2)).json()["status"] == "succeeded"
        assert (await c.get(f"/api/v1/stores/{sid}/payments/{p1}", headers=h1)).json()["status"] == "awaiting_review"


async def test_suggest_mode_does_not_credit_without_a_human():
    async with api_client() as (c, maker, main):
        h, sid = await _login(c, maker)
        token = await _setup_source(maker, main.id, auto=False)
        when = _minute()
        pid = await _topup(c, h, sid, paid_at=dom.utc_to_jalali_text(when))
        r = await _sms(c, main.id, token, sms_text(when=when))
        assert r.json()["status"] == "unmatched"
        assert (await c.get(f"/api/v1/stores/{sid}/payments/{pid}", headers=h)).json()["status"] == "awaiting_review"
        async with maker() as s:
            assert (await s.scalar(select(BankSmsMessage.note))) == f"suggested:{pid}"


async def test_webhook_is_protected():
    async with api_client() as (c, maker, main):
        token = await _setup_source(maker, main.id, senders=["MehrIran"])
        url = f"/api/v1/payments/bank-sms/{main.id}"
        body = {"text": sms_text(), "sender": "MehrIran"}
        assert _err(await c.post(url, json=body)) == "BANK_SMS_UNAUTHORIZED"
        assert _err(await c.post(url, json=body, headers={"X-Webhook-Token": "nope"})) == "BANK_SMS_UNAUTHORIZED"
        other = await c.post(f"/api/v1/payments/bank-sms/{__import__('uuid').uuid4()}", json=body, headers={"X-Webhook-Token": token})
        assert _err(other) == "BANK_SMS_UNAUTHORIZED"  # same answer for an unknown store: no enumeration
        assert _err(await c.post(url, json={**body, "sender": "Spam"}, headers={"X-Webhook-Token": token})) == "BANK_SMS_SENDER_REJECTED"
        assert (
            _err(await c.post(url, json={"text": "x" * 2000, "sender": "MehrIran"}, headers={"Authorization": f"Bearer {token}"}))
            == "BANK_SMS_TOO_LONG"
        )
        ok = await c.post(url, json=body, headers={"Authorization": f"Bearer {token}"})  # bearer form is accepted too
        assert ok.status_code == 200


async def test_stored_token_is_only_a_hash_and_rotation_revokes_the_old_one():
    async with api_client() as (c, maker, main):
        old = await _setup_source(maker, main.id)
        async with maker() as s:
            src = await bank_sms.get_source(s, main.id)
            assert src.token_hash != old and old not in (src.token_hash, src.token_hint)
            new = await bank_sms.rotate_token(s, await s.get(Store, main.id), actor_id=None, actor_type="system")
        url = f"/api/v1/payments/bank-sms/{main.id}"
        assert _err(await c.post(url, json={"text": sms_text()}, headers={"X-Webhook-Token": old})) == "BANK_SMS_UNAUTHORIZED"
        assert (await c.post(url, json={"text": sms_text()}, headers={"X-Webhook-Token": new})).status_code == 200


async def test_withdrawals_and_garbage_are_stored_but_never_matched():
    async with api_client() as (c, maker, main):
        h, sid = await _login(c, maker)
        token = await _setup_source(maker, main.id)
        when = _minute()
        pid = await _topup(c, h, sid, paid_at=dom.utc_to_jalali_text(when))
        assert (await _sms(c, main.id, token, sms_text(when=when, sign="-"))).json()["status"] == "ignored"
        assert (await _sms(c, main.id, token, "تخفیف ویژه! همین حالا بخرید")).json()["status"] == "unparsed"
        assert (await c.get(f"/api/v1/stores/{sid}/payments/{pid}", headers=h)).json()["status"] == "awaiting_review"


async def test_balance_gap_is_flagged_when_an_sms_was_missed():
    async with api_client() as (c, maker, main):
        token = await _setup_source(maker, main.id)
        t0 = _minute(-30)
        await _sms(c, main.id, token, sms_text(amount_rial=1_000_000, when=t0, serial="100000000000000001", balance=10_000_000))
        await _sms(
            c,
            main.id,
            token,
            sms_text(amount_rial=500_000, when=t0 + dt.timedelta(minutes=5), serial="100000000000000002", balance=10_500_000),
        )
        await _sms(
            c,
            main.id,
            token,
            sms_text(amount_rial=500_000, when=t0 + dt.timedelta(minutes=9), serial="100000000000000003", balance=99_000_000),
        )
        async with maker() as s:
            rows = (await s.scalars(select(BankSmsMessage).order_by(BankSmsMessage.occurred_at))).all()
            assert [r.balance_gap for r in rows] == [False, False, True]


async def test_receipt_claim_validation():
    async with api_client() as (c, maker, main):
        h, sid = await _login(c, maker)
        await _setup_source(maker, main.id)
        pid = await _topup(c, h, sid, receipt=False)
        bad = await _receipt(c, h, sid, pid, paid_at="yesterday")
        assert bad.status_code == 422 and _err(bad) == "RECEIPT_TIME_INVALID"
        future = await _receipt(c, h, sid, pid, paid_at=dom.utc_to_jalali_text(dt.datetime.now(dt.UTC) + dt.timedelta(days=2)))
        assert future.status_code == 422


async def test_unconfigured_store_still_works_with_manual_review_only():
    async with api_client() as (c, maker, main):
        h, sid = await _login(c, maker)
        async with maker() as s:
            s.add(
                StorePaymentConfiguration(
                    store_id=main.id,
                    provider="manual_card",
                    is_enabled=True,
                    public_config={"card_number": "6037997000000000", "holder": "T"},
                )
            )
            await s.commit()
        pid = await _topup(c, h, sid, paid_at=dom.utc_to_jalali_text(_minute()))
        assert (await c.get(f"/api/v1/stores/{sid}/payments/{pid}", headers=h)).json()["status"] == "awaiting_review"


async def test_admin_routes_configure_and_review_the_sms_inbox():
    async with api_client() as (c, maker, main):
        await add_user(maker, email="root@example.com", admin=True, totp=True)
        r = await c.post(f"{AUTH}/password/login", json={"email": "root@example.com", "password": PASSWORD, "totp_code": totp_now()})
        admin = {"Authorization": f"Bearer {r.json()['access_token']}"}
        base = f"{ADMIN}/stores/{main.id}/bank-sms"
        assert (await c.get(base)).status_code in (401, 403)  # closed to anonymous callers
        saved = await c.put(f"{base}/source", json={"auto_verify": True, "settings": {"window_minutes": 60}}, headers=admin)
        assert saved.status_code == 200, saved.text
        token = saved.json()["token"]
        assert token.startswith("mlr_sms_") and saved.json()["source"]["auto_verify"] is True
        again = await c.put(f"{base}/source", json={"senders": ["MehrIran"]}, headers=admin)
        assert again.json()["token"] is None  # the token is never shown a second time
        bad = await c.put(f"{base}/source", json={"settings": {"window_minutes": 1}}, headers=admin)
        assert bad.status_code == 422 and _err(bad) == "BANK_SMS_SETTING_INVALID"
        unknown = await c.put(f"{base}/source", json={"settings": {"yolo": 1}}, headers=admin)
        assert unknown.status_code == 422
        await c.put(f"{base}/source", json={"senders": []}, headers=admin)
        await _sms(c, main.id, token, sms_text())
        overview = (await c.get(base, headers=admin)).json()
        assert overview["source"]["has_token"] and len(overview["messages"]) == 1
        sms_id = overview["messages"][0]["id"]
        ign = await c.post(f"{base}/{sms_id}/ignore", json={"ignored": True}, headers=admin)
        assert ign.json()["status"] == "ignored"
        rot = await c.post(f"{base}/token", headers=admin)
        assert rot.json()["token"] != token


async def test_reconcile_job_pairs_open_deposits(monkeypatch):
    from melorin.worker import jobs

    async with api_client() as (c, maker, main):
        h, sid = await _login(c, maker)
        token = await _setup_source(maker, main.id)
        when = _minute()
        pid = await _topup(c, h, sid, paid_at=dom.utc_to_jalali_text(when), receipt=False)
        await _sms(c, main.id, token, sms_text(when=when))
        # receipt attached without the inline hook (e.g. a different channel): the periodic job still finishes the work
        async with maker() as s:
            from melorin.kernel.models.system import FileObject
            from melorin.modules.payments import service as payments

            fo = FileObject(
                owner_user_id=(await s.get(Payment, __import__("uuid").UUID(pid))).user_id,
                store_id=main.id,
                purpose="receipt",
                storage_key="k",
                content_type="image/png",
                size=1,
                sha256="0" * 64,
            )
            s.add(fo)
            await s.flush()
            p = await s.get(Payment, __import__("uuid").UUID(pid))
            await payments.attach_receipt(s, p, fo.id, {"paid_at": when.isoformat()})
        assert await jobs.bank_sms_reconcile_job() == 1
        assert await _balance(maker, sid) == 150_000
