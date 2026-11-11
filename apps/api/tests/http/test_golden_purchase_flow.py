"""T-R06 / T-G01: the golden path over the real HTTP app, end to end.

login -> gateway top-up (callback credits the wallet) -> wallet purchase -> provisioning -> order completed with a
delivered account. Only the payment gateway and the VPN panel are faked; routing, validation, ledger, order state
machine and provisioning run for real against the per-test schema (SQLite, or PostgreSQL with ``TEST_PG_URL``).
"""

from __future__ import annotations

import datetime as dt
import itertools
import uuid

import pytest

from _db import make_product, pg_url
from _http import PASSWORD, add_user, api_client
from melorin.core import codes
from melorin.kernel.models.catalog import StoreProduct
from melorin.kernel.models.bundles import Bundle, BundleMember, BundleProduct
from melorin.kernel.models.payments import Payment
from melorin.kernel.models.stores import StorePaymentConfiguration
from melorin.kernel.models.vpn import Panel, Server
from melorin.modules.orders import provisioning as vpn
from melorin.modules.payments.adapters import registry
from melorin.modules.payments.adapters.base import CallbackResult, IntentResult
from melorin.modules.vpn.adapters.base import PanelAccount

AUTH = "/api/v1/auth"


class _Gateway:
    name = "golden_gw"
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


class _Panel:
    kind = "golden"

    def __init__(self):
        self.created = []

    async def create_account(self, spec):
        self.created.append(spec)
        return PanelAccount(
            ref=f"ref-{spec.username}",
            username=spec.username,
            status="active",
            expire_at=spec.expire_at or dt.datetime.now(dt.UTC) + dt.timedelta(days=30),
            traffic_limit_bytes=spec.traffic_bytes,
            traffic_used_bytes=0,
            subscription_url=f"https://sub.test/{spec.username}",
            links=["vless://golden"],
        )

    async def get_account(self, username):
        return None

    async def close(self):
        return None


@pytest.fixture
def world(monkeypatch):
    gw, panel = _Gateway(), _Panel()
    monkeypatch.setitem(registry._ADAPTERS, gw.name, gw)
    monkeypatch.setattr(vpn, "build_adapter", lambda _panel, _server=None: panel)
    if pg_url() is None:  # SQLite has no ``nextval``; on PostgreSQL the real sequence runs (created by tests/_db.py)
        counter = itertools.count(1)

        async def next_code(session, sequence):
            return f"T{next(counter):05d}"

        monkeypatch.setattr(codes, "next_code", next_code)
    return panel


async def test_signup_topup_purchase_and_provisioning_end_to_end(world):
    price = 2_000
    async with api_client() as (c, maker, main):
        # catalogue + capacity (what an operator configured before the shop opens)
        async with maker() as s:
            product = await make_product(s, price=price)
            group = Bundle(name="G", selection_mode="automatic", is_enabled=True)
            panel = Panel(name="P1", kind="mock", base_url="http://x", is_enabled=True, health_status="healthy")
            s.add_all([group, panel])
            await s.flush()
            s.add_all(
                [BundleMember(bundle_id=group.id, panel_id=panel.id, sort=0), BundleProduct(bundle_id=group.id, product_id=product.id)]
            )
            s.add(Server(name="S1", panel_id=panel.id))
            s.add(StoreProduct(store_id=main.id, product_id=product.id, is_enabled=True))
            s.add(StorePaymentConfiguration(store_id=main.id, provider="golden_gw", is_enabled=True, public_config={}))
            await s.commit()
            product_id, bundle_id = product.id, group.id

        # sign in
        await add_user(maker, email="buyer@example.com")
        login = await c.post(f"{AUTH}/password/login", json={"email": "buyer@example.com", "password": PASSWORD})
        assert login.status_code == 200, login.text
        sid = login.json()["store_id"]
        auth = {"Authorization": f"Bearer {login.json()['access_token']}"}

        # top-up through the gateway: nothing is credited until the verified callback arrives
        pay = (
            await c.post(
                f"/api/v1/stores/{sid}/wallet/topups",
                json={"amount": price, "provider": "golden_gw"},
                headers={**auth, "Idempotency-Key": "golden-topup-1"},
            )
        ).json()
        assert (await c.get(f"/api/v1/stores/{sid}/wallet", headers=auth)).json()["balance"] == 0
        async with maker() as s:
            ref = (await s.get(Payment, uuid.UUID(pay["id"]))).external_ref
        cb = await c.get(f"/api/v1/payments/callbacks/golden_gw?pid={pay['id']}&Status=OK&Authority={ref}")
        assert cb.status_code == 303 and cb.headers["location"].endswith("status=succeeded")
        assert (await c.get(f"/api/v1/stores/{sid}/wallet", headers=auth)).json()["balance"] == price

        # purchase with the wallet; the same Idempotency-Key never charges twice
        body = {"product_id": str(product_id), "bundle_id": str(bundle_id), "payment_method": "wallet"}
        order = await c.post(f"/api/v1/stores/{sid}/orders", json=body, headers={**auth, "Idempotency-Key": "golden-order-1"})
        assert order.status_code == 201, order.text
        replay = await c.post(f"/api/v1/stores/{sid}/orders", json=body, headers={**auth, "Idempotency-Key": "golden-order-1"})
        assert replay.status_code in (200, 201) and replay.json()["id"] == order.json()["id"]
        assert (await c.get(f"/api/v1/stores/{sid}/wallet", headers=auth)).json()["balance"] == 0

        # provisioning (the worker's job) delivers exactly one account
        async with maker() as s:
            assert await vpn.provision_order(s, uuid.UUID(order.json()["id"])) == "completed"
            await s.commit()
        final = await c.get(f"/api/v1/stores/{sid}/orders/{order.json()['id']}", headers=auth)
        assert final.status_code == 200 and final.json()["status"] == "completed"
        assert len(world.created) == 1
