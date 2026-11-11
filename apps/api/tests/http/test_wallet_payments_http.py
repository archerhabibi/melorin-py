"""Phase 4: customer wallet and payment routes over HTTP (store-scoped, idempotent, receipt upload, gateway callbacks)."""

from __future__ import annotations

import pytest
from sqlalchemy import select

from _db import make_store
from _http import PASSWORD, add_user, api_client
from melorin.kernel.models.payments import Payment
from melorin.kernel.models.stores import StorePaymentConfiguration
from melorin.modules.payments.adapters import registry
from melorin.modules.payments.adapters.base import CallbackResult, IntentResult

AUTH = "/api/v1/auth"
PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 64


def _err(r):
    body = r.json()
    return body.get("error", body).get("code") if isinstance(body, dict) else None


class FakeGateway:
    name = "fake_gw"
    requires_review = False

    async def create_payment_intent(self, payment, *, callback_url, settings):
        return IntentResult(instructions={"type": "redirect", "url": callback_url}, external_ref=f"AUTH-{payment.id.hex[:8]}")

    async def verify_callback(self, params, payment, *, settings):
        ok = params.get("Status") == "OK" and params.get("Authority") == payment.external_ref
        return CallbackResult(str(payment.id), params.get("Authority"), ok, dict(params))

    async def query_payment_status(self, payment, *, settings):
        return payment.status

    def normalize_status(self, raw):
        return raw


@pytest.fixture
def gateway(monkeypatch):
    gw = FakeGateway()
    monkeypatch.setitem(registry._ADAPTERS, gw.name, gw)
    return gw


async def _login(c, maker, email="user@example.com"):
    await add_user(maker, email=email)
    r = await c.post(f"{AUTH}/password/login", json={"email": email, "password": PASSWORD})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}, r.json()["store_id"]


async def _enable(maker, store, provider="fake_gw", **public):
    async with maker() as s:
        s.add(StorePaymentConfiguration(store_id=store.id, provider=provider, is_enabled=True, public_config=public))
        await s.commit()


# --- wallet ----------------------------------------------------------------------------------------------------------


async def test_wallet_routes_need_a_session_opened_for_that_very_store():
    async with api_client() as (c, maker, main):
        h, sid = await _login(c, maker)
        assert (await c.get(f"/api/v1/stores/{sid}/wallet")).status_code == 401
        async with maker() as s:
            other = await make_store(s, kind="reseller", slug="other")
            await s.commit()
        wrong = await c.get(f"/api/v1/stores/{other.id}/wallet", headers=h)
        assert wrong.status_code == 403 and _err(wrong) == "CHANNEL_MISMATCH"  # a main-store session never reads another store


async def test_wallet_is_created_lazily_in_the_store_currency_with_an_empty_ledger():
    async with api_client() as (c, maker, main):
        h, sid = await _login(c, maker)
        w = await c.get(f"/api/v1/stores/{sid}/wallet", headers=h)
        assert w.status_code == 200
        assert (w.json()["store_id"], w.json()["currency"], w.json()["balance"]) == (sid, main.currency, 0)
        again = await c.get(f"/api/v1/stores/{sid}/wallet", headers=h)
        assert again.json()["id"] == w.json()["id"]  # same wallet, not a new one per call
        tx = await c.get(f"/api/v1/stores/{sid}/wallet/transactions", headers=h)
        assert tx.status_code == 200 and tx.json() == {"items": [], "total": 0, "limit": 50, "offset": 0}


async def test_wallet_transactions_are_paginated_newest_first_and_validate_paging():
    from melorin.modules.wallet import service as wallet

    async with api_client() as (c, maker, main):
        h, sid = await _login(c, maker)
        async with maker() as s:
            user_id = (await c.get("/api/v1/me", headers=h)).json()["id"]
            import uuid

            w = await wallet.get_wallet(s, uuid.UUID(user_id), main.id, currency=main.currency)
            for i in range(3):
                await wallet.post(
                    s,
                    kind="topup",
                    key=f"seed-{i}",
                    currency=main.currency,
                    postings=[
                        wallet.Posting(-(100 * (i + 1)), account=wallet.acc_store_topup(main.id, "manual_card")),
                        wallet.Posting(100 * (i + 1), wallet=w),
                    ],
                    store_id=main.id,
                    memo=f"m{i}",
                )
            await s.commit()
        page = await c.get(f"/api/v1/stores/{sid}/wallet/transactions?limit=2", headers=h)
        body = page.json()
        assert page.status_code == 200 and body["total"] == 3 and body["limit"] == 2 and len(body["items"]) == 2
        assert body["items"][0]["balance_after"] == 600  # newest first: 100 + 200 + 300
        rest = await c.get(f"/api/v1/stores/{sid}/wallet/transactions?limit=2&offset=2", headers=h)
        assert len(rest.json()["items"]) == 1
        assert (await c.get(f"/api/v1/stores/{sid}/wallet/transactions?limit=0", headers=h)).status_code == 422
        assert (await c.get(f"/api/v1/stores/{sid}/wallet/transactions?limit=201", headers=h)).status_code == 422


# --- top-up ----------------------------------------------------------------------------------------------------------


async def test_topup_creates_a_pending_payment_and_is_idempotent_per_key(gateway):
    async with api_client() as (c, maker, main):
        await _enable(maker, main)
        h, sid = await _login(c, maker)
        url = f"/api/v1/stores/{sid}/wallet/topups"
        body = {"amount": 5000, "provider": "fake_gw"}
        first = await c.post(url, json=body, headers={**h, "Idempotency-Key": "topup-key-1"})
        assert first.status_code == 200, first.text
        assert (first.json()["status"], first.json()["amount"], first.json()["store_id"]) == ("pending", 5000, sid)
        replay = await c.post(url, json=body, headers={**h, "Idempotency-Key": "topup-key-1"})
        assert replay.json()["id"] == first.json()["id"]
        clash = await c.post(url, json={**body, "amount": 9000}, headers={**h, "Idempotency-Key": "topup-key-1"})
        assert clash.status_code == 409 and _err(clash) == "IDEMPOTENCY_KEY_REUSE"
        async with maker() as s:
            assert len((await s.scalars(select(Payment))).all()) == 1  # a retry never doubles the charge


async def test_topup_validates_the_key_the_amount_and_the_provider(gateway):
    async with api_client() as (c, maker, main):
        await _enable(maker, main)
        h, sid = await _login(c, maker)
        url = f"/api/v1/stores/{sid}/wallet/topups"
        assert (await c.post(url, json={"amount": 5000, "provider": "fake_gw"}, headers=h)).status_code == 422  # key required
        short = await c.post(url, json={"amount": 5000, "provider": "fake_gw"}, headers={**h, "Idempotency-Key": "short"})
        assert short.status_code == 422
        zero = await c.post(url, json={"amount": 0, "provider": "fake_gw"}, headers={**h, "Idempotency-Key": "valid-key-1"})
        assert zero.status_code == 422
        unknown = await c.post(url, json={"amount": 5000, "provider": "nope"}, headers={**h, "Idempotency-Key": "valid-key-2"})
        assert unknown.status_code == 400 and _err(unknown) == "GATEWAY_UNKNOWN"


# --- payment list / detail ---------------------------------------------------------------------------------------------


async def test_payments_are_visible_only_to_their_owner_inside_their_store(gateway):
    async with api_client() as (c, maker, main):
        await _enable(maker, main)
        ha, sid = await _login(c, maker, "a@example.com")
        hb, _ = await _login(c, maker, "b@example.com")
        pay = (
            await c.post(
                f"/api/v1/stores/{sid}/wallet/topups",
                json={"amount": 1000, "provider": "fake_gw"},
                headers={**ha, "Idempotency-Key": "owner-a-key"},
            )
        ).json()
        mine = await c.get(f"/api/v1/stores/{sid}/payments", headers=ha)
        assert [p["id"] for p in mine.json()] == [pay["id"]]
        assert (await c.get(f"/api/v1/stores/{sid}/payments", headers=hb)).json() == []
        assert (await c.get(f"/api/v1/stores/{sid}/payments/{pay['id']}", headers=ha)).status_code == 200
        other = await c.get(f"/api/v1/stores/{sid}/payments/{pay['id']}", headers=hb)
        assert other.status_code == 404  # existence is not even revealed to another customer


# --- receipt upload ----------------------------------------------------------------------------------------------------


async def _manual_payment(c, maker, main, h, sid):
    await _enable(maker, main, provider="manual_card", card_number="6037997000000000", holder="Test")
    r = await c.post(
        f"/api/v1/stores/{sid}/wallet/topups",
        json={"amount": 2000, "provider": "manual_card"},
        headers={**h, "Idempotency-Key": "manual-key-1"},
    )
    assert r.status_code == 200, r.text
    return r.json()["id"]


async def test_receipt_upload_moves_a_manual_payment_to_review(tmp_path, monkeypatch):
    from melorin.core import storage

    monkeypatch.setattr(storage, "_storage", storage.LocalStorage(str(tmp_path)))
    async with api_client() as (c, maker, main):
        h, sid = await _login(c, maker)
        pid = await _manual_payment(c, maker, main, h, sid)
        r = await c.post(f"/api/v1/stores/{sid}/payments/{pid}/receipt", files={"file": ("r.png", PNG, "image/png")}, headers=h)
        assert r.status_code == 200, r.text
        assert r.json()["status"] == "awaiting_review"
        assert any(p.is_file() for p in tmp_path.rglob("*"))  # the file really was stored
        again = await c.post(f"/api/v1/stores/{sid}/payments/{pid}/receipt", files={"file": ("r.png", PNG, "image/png")}, headers=h)
        assert again.status_code == 200  # a corrected receipt can replace the first while still in review


@pytest.mark.parametrize(
    "name,data,ctype,status,code",
    [
        ("r.exe", b"MZ" + b"0" * 30, "application/x-msdownload", 415, "UNSUPPORTED_FILE"),
        ("r.png", b"not really a png file", "image/png", 415, "INVALID_FILE_SIGNATURE"),
        ("r.webp", b"RIFF" + b"0" * 30, "image/webp", 415, "INVALID_FILE_SIGNATURE"),
    ],
)
async def test_receipt_upload_rejects_wrong_types_and_fake_signatures(tmp_path, monkeypatch, name, data, ctype, status, code):
    from melorin.core import storage

    monkeypatch.setattr(storage, "_storage", storage.LocalStorage(str(tmp_path)))
    async with api_client() as (c, maker, main):
        h, sid = await _login(c, maker)
        pid = await _manual_payment(c, maker, main, h, sid)
        r = await c.post(f"/api/v1/stores/{sid}/payments/{pid}/receipt", files={"file": (name, data, ctype)}, headers=h)
        assert (r.status_code, _err(r)) == (status, code)
        assert not any(p.is_file() for p in tmp_path.rglob("*"))  # nothing is stored for a rejected file


async def test_receipt_upload_enforces_the_size_limit_while_streaming(tmp_path, monkeypatch):
    from melorin.core import storage
    from melorin.core.config import get_settings

    monkeypatch.setattr(storage, "_storage", storage.LocalStorage(str(tmp_path)))
    async with api_client() as (c, maker, main):
        h, sid = await _login(c, maker)
        pid = await _manual_payment(c, maker, main, h, sid)
        big = PNG + b"0" * get_settings().max_upload_bytes
        r = await c.post(f"/api/v1/stores/{sid}/payments/{pid}/receipt", files={"file": ("r.png", big, "image/png")}, headers=h)
        assert r.status_code == 413 and _err(r) == "FILE_TOO_LARGE"


async def test_receipt_is_refused_for_gateway_payments(gateway, tmp_path, monkeypatch):
    from melorin.core import storage

    monkeypatch.setattr(storage, "_storage", storage.LocalStorage(str(tmp_path)))
    async with api_client() as (c, maker, main):
        await _enable(maker, main)
        h, sid = await _login(c, maker)
        pid = (
            await c.post(
                f"/api/v1/stores/{sid}/wallet/topups",
                json={"amount": 1000, "provider": "fake_gw"},
                headers={**h, "Idempotency-Key": "gateway-key-1"},
            )
        ).json()["id"]
        r = await c.post(f"/api/v1/stores/{sid}/payments/{pid}/receipt", files={"file": ("r.png", PNG, "image/png")}, headers=h)
        assert r.status_code == 409 and _err(r) == "INVALID_PAYMENT_STATE"


# --- gateway callbacks -------------------------------------------------------------------------------------------------


async def test_callback_get_and_post_redirect_the_browser_to_the_store_web_with_the_final_status(gateway):
    async with api_client() as (c, maker, main):
        await _enable(maker, main)
        h, sid = await _login(c, maker)
        pay = (
            await c.post(
                f"/api/v1/stores/{sid}/wallet/topups",
                json={"amount": 1000, "provider": "fake_gw"},
                headers={**h, "Idempotency-Key": "callback-key-1"},
            )
        ).json()
        async with maker() as s:
            ref = (await s.get(Payment, __import__("uuid").UUID(pay["id"]))).external_ref
        ok = await c.get(f"/api/v1/payments/callbacks/fake_gw?pid={pay['id']}&Status=OK&Authority={ref}")
        assert ok.status_code == 303
        assert ok.headers["location"] == f"http://localhost:3000/account/payments/{pay['id']}?status=succeeded"
        # the gateway retries with a POST (form body): the same payment is not credited twice and still redirects
        dup = await c.post(f"/api/v1/payments/callbacks/fake_gw?pid={pay['id']}", data={"Status": "OK", "Authority": ref})
        assert dup.status_code == 303 and dup.headers["location"].endswith("status=succeeded")
        bal = (await c.get(f"/api/v1/stores/{sid}/wallet", headers=h)).json()["balance"]
        assert bal == 1000


async def test_callback_with_a_tampered_authority_fails_the_payment_and_never_credits(gateway):
    async with api_client() as (c, maker, main):
        await _enable(maker, main)
        h, sid = await _login(c, maker)
        pay = (
            await c.post(
                f"/api/v1/stores/{sid}/wallet/topups",
                json={"amount": 1000, "provider": "fake_gw"},
                headers={**h, "Idempotency-Key": "callback-key-2"},
            )
        ).json()
        r = await c.get(f"/api/v1/payments/callbacks/fake_gw?pid={pay['id']}&Status=OK&Authority=FORGED")
        assert r.status_code == 303 and not r.headers["location"].endswith("status=succeeded")
        assert (await c.get(f"/api/v1/stores/{sid}/wallet", headers=h)).json()["balance"] == 0


async def test_callback_rejects_unknown_provider_garbage_ids_and_unparsable_post_bodies(gateway):
    async with api_client() as (c, maker, main):
        assert (await c.get("/api/v1/payments/callbacks/unknown?pid=x")).status_code == 400
        bad_id = await c.get("/api/v1/payments/callbacks/fake_gw?pid=not-a-uuid")
        assert bad_id.status_code == 404 and _err(bad_id) == "PAYMENT_NOT_FOUND"
        missing = await c.get("/api/v1/payments/callbacks/fake_gw")
        assert missing.status_code == 404
        # a POST whose body is not a form must not crash: the query string still carries the fields
        weird = await c.post(
            "/api/v1/payments/callbacks/fake_gw?pid=00000000-0000-0000-0000-000000000000",
            content=b"\xff\xfe not a form",
            headers={"content-type": "multipart/form-data; boundary=zzz"},
        )
        assert weird.status_code == 404 and _err(weird) == "PAYMENT_NOT_FOUND"
