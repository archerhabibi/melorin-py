"""Phase 4.13: the reseller panel and the versioned reseller API over HTTP, with Store isolation as the main subject.

Two reseller stores (A, B) live next to the main store. Owner A reaches the panel through the main store (the account hub) and must
never read or change anything of store B; the API key of A opens store A and nothing else."""

from __future__ import annotations

import types

import pytest
from sqlalchemy import func, select

from _db import make_product, make_store, make_user
from _http import PASSWORD, add_user, api_client
from melorin.kernel.models.bundles import Bundle, BundleMember, BundleProduct
from melorin.kernel.models.catalog import Product, StoreProduct
from melorin.kernel.models.identity import User
from melorin.kernel.models.payments import Payment
from melorin.kernel.models.stores import ApiCredential, ResellerProfile, StoreMembership, StorePaymentConfiguration
from melorin.kernel.models.system import AuditEvent
from melorin.kernel.models.vpn import Panel, Server
from melorin.kernel.models.wallet import LedgerEntry, Wallet
from melorin.modules.reseller import api_keys
from melorin.modules.webhooks import service as webhook_svc

AUTH = "/api/v1/auth"
V1 = "/api/v1"
API = "/api/v1/reseller-api/v1"
PUBLIC_IP = "93.184.216.34"


def _err(r):
    body = r.json()
    return body.get("error", body).get("code") if isinstance(body, dict) else None


@pytest.fixture(autouse=True)
def public_dns(monkeypatch):
    """Webhook hosts resolve to a public address (the SSRF guard resolves them); every other host is left alone."""
    real = webhook_svc.socket.getaddrinfo

    def fake(host, *a, **k):
        if str(host).endswith("example.com"):
            return [(2, 1, 6, "", (PUBLIC_IP, 443))]
        return real(host, *a, **k)

    monkeypatch.setattr(webhook_svc.socket, "getaddrinfo", fake)


async def _world(c, maker, main, *, api_enabled=True):
    """Owner A + store A, owner B + store B, one stranger. Returns the owners' bearer headers (main-store hub sessions)."""
    owner_a = await add_user(maker, email="a@example.com")
    owner_b = await add_user(maker, email="b@example.com")
    await add_user(maker, email="stranger@example.com")
    async with maker() as s:
        store_a = await make_store(s, kind="reseller", owner=owner_a, slug="shop-a")
        store_b = await make_store(s, kind="reseller", owner=owner_b, slug="shop-b")
        for st, owner in ((store_a, owner_a), (store_b, owner_b)):
            s.add(ResellerProfile(store_id=st.id, user_id=owner.id, debt_limit=5000, api_enabled=api_enabled, sales_enabled=True))
        await s.commit()
    headers = {}
    for who in ("a", "b", "stranger"):
        r = await c.post(f"{AUTH}/password/login", json={"email": f"{who}@example.com", "password": PASSWORD})
        assert r.status_code == 200, r.text
        headers[who] = {"Authorization": f"Bearer {r.json()['access_token']}"}
    return types.SimpleNamespace(a=store_a, b=store_b, owner_a=owner_a, owner_b=owner_b, h=headers)


async def _customer(maker, store, *, email, status="active", balance=0):
    async with maker() as s:
        user = User(email=email, display_name=email.split("@")[0], is_active=True)
        s.add(user)
        await s.flush()
        s.add(StoreMembership(store_id=store.id, user_id=user.id, role="customer", status=status))
        await s.commit()
        return user


def _panel(store, path=""):
    return f"{V1}/stores/{store.id}/reseller{path}"


OWNER_GETS = ["/customers", "/profile", "/reports", "/api-credentials", "/webhooks", "/payment-config", "/payments", "/prices", "/bundles"]


# --- isolation ------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("path", OWNER_GETS)
async def test_the_reseller_panel_is_closed_to_anonymous_callers_strangers_and_other_owners(path):
    async with api_client() as (c, maker, main):
        w = await _world(c, maker, main)
        assert (await c.get(_panel(w.a, path))).status_code == 401
        assert (await c.get(_panel(w.a, path), headers=w.h["a"])).status_code == 200  # the owner himself
        for who in ("b", "stranger"):  # another owner / somebody who owns nothing: the hub session cannot reach store A
            r = await c.get(_panel(w.a, path), headers=w.h[who])
            assert r.status_code == 403 and _err(r) == "CHANNEL_MISMATCH", (who, path)


async def test_the_owner_panel_exists_only_for_reseller_stores():
    async with api_client() as (c, maker, main):
        w = await _world(c, maker, main)
        r = await c.get(f"{V1}/stores/{main.id}/reseller/profile", headers=w.h["a"])
        assert r.status_code == 403 and _err(r) == "FORBIDDEN"


# --- customers and the manual wallet top-up -------------------------------------------------------------------------


async def test_customer_list_contains_only_the_members_of_this_store():
    async with api_client() as (c, maker, main):
        w = await _world(c, maker, main)
        mine = await _customer(maker, w.a, email="mine@example.com")
        await _customer(maker, w.b, email="theirs@example.com")
        rows = (await c.get(_panel(w.a, "/customers"), headers=w.h["a"])).json()
        assert [r["user_id"] for r in rows] == [str(mine.id)] and rows[0]["email"] == "mine@example.com"


def _adjust(amount, key="key-00000001", reason="cash received", **kw):
    return {"amount": amount, "reason": reason, "idempotency_key": key, **kw}


async def _wallet(maker, user_id, store_id):
    async with maker() as s:
        return await s.scalar(select(Wallet).where(Wallet.user_id == user_id, Wallet.store_id == store_id))


async def test_manual_topup_credits_once_per_idempotency_key_and_uses_the_stores_own_cash_account():
    async with api_client() as (c, maker, main):
        w = await _world(c, maker, main)
        cust = await _customer(maker, w.a, email="mine@example.com")
        url = _panel(w.a, f"/customers/{cust.id}/wallet")
        first = await c.post(url, headers=w.h["a"], json=_adjust(2500, reference="receipt-7"))
        retry = await c.post(url, headers=w.h["a"], json=_adjust(2500))  # same key: a network retry, not a second top-up
        assert first.status_code == retry.status_code == 200
        assert first.json()["balance"] == retry.json()["balance"] == 2500
        assert first.json()["transaction_id"] == retry.json()["transaction_id"]
        second = await c.post(url, headers=w.h["a"], json=_adjust(500, key="key-00000002"))
        assert second.json()["balance"] == 3000
        wallet = await _wallet(maker, cust.id, w.a.id)
        assert wallet.balance == 3000 and wallet.store_id == w.a.id
        async with maker() as s:
            assert (
                await s.scalar(select(func.count()).select_from(AuditEvent).where(AuditEvent.action == "reseller.customer_wallet_adjusted"))
                == 2
            )


async def test_manual_correction_can_never_drive_a_customer_wallet_negative():
    async with api_client() as (c, maker, main):
        w = await _world(c, maker, main)
        cust = await _customer(maker, w.a, email="mine@example.com")
        url = _panel(w.a, f"/customers/{cust.id}/wallet")
        await c.post(url, headers=w.h["a"], json=_adjust(1000))
        over = await c.post(url, headers=w.h["a"], json=_adjust(-1001, key="key-00000002"))
        assert over.status_code == 409 and _err(over) == "INSUFFICIENT_FUNDS"
        ok = await c.post(url, headers=w.h["a"], json=_adjust(-1000, key="key-00000003"))
        assert ok.status_code == 200 and ok.json()["balance"] == 0


async def test_manual_topup_validates_amount_cap_and_membership():
    async with api_client() as (c, maker, main):
        w = await _world(c, maker, main)
        mine = await _customer(maker, w.a, email="mine@example.com")
        theirs = await _customer(maker, w.b, email="theirs@example.com")
        banned = await _customer(maker, w.a, email="banned@example.com", status="blocked")
        zero = await c.post(_panel(w.a, f"/customers/{mine.id}/wallet"), headers=w.h["a"], json=_adjust(0))
        assert zero.status_code == 400 and _err(zero) == "BAD_AMOUNT"
        # the customer of ANOTHER store, a blocked member and an unknown user are all "not my customer"
        for other in (theirs.id, banned.id, "00000000-0000-0000-0000-000000000001"):
            r = await c.post(_panel(w.a, f"/customers/{other}/wallet"), headers=w.h["a"], json=_adjust(100))
            assert r.status_code == 404, other
        assert await _wallet(maker, theirs.id, w.a.id) is None and await _wallet(maker, theirs.id, w.b.id) is None
        bad_body = await c.post(
            _panel(w.a, f"/customers/{mine.id}/wallet"), headers=w.h["a"], json={"amount": 5, "reason": "x", "idempotency_key": "short"}
        )
        assert bad_body.status_code == 422
        from melorin.core import settings_store

        async with maker() as s:
            await settings_store.set_value(s, "reseller.manual_topup_max", 1000)
            await s.commit()
        capped = await c.post(_panel(w.a, f"/customers/{mine.id}/wallet"), headers=w.h["a"], json=_adjust(1001))
        assert capped.status_code == 400 and _err(capped) == "BAD_AMOUNT"
        assert (await c.post(_panel(w.a, f"/customers/{mine.id}/wallet"), headers=w.h["a"], json=_adjust(1000))).status_code == 200


# --- profile, branding, reports -------------------------------------------------------------------------------------


async def test_profile_reports_debt_limit_and_the_main_wallet_state():
    async with api_client() as (c, maker, main):
        w = await _world(c, maker, main)
        p = (await c.get(_panel(w.a, "/profile"), headers=w.h["a"])).json()
        assert (p["store_id"], p["store_currency"], p["debt_limit"], p["sales_enabled"], p["api_enabled"]) == (
            str(w.a.id),
            "IRT",
            5000,
            True,
            True,
        )
        assert p["main_wallet"]["balance"] == 0 and p["main_wallet"]["currency"] == main.currency and p["main_wallet"]["debt_state"]


async def test_branding_update_is_stored_on_this_store_only_and_audited():
    async with api_client() as (c, maker, main):
        w = await _world(c, maker, main)
        r = await c.patch(
            _panel(w.a, "/branding"), headers=w.h["a"], json={"branding": {"title": "Shop A"}, "bot_messages": {"welcome": "hi"}}
        )
        assert r.json() == {"ok": True}
        from melorin.kernel.models.stores import Store

        async with maker() as s:
            a, b = await s.get(Store, w.a.id), await s.get(Store, w.b.id)
            assert a.branding == {"title": "Shop A"} and a.bot_messages == {"welcome": "hi"} and not b.branding
            assert await s.scalar(select(func.count()).select_from(AuditEvent).where(AuditEvent.action == "reseller.branding_updated")) == 1


async def test_report_groups_only_this_stores_orders_by_status():
    from _db import make_order

    async with api_client() as (c, maker, main):
        w = await _world(c, maker, main)
        async with maker() as s:
            user, product = await make_user(s), await make_product(s)
            await make_order(s, user=user, store=w.a, product=product, status="completed", total=1000, reseller_cost=600)
            await make_order(s, user=user, store=w.a, product=product, status="completed", total=2000, reseller_cost=1200)
            await make_order(s, user=user, store=w.a, product=product, status="paid", total=500, reseller_cost=300)
            await make_order(s, user=user, store=w.b, product=product, status="completed", total=999999, reseller_cost=1)
            await s.commit()
        rep = (await c.get(_panel(w.a, "/reports"), headers=w.h["a"])).json()
        rows = {r["status"]: r for r in rep["orders"]}
        assert (
            rep["currency"] == "IRT"
            and rows["completed"]["count"] == 2
            and rows["completed"]["total"] == 3000
            and rows["completed"]["reseller_cost"] == 1800
        )
        assert rows["paid"]["count"] == 1 and "refunded" not in rows


# --- API credentials ------------------------------------------------------------------------------------------------


async def test_api_key_is_shown_once_listed_without_the_secret_and_rotation_revokes_the_old_key():
    async with api_client() as (c, maker, main):
        w = await _world(c, maker, main)
        created = await c.post(_panel(w.a, "/api-credentials"), headers=w.h["a"], json={"name": "erp", "scopes": ["catalog:read"]})
        assert created.status_code == 201 and created.json()["api_key"] and "warning" in created.json()
        key_id, raw = created.json()["id"], created.json()["api_key"]
        listed = (await c.get(_panel(w.a, "/api-credentials"), headers=w.h["a"])).json()
        assert [x["id"] for x in listed] == [key_id] and raw not in str(listed) and "api_key" not in listed[0]
        rotated = await c.post(_panel(w.a, f"/api-credentials/{key_id}/rotate"), headers=w.h["a"])
        assert rotated.status_code == 200 and rotated.json()["api_key"] and rotated.json()["api_key"] != raw
        old = await c.get(f"{API}/stores/{w.a.id}/catalog", headers={"X-API-Key": raw})
        new = await c.get(f"{API}/stores/{w.a.id}/catalog", headers={"X-API-Key": rotated.json()["api_key"]})
        assert (old.status_code, _err(old)) == (401, "API_UNAUTHORIZED") and new.status_code == 200
        again = await c.post(_panel(w.a, f"/api-credentials/{key_id}/rotate"), headers=w.h["a"])
        assert again.status_code == 409 and _err(again) == "API_KEY_REVOKED"  # a revoked key cannot be rotated twice


async def test_api_key_actions_enable_disable_revoke_and_never_cross_stores():
    async with api_client() as (c, maker, main):
        w = await _world(c, maker, main)
        mine = (await c.post(_panel(w.a, "/api-credentials"), headers=w.h["a"], json={"name": "mine"})).json()["id"]
        theirs = (await c.post(_panel(w.b, "/api-credentials"), headers=w.h["b"], json={"name": "theirs"})).json()["id"]
        assert (await c.post(_panel(w.a, f"/api-credentials/{mine}/disable"), headers=w.h["a"])).json()["status"] == "disabled"
        assert (await c.post(_panel(w.a, f"/api-credentials/{mine}/activate"), headers=w.h["a"])).json()["status"] == "active"
        bad = await c.post(_panel(w.a, f"/api-credentials/{mine}/explode"), headers=w.h["a"])
        assert bad.status_code == 400 and _err(bad) == "API_ACTION_INVALID"
        cross = await c.post(_panel(w.a, f"/api-credentials/{theirs}/revoke"), headers=w.h["a"])
        assert cross.status_code == 404  # store B's key does not exist for owner A
        async with maker() as s:
            assert (await s.get(ApiCredential, __import__("uuid").UUID(theirs))).status == "active"
        assert (await c.post(_panel(w.a, f"/api-credentials/{mine}/revoke"), headers=w.h["a"])).json()["status"] == "revoked"
        assert [x["id"] for x in (await c.get(_panel(w.b, "/api-credentials"), headers=w.h["b"])).json()] == [theirs]


async def test_api_credential_creation_validates_scopes_and_rate_limit():
    async with api_client() as (c, maker, main):
        w = await _world(c, maker, main)
        r = await c.post(_panel(w.a, "/api-credentials"), headers=w.h["a"], json={"name": "x", "rate_limit_per_minute": 0})
        assert r.status_code == 422
        unknown_scope = await c.post(
            _panel(w.a, "/api-credentials"), headers=w.h["a"], json={"name": "erp", "scopes": ["admin:everything"]}
        )
        assert (unknown_scope.status_code, _err(unknown_scope)) == (400, "API_SCOPE_INVALID")
        async with maker() as s:
            assert await s.scalar(select(func.count()).select_from(ApiCredential)) == 0  # a refused request creates no key


# --- webhook endpoints ----------------------------------------------------------------------------------------------


async def test_webhook_lifecycle_secret_once_rotate_disable_and_store_isolation():
    async with api_client() as (c, maker, main):
        w = await _world(c, maker, main)
        created = await c.post(
            _panel(w.a, "/webhooks"),
            headers=w.h["a"],
            json={"url": "https://hooks.example.com/melorin", "description": "erp", "events": ["order.completed"]},
        )
        assert created.status_code == 201, created.text
        ep, secret = created.json()["id"], created.json()["secret"]
        listed = (await c.get(_panel(w.a, "/webhooks"), headers=w.h["a"])).json()
        assert [x["id"] for x in listed] == [ep] and secret not in str(listed)
        assert (await c.get(_panel(w.b, "/webhooks"), headers=w.h["b"])).json() == []
        # store B cannot see, change, rotate, test or delete store A's endpoint
        for method, path in (
            ("patch", f"/webhooks/{ep}"),
            ("post", f"/webhooks/{ep}/rotate-secret"),
            ("post", f"/webhooks/{ep}/test"),
            ("delete", f"/webhooks/{ep}"),
            ("get", f"/webhooks/{ep}/deliveries"),
        ):
            kw = {"json": {"description": "hijack"}} if method == "patch" else {}
            r = await getattr(c, method)(_panel(w.b, path), headers=w.h["b"], **kw)
            assert r.status_code == 404, (method, path)
        patched = await c.patch(
            _panel(w.a, f"/webhooks/{ep}"), headers=w.h["a"], json={"description": "new", "events": ["order.completed", "order.refunded"]}
        )
        assert patched.status_code == 200 and patched.json()["description"] == "new"
        rotated = await c.post(_panel(w.a, f"/webhooks/{ep}/rotate-secret"), headers=w.h["a"])
        assert rotated.json()["secret"] and rotated.json()["secret"] != secret
        test = await c.post(_panel(w.a, f"/webhooks/{ep}/test"), headers=w.h["a"])
        assert test.status_code == 200 and test.json()["ok"] is True
        deliveries = (await c.get(_panel(w.a, f"/webhooks/{ep}/deliveries"), headers=w.h["a"])).json()
        assert len(deliveries) == 1
        redo = await c.post(_panel(w.a, f"/webhooks/{ep}/deliveries/{test.json()['delivery_id']}/redeliver"), headers=w.h["a"])
        assert redo.status_code == 200
        assert (await c.delete(_panel(w.a, f"/webhooks/{ep}"), headers=w.h["a"])).json() == {"ok": True}
        assert (await c.get(_panel(w.a, "/webhooks"), headers=w.h["a"])).json()[0][
            "status"
        ] == "disabled"  # soft delete keeps the delivery log


async def test_webhook_urls_must_be_public_https_endpoints(monkeypatch):
    async with api_client() as (c, maker, main):
        w = await _world(c, maker, main)
        monkeypatch.setattr(webhook_svc.socket, "getaddrinfo", lambda host, *a, **k: [(2, 1, 6, "", ("10.0.0.5", 443))])
        private = await c.post(_panel(w.a, "/webhooks"), headers=w.h["a"], json={"url": "https://internal.example.com/x"})
        assert (private.status_code, _err(private)) == (400, "WEBHOOK_URL_FORBIDDEN")
        not_a_url = await c.post(_panel(w.a, "/webhooks"), headers=w.h["a"], json={"url": "not a url"})
        assert not_a_url.status_code == 422
        assert (await c.get(_panel(w.a, "/webhooks"), headers=w.h["a"])).json() == []


# --- store payment destination and review ---------------------------------------------------------------------------


async def test_payment_config_never_returns_the_secret_and_is_scoped_to_the_store():
    async with api_client() as (c, maker, main):
        w = await _world(c, maker, main)
        ok = await c.put(
            _panel(w.a, "/payment-config/manual_card"),
            headers=w.h["a"],
            json={"is_enabled": True, "public_config": {"card_number": "6037-0000"}, "secret": {"pin": "1234"}},
        )
        assert ok.json() == {"ok": True}
        rows = (await c.get(_panel(w.a, "/payment-config"), headers=w.h["a"])).json()
        assert rows == [{"provider": "manual_card", "is_enabled": True, "public_config": {"card_number": "6037-0000"}, "has_secret": True}]
        assert "1234" not in (await c.get(_panel(w.a, "/payment-config"), headers=w.h["a"])).text
        assert (await c.get(_panel(w.b, "/payment-config"), headers=w.h["b"])).json() == []
        # updating without a secret keeps the stored one
        await c.put(_panel(w.a, "/payment-config/manual_card"), headers=w.h["a"], json={"is_enabled": False, "public_config": {}})
        after = (await c.get(_panel(w.a, "/payment-config"), headers=w.h["a"])).json()[0]
        assert after["is_enabled"] is False and after["has_secret"] is True
        async with maker() as s:
            assert (
                await s.scalar(
                    select(func.count()).select_from(StorePaymentConfiguration).where(StorePaymentConfiguration.store_id == w.a.id)
                )
                == 1
            )
        unknown = await c.put(_panel(w.a, "/payment-config/not_a_gateway"), headers=w.h["a"], json={})
        assert (unknown.status_code, _err(unknown)) == (400, "GATEWAY_UNKNOWN")


async def _payment(maker, store, user, *, provider="manual_card", status="awaiting_review", amount=4000):
    async with maker() as s:
        p = Payment(
            user_id=user.id,
            store_id=store.id,
            purpose="wallet_topup",
            provider=provider,
            amount=amount,
            currency=store.currency,
            status=status,
        )
        s.add(p)
        await s.commit()
        return p


async def test_owner_reviews_only_manual_card_payments_of_his_own_store():
    async with api_client() as (c, maker, main):
        w = await _world(c, maker, main)
        cust_a = await _customer(maker, w.a, email="ca@example.com")
        cust_b = await _customer(maker, w.b, email="cb@example.com")
        mine = await _payment(maker, w.a, cust_a)
        gateway = await _payment(maker, w.a, cust_a, provider="zarinpal", status="pending")
        theirs = await _payment(maker, w.b, cust_b)
        listed = (await c.get(_panel(w.a, "/payments"), headers=w.h["a"])).json()
        assert {p["id"] for p in listed} == {str(mine.id), str(gateway.id)}
        only = (await c.get(_panel(w.a, "/payments"), headers=w.h["a"], params={"status": "awaiting_review"})).json()
        assert [p["id"] for p in only] == [str(mine.id)]
        cross = await c.post(_panel(w.a, f"/payments/{theirs.id}/review"), headers=w.h["a"], json={"approve": True})
        assert cross.status_code == 404  # store B's payment is invisible to owner A
        forbidden = await c.post(_panel(w.a, f"/payments/{gateway.id}/review"), headers=w.h["a"], json={"approve": True})
        assert forbidden.status_code == 403 and _err(forbidden) == "PAYMENT_REVIEW_FORBIDDEN"
        ok = await c.post(_panel(w.a, f"/payments/{mine.id}/review"), headers=w.h["a"], json={"approve": True, "note": "seen in my bank"})
        again = await c.post(_panel(w.a, f"/payments/{mine.id}/review"), headers=w.h["a"], json={"approve": True})
        assert ok.status_code == again.status_code == 200 and ok.json()["status"] == "succeeded"
        wallet = await _wallet(maker, cust_a.id, w.a.id)
        assert wallet.balance == 4000  # credited once, in the customer's own store wallet
        assert await _wallet(maker, cust_b.id, w.b.id) is None
        rejected = await c.post(
            _panel(w.a, f"/payments/{(await _payment(maker, w.a, cust_a)).id}/review"),
            headers=w.h["a"],
            json={"approve": False, "note": "no match"},
        )
        assert rejected.json()["status"] == "failed"


# --- pricing / bundles ----------------------------------------------------------------------------------------------


async def _catalog(maker, store, *, cost=20000, main_price=30000):
    async with maker() as s:
        product = Product(
            code="P30", name="30GB", duration_days=30, traffic_gb=30, main_price=main_price, reseller_price=cost, currency="IRT"
        )
        bundle = Bundle(name="Gold", kind_label="gold")
        panel = Panel(name="internal", kind="mock", base_url="http://x", is_enabled=True, health_status="healthy")
        s.add_all([product, bundle, panel])
        await s.flush()
        s.add_all(
            [
                BundleMember(bundle_id=bundle.id, panel_id=panel.id, sort=0),
                Server(name="srv", panel_id=panel.id),
                BundleProduct(bundle_id=bundle.id, product_id=product.id, reseller_price=cost, is_listed=True),
                StoreProduct(store_id=store.id, product_id=product.id, is_enabled=True, is_listed=True),
            ]
        )
        await s.commit()
        return product, bundle


async def test_reseller_prices_respect_the_cost_floor_and_each_store_keeps_its_own_price():
    async with api_client() as (c, maker, main):
        w = await _world(c, maker, main)
        product, bundle = await _catalog(maker, w.a)
        async with maker() as s:  # the same package is enabled for store B too
            s.add(StoreProduct(store_id=w.b.id, product_id=product.id, is_enabled=True, is_listed=True))
            await s.commit()
        table = (await c.get(_panel(w.a, "/prices"), headers=w.h["a"])).json()
        assert [row["product_id"] for row in table] == [str(product.id)]
        below = await c.put(_panel(w.a, f"/prices/{product.id}"), headers=w.h["a"], json={"customer_price": 19999})
        assert below.status_code == 422 and _err(below) == "CUSTOMER_PRICE_BELOW_COST"
        ok = await c.put(_panel(w.a, f"/prices/{product.id}"), headers=w.h["a"], json={"customer_price": 25000})
        assert ok.json() == {"ok": True, "product_id": str(product.id), "customer_price": 25000}
        async with maker() as s:
            a = await s.scalar(select(StoreProduct).where(StoreProduct.store_id == w.a.id))
            b = await s.scalar(select(StoreProduct).where(StoreProduct.store_id == w.b.id))
            assert (a.customer_price, b.customer_price) == (25000, None)  # B is untouched
        cleared = await c.put(_panel(w.a, f"/prices/{product.id}"), headers=w.h["a"], json={"customer_price": 0})
        assert cleared.json()["customer_price"] is None
        unknown = await c.put(_panel(w.a, "/prices/00000000-0000-0000-0000-000000000001"), headers=w.h["a"], json={"customer_price": 25000})
        assert unknown.status_code == 404


async def test_bundle_prices_batch_is_all_or_nothing():
    async with api_client() as (c, maker, main):
        w = await _world(c, maker, main)
        product, bundle = await _catalog(maker, w.a)
        one = await c.put(_panel(w.a, f"/bundles/{bundle.id}/prices/{product.id}"), headers=w.h["a"], json={"customer_price": 26000})
        assert one.json()["customer_price"] == 26000 and one.json()["bundle_id"] == str(bundle.id)
        below = await c.put(_panel(w.a, f"/bundles/{bundle.id}/prices/{product.id}"), headers=w.h["a"], json={"customer_price": 100})
        assert below.status_code == 422
        bad_batch = await c.post(
            _panel(w.a, "/prices/batch"),
            headers=w.h["a"],
            json={
                "items": [
                    {"product_id": str(product.id), "customer_price": 30000},
                    {"bundle_id": str(bundle.id), "product_id": str(product.id), "customer_price": 5},
                ]
            },
        )
        assert (bad_batch.status_code, _err(bad_batch)) == (422, "PRICES_INVALID")
        async with maker() as s:
            sp = await s.scalar(select(StoreProduct).where(StoreProduct.store_id == w.a.id))
            assert sp.customer_price is None  # the valid first item was NOT saved because the second was refused
        good = await c.post(
            _panel(w.a, "/prices/batch"),
            headers=w.h["a"],
            json={
                "items": [
                    {"product_id": str(product.id), "customer_price": 30000},
                    {"bundle_id": str(bundle.id), "product_id": str(product.id), "customer_price": 28000},
                ]
            },
        )
        assert good.status_code == 200 and good.json()["ok"] is True and good.json()["changed"] >= 1 and good.json()["prices"]
        assert (await c.post(_panel(w.a, "/prices/batch"), headers=w.h["a"], json={"items": []})).status_code == 422


async def test_bundle_list_has_one_row_per_bundle_and_never_leaks_another_stores_switch():
    """Regression (phase 4.13): the outer join on StoreBundle had no store filter, so with N linked stores every bundle was
    listed N times and a store saw the on/off switch of whichever store's row came first."""
    async with api_client() as (c, maker, main):
        w = await _world(c, maker, main)
        product, bundle = await _catalog(maker, w.a)
        async with maker() as s:  # what reseller linking does in production: one StoreBundle row per (store, bundle)
            from melorin.kernel.models.bundles import StoreBundle

            s.add_all(
                [
                    StoreBundle(store_id=w.a.id, bundle_id=bundle.id, is_enabled=False),
                    StoreBundle(store_id=w.b.id, bundle_id=bundle.id, is_enabled=True),
                ]
            )
            await s.commit()
        a = (await c.get(_panel(w.a, "/bundles"), headers=w.h["a"])).json()
        b = (await c.get(_panel(w.b, "/bundles"), headers=w.h["b"])).json()
        assert [(x["id"], x["is_enabled"]) for x in a] == [(str(bundle.id), False)]
        assert [(x["id"], x["is_enabled"]) for x in b] == [(str(bundle.id), True)]


async def test_reseller_can_close_a_bundle_for_his_own_store_only():
    async with api_client() as (c, maker, main):
        w = await _world(c, maker, main)
        product, bundle = await _catalog(maker, w.a)
        listed = (await c.get(_panel(w.a, "/bundles"), headers=w.h["a"])).json()
        assert [(b["id"], b["is_enabled"]) for b in listed] == [(str(bundle.id), True)]
        off = await c.put(_panel(w.a, f"/bundles/{bundle.id}"), headers=w.h["a"], json={"is_enabled": False})
        assert off.json() == {"ok": True, "is_enabled": False}
        assert (await c.get(_panel(w.a, "/bundles"), headers=w.h["a"])).json()[0]["is_enabled"] is False
        assert (await c.get(_panel(w.b, "/bundles"), headers=w.h["b"])).json()[0]["is_enabled"] is True
        assert (await c.put(_panel(w.a, "/bundles/00000000-0000-0000-0000-000000000001"), headers=w.h["a"], json={})).status_code == 404


# --- the versioned reseller API (API key, channel "api") ------------------------------------------------------------


async def _key(maker, store, owner, scopes, **kw):
    async with maker() as s:
        body = types.SimpleNamespace(
            name="k", scopes=scopes, activate=True, rate_limit_per_minute=600, ip_allowlist=kw.get("ips"), expires_at=None
        )
        _, raw = await api_keys.create(s, store, owner, body)
        await s.commit()
        return raw


async def test_reseller_api_scopes_store_binding_and_data_isolation():
    async with api_client() as (c, maker, main):
        w = await _world(c, maker, main)
        product, bundle = await _catalog(maker, w.a)
        async with maker() as s:
            await s.execute(StoreProduct.__table__.update().where(StoreProduct.store_id == w.a.id).values(customer_price=25000))
            await s.commit()
        mine = await _customer(maker, w.a, email="mine@example.com")
        await _customer(maker, w.b, email="theirs@example.com")
        key = await _key(maker, w.a, w.owner_a, ["catalog:read", "customers:read", "orders:read", "reports:read", "customers:wallet:write"])
        h = {"X-API-Key": key}
        catalog = (await c.get(f"{API}/stores/{w.a.id}/catalog", headers=h)).json()
        assert [(p["code"], p["price"], p["currency"]) for p in catalog] == [("P30", 25000, "IRT")]
        assert [x["user_id"] for x in (await c.get(f"{API}/stores/{w.a.id}/customers", headers=h)).json()] == [str(mine.id)]
        assert (await c.get(f"{API}/stores/{w.a.id}/orders", headers=h)).json() == []
        assert (await c.get(f"{API}/stores/{w.a.id}/reports", headers=h)).json()["orders"] == []
        topup = await c.post(f"{API}/stores/{w.a.id}/customers/{mine.id}/wallet", headers=h, json=_adjust(1500, key="api-key-0001"))
        assert topup.status_code == 200 and topup.json()["balance"] == 1500
        async with maker() as s:
            row = await s.scalar(select(AuditEvent).where(AuditEvent.action == "reseller.customer_wallet_adjusted"))
            assert row.actor_type == "api"  # the ledger knows the change came through the API, not the panel
        # the key of store A opens store B's URL for nobody, with or without the right scope
        for path in ("/catalog", "/customers", "/orders", "/reports"):
            cross = await c.get(f"{API}/stores/{w.b.id}{path}", headers=h)
            assert (cross.status_code, _err(cross)) == (403, "API_STORE_ISOLATION"), path
        for headers in ({}, {"X-API-Key": "mk_live_not-a-key"}):
            r = await c.get(f"{API}/stores/{w.a.id}/catalog", headers=headers)
            assert (r.status_code, _err(r)) == (401, "API_UNAUTHORIZED")


async def test_reseller_api_key_scope_is_enforced_per_route_and_disabled_keys_open_nothing():
    async with api_client() as (c, maker, main):
        w = await _world(c, maker, main)
        mine = await _customer(maker, w.a, email="mine@example.com")
        read_only = {"X-API-Key": await _key(maker, w.a, w.owner_a, ["catalog:read"])}
        assert (await c.get(f"{API}/stores/{w.a.id}/catalog", headers=read_only)).status_code == 200
        for path in ("/customers", "/orders", "/reports"):
            r = await c.get(f"{API}/stores/{w.a.id}{path}", headers=read_only)
            assert (r.status_code, _err(r)) == (403, "API_SCOPE_FORBIDDEN"), path
        write = await c.post(f"{API}/stores/{w.a.id}/customers/{mine.id}/wallet", headers=read_only, json=_adjust(100))
        assert (write.status_code, _err(write)) == (403, "API_SCOPE_FORBIDDEN") and (await _wallet(maker, mine.id, w.a.id)) is None
        for state in ("disabled", "revoked"):
            async with maker() as s:
                (await s.scalar(select(ApiCredential).where(ApiCredential.store_id == w.a.id))).status = state
                await s.commit()
            r = await c.get(f"{API}/stores/{w.a.id}/catalog", headers=read_only)
            assert (r.status_code, _err(r)) == (401, "API_UNAUTHORIZED"), state


async def test_reseller_api_is_closed_when_the_store_has_the_api_switched_off():
    async with api_client() as (c, maker, main):
        w = await _world(c, maker, main, api_enabled=False)
        key = await _key(maker, w.a, w.owner_a, ["catalog:read"])
        r = await c.get(f"{API}/stores/{w.a.id}/catalog", headers={"X-API-Key": key})
        assert (r.status_code, _err(r)) == (403, "API_DISABLED")


async def test_reseller_api_honours_the_ip_allowlist():
    async with api_client() as (c, maker, main):
        w = await _world(c, maker, main)
        key = await _key(maker, w.a, w.owner_a, ["catalog:read"], ips=["198.51.100.7"])
        r = await c.get(f"{API}/stores/{w.a.id}/catalog", headers={"X-API-Key": key})
        assert (r.status_code, _err(r)) == (403, "API_IP_FORBIDDEN")  # the in-process test client is not the allowed address


async def test_ledger_entries_of_a_manual_topup_balance_to_zero_inside_the_store_currency():
    async with api_client() as (c, maker, main):
        w = await _world(c, maker, main)
        cust = await _customer(maker, w.a, email="mine@example.com")
        await c.post(_panel(w.a, f"/customers/{cust.id}/wallet"), headers=w.h["a"], json=_adjust(1234))
        async with maker() as s:
            rows = (await s.scalars(select(LedgerEntry))).all()
            assert rows and sum(r.amount for r in rows) == 0  # double entry: the contra is the store's own reseller-cash account
