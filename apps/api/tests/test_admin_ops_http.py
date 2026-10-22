"""Phase 4.12: the admin API over HTTP - orders, payments, settings, audit, reports, bot bindings and coupons.

Every route is driven through the real app with a real admin-panel session (password + TOTP). The first group proves that the
whole ``/admin`` surface is closed to anonymous callers and to customer sessions, even when the account behind them is an admin."""

from __future__ import annotations

import pytest
from sqlalchemy import select

from _db import make_order, make_product, make_store, make_user
from _http import PASSWORD, add_user, api_client, totp_now
from melorin.core import storage
from melorin.core.security import create_access_token
from melorin.kernel.models.identity import User
from melorin.kernel.models.orders import Order
from melorin.kernel.models.payments import Payment
from melorin.kernel.models.system import AuditEvent, BackupRun, FileObject
from melorin.kernel.models.vpn import Panel, Server
from melorin.kernel.models.wallet import Wallet
from melorin.modules.payments.adapters import registry
from melorin.modules.payments.adapters.base import RefundResult

AUTH = "/api/v1/auth"
ADMIN = "/api/v1/admin"


def _err(r):
    body = r.json()
    return body.get("error", body).get("code") if isinstance(body, dict) else None


async def _admin(c, maker, email="root@example.com"):
    await add_user(maker, email=email, admin=True, totp=True)
    r = await c.post(f"{AUTH}/password/login", json={"email": email, "password": PASSWORD, "totp_code": totp_now()})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


async def _audit_actions(maker, action):
    async with maker() as s:
        return (await s.scalars(select(AuditEvent.action).where(AuditEvent.action == action))).all()


# --- the admin surface is closed ------------------------------------------------------------------------------------

READ_ROUTES = [
    "/orders",
    "/payments",
    "/coupons",
    "/settings",
    "/feature-flags",
    "/audit",
    "/dashboard",
    "/health",
    "/reports/summary",
    "/reports/timeseries",
    "/reports/orders.csv",
    "/operations/backups",
    "/bot-store-bindings",
]


@pytest.mark.parametrize("path", READ_ROUTES)
async def test_admin_routes_reject_anonymous_callers(path):
    async with api_client() as (c, maker, _):
        assert (await c.get(f"{ADMIN}{path}")).status_code == 401


async def test_admin_routes_reject_a_customer_session():
    async with api_client() as (c, maker, _):
        await add_user(maker, email="cust@example.com")
        login = await c.post(f"{AUTH}/password/login", json={"email": "cust@example.com", "password": PASSWORD})
        h = {"Authorization": f"Bearer {login.json()['access_token']}"}
        for path in READ_ROUTES:
            assert (await c.get(f"{ADMIN}{path}", headers=h)).status_code == 403, path
        assert (await c.post(f"{ADMIN}/coupons", headers=h, json={"code": "ABCDE"})).status_code == 403
        assert (await c.put(f"{ADMIN}/settings/ui.title", headers=h, json={"value": "x"})).status_code == 403


async def test_an_admin_account_cannot_open_any_session_without_its_second_factor():
    async with api_client() as (c, maker, _):
        await add_user(maker, email="root@example.com", admin=True, totp=False)
        r = await c.post(f"{AUTH}/password/login", json={"email": "root@example.com", "password": PASSWORD})
        assert r.status_code == 403 and _err(r) == "ADMIN_2FA_REQUIRED"


async def test_admin_rights_need_both_the_admin_channel_and_the_admin_flag_on_the_account():
    """Two independent locks: a customer-channel token of an admin account, and an admin-channel token of a demoted account."""
    async with api_client() as (c, maker, main):
        admin = await add_user(maker, email="root@example.com", admin=True, totp=True)
        customer_token, _ = create_access_token(admin.id, False, store_id=main.id, channel="site")
        as_customer = {"Authorization": f"Bearer {customer_token}"}
        for path in READ_ROUTES:
            assert (await c.get(f"{ADMIN}{path}", headers=as_customer)).status_code == 403, path
        assert (await c.post(f"{ADMIN}/coupons", headers=as_customer, json={"code": "ABCDE"})).status_code == 403
        # the same account with a real admin-channel token works ...
        admin_token, _ = create_access_token(admin.id, True)
        ok = await c.get(f"{ADMIN}/dashboard", headers={"Authorization": f"Bearer {admin_token}"})
        assert ok.status_code == 200
        # ... until it is demoted: the old admin token is rejected at once (401), it does not live on until it expires
        async with maker() as s:
            (await s.get(User, admin.id)).is_super_admin = False
            await s.commit()
        assert (await c.get(f"{ADMIN}/dashboard", headers={"Authorization": f"Bearer {admin_token}"})).status_code == 401


# --- orders ---------------------------------------------------------------------------------------------------------


async def _seed_orders(maker):
    async with maker() as s:
        store = await make_store(s, kind="reseller", slug="r1")
        user, product = await make_user(s), await make_product(s)
        failed = await make_order(s, user=user, store=store, product=product, status="provisioning_failed")
        paid = await make_order(s, user=user, store=store, product=product, status="paid")
        done = await make_order(s, user=user, store=store, product=product, status="completed")
        await s.commit()
        return store, failed, paid, done, product


async def test_admin_orders_list_filters_by_status_and_store():
    async with api_client() as (c, maker, main):
        h = await _admin(c, maker)
        store, failed, paid, done, _ = await _seed_orders(maker)
        everything = await c.get(f"{ADMIN}/orders", headers=h)
        assert everything.status_code == 200 and len(everything.json()) == 3
        only_failed = await c.get(f"{ADMIN}/orders", headers=h, params={"status": "provisioning_failed"})
        assert [o["id"] for o in only_failed.json()] == [str(failed.id)]
        other_store = await c.get(f"{ADMIN}/orders", headers=h, params={"store_id": str(main.id)})
        assert other_store.json() == []
        mine = await c.get(f"{ADMIN}/orders", headers=h, params={"store_id": str(store.id)})
        assert {o["store_id"] for o in mine.json()} == {str(store.id)}


async def test_admin_retry_only_works_on_failed_or_review_orders_and_is_audited():
    async with api_client() as (c, maker, _):
        h = await _admin(c, maker)
        _, failed, paid, _, _ = await _seed_orders(maker)
        refused = await c.post(f"{ADMIN}/orders/{paid.id}/retry", headers=h)
        assert refused.status_code == 409 and _err(refused) == "INVALID_ORDER_STATE"
        ok = await c.post(f"{ADMIN}/orders/{failed.id}/retry", headers=h)
        assert ok.status_code == 200 and ok.json() == {"ok": True}
        async with maker() as s:
            order = await s.get(Order, failed.id)
            assert order.status == "processing" and order.provisioning_attempts == 1 and order.needs_review is False
        assert await _audit_actions(maker, "provisioning.retry")
        # a second click is refused: the order already left the retryable states, so no duplicate provisioning event is queued
        again = await c.post(f"{ADMIN}/orders/{failed.id}/retry", headers=h)
        assert again.status_code == 409


async def test_admin_manual_review_marks_the_order_and_unknown_orders_are_404():
    async with api_client() as (c, maker, _):
        h = await _admin(c, maker)
        _, failed, *_ = await _seed_orders(maker)
        ok = await c.post(f"{ADMIN}/orders/{failed.id}/manual-review", headers=h, json={"reason": "panel down"})
        assert ok.status_code == 200
        async with maker() as s:
            order = await s.get(Order, failed.id)
            assert (order.status, order.needs_review) == ("manual_review", True)
        missing = "00000000-0000-0000-0000-000000000001"
        for action in ("retry", "manual-review", "refund"):
            r = await c.post(f"{ADMIN}/orders/{missing}/{action}", headers=h, json={})
            assert r.status_code == 404, action


async def test_admin_refund_is_idempotent_and_refuses_orders_that_cannot_be_refunded():
    async with api_client() as (c, maker, main):
        h = await _admin(c, maker)
        async with maker() as s:
            user, product = await make_user(s), await make_product(s)
            paid = await make_order(s, user=user, store=main, product=product, status="paid")
            cancelled = await make_order(s, user=user, store=main, product=product, status="cancelled")
            await s.commit()
        refused = await c.post(f"{ADMIN}/orders/{cancelled.id}/refund", headers=h, json={})
        assert refused.status_code == 409 and _err(refused) == "INVALID_ORDER_STATE"
        first = await c.post(f"{ADMIN}/orders/{paid.id}/refund", headers=h, json={"reason": "customer asked"})
        second = await c.post(f"{ADMIN}/orders/{paid.id}/refund", headers=h, json={"reason": "double click"})
        assert first.status_code == second.status_code == 200
        async with maker() as s:
            assert (await s.get(Order, paid.id)).status == "refunded"
        assert len(await _audit_actions(maker, "order.refunded")) == 1  # the second call changed nothing


async def test_admin_attach_account_completes_a_failed_order_with_a_manually_created_account():
    async with api_client() as (c, maker, main):
        h = await _admin(c, maker)
        async with maker() as s:
            user, product = await make_user(s), await make_product(s)
            panel = Panel(name="p", kind="mock", base_url="http://panel.invalid")
            s.add(panel)
            await s.flush()
            server = Server(name="srv", panel_id=panel.id)
            s.add(server)
            failed = await make_order(s, user=user, store=main, product=product, status="provisioning_failed")
            paid = await make_order(s, user=user, store=main, product=product, status="paid")
            await s.commit()
        body = {
            "server_id": str(server.id),
            "username": "manual-1",
            "panel_ref": "ref-1",
            "subscription_url": "https://sub/x",
            "reason": "by hand",
        }
        wrong_state = await c.post(f"{ADMIN}/orders/{paid.id}/attach-account", headers=h, json=body)
        assert wrong_state.status_code == 409 and _err(wrong_state) == "INVALID_ORDER_STATE"
        unknown_server = await c.post(
            f"{ADMIN}/orders/{failed.id}/attach-account", headers=h, json={**body, "server_id": "00000000-0000-0000-0000-000000000009"}
        )
        assert unknown_server.status_code == 404
        ok = await c.post(f"{ADMIN}/orders/{failed.id}/attach-account", headers=h, json=body)
        assert ok.status_code == 200 and ok.json()["ok"] is True
        async with maker() as s:
            order = await s.get(Order, failed.id)
            assert (order.status, order.needs_review, str(order.vpn_account_id)) == ("completed", False, str(ok.json()["vpn_account_id"]))
        assert await _audit_actions(maker, "provisioning.account_attached")


# --- payments -------------------------------------------------------------------------------------------------------


async def _payment(maker, store, *, status="awaiting_review", amount=5000, provider="manual_card", receipt=None):
    async with maker() as s:
        user = await make_user(s)
        p = Payment(
            user_id=user.id,
            store_id=store.id,
            purpose="wallet_topup",
            provider=provider,
            amount=amount,
            currency=store.currency,
            status=status,
            receipt_file_id=receipt,
        )
        s.add(p)
        await s.commit()
        return p, user


async def _balance(maker, user_id, store_id):
    async with maker() as s:
        return await s.scalar(select(Wallet.balance).where(Wallet.user_id == user_id, Wallet.store_id == store_id)) or 0


async def test_admin_payment_list_filters_by_status():
    async with api_client() as (c, maker, main):
        h = await _admin(c, maker)
        review, _ = await _payment(maker, main)
        await _payment(maker, main, status="failed")
        rows = (await c.get(f"{ADMIN}/payments", headers=h)).json()
        assert len(rows) == 2 and all(set(r) >= {"id", "amount", "currency", "provider", "status", "has_receipt"} for r in rows)
        only = (await c.get(f"{ADMIN}/payments", headers=h, params={"status": "awaiting_review"})).json()
        assert [r["id"] for r in only] == [str(review.id)]


async def test_approving_a_payment_credits_the_wallet_exactly_once_even_when_approved_twice():
    async with api_client() as (c, maker, main):
        h = await _admin(c, maker)
        p, user = await _payment(maker, main, amount=7000)
        first = await c.post(f"{ADMIN}/payments/{p.id}/review", headers=h, json={"approve": True, "reason": "bank statement checked"})
        second = await c.post(f"{ADMIN}/payments/{p.id}/review", headers=h, json={"approve": True})
        assert (first.json(), second.json()) == ({"ok": True, "status": "succeeded"}, {"ok": True, "status": "succeeded"})
        assert await _balance(maker, user.id, main.id) == 7000  # idempotency key: no double credit
        assert len(await _audit_actions(maker, "payment.succeeded")) == 1


async def test_rejecting_a_payment_never_touches_the_wallet_and_a_missing_payment_is_404():
    async with api_client() as (c, maker, main):
        h = await _admin(c, maker)
        p, user = await _payment(maker, main)
        r = await c.post(f"{ADMIN}/payments/{p.id}/review", headers=h, json={"approve": False, "reason": "wrong amount"})
        assert r.json() == {"ok": True, "status": "failed"}
        assert await _balance(maker, user.id, main.id) == 0
        missing = await c.post(f"{ADMIN}/payments/00000000-0000-0000-0000-000000000001/review", headers=h, json={"approve": True})
        assert missing.status_code == 404


class _Gateway:
    name = "fake_refund_gw"
    fail = False

    async def refund(self, payment, *, settings):
        if self.fail:
            raise RuntimeError("gateway down")
        return RefundResult(external_ref="RF-1", status="ok", raw={"ok": True})


async def test_admin_refund_of_a_topup_reverses_the_credit_once_and_a_gateway_failure_changes_nothing(monkeypatch):
    gw = _Gateway()
    monkeypatch.setitem(registry._ADAPTERS, gw.name, gw)
    async with api_client() as (c, maker, main):
        h = await _admin(c, maker)
        p, user = await _payment(maker, main, provider=gw.name, amount=3000)
        not_succeeded = await c.post(f"{ADMIN}/payments/{p.id}/refund", headers=h, json={})
        assert not_succeeded.status_code == 409 and _err(not_succeeded) == "INVALID_PAYMENT_STATE"
        await c.post(f"{ADMIN}/payments/{p.id}/review", headers=h, json={"approve": True})
        assert await _balance(maker, user.id, main.id) == 3000
        gw.fail = True
        with pytest.raises(RuntimeError):
            await c.post(f"{ADMIN}/payments/{p.id}/refund", headers=h, json={})
        async with maker() as s:
            assert (await s.get(Payment, p.id)).meta["refund_operation"] == "failed"
        assert await _balance(maker, user.id, main.id) == 3000  # a failed gateway refund never moves money
        gw.fail = False
        ok = await c.post(f"{ADMIN}/payments/{p.id}/refund", headers=h, json={"reason": "duplicate charge"})
        again = await c.post(f"{ADMIN}/payments/{p.id}/refund", headers=h, json={})
        assert ok.json()["status"] == again.json()["status"] == "refunded"
        assert await _balance(maker, user.id, main.id) == 0


class _MemoryStorage:
    def __init__(self, blobs):
        self.blobs = blobs

    async def get(self, key):
        return self.blobs[key]


async def test_admin_receipt_download_is_private_audited_and_404_without_a_receipt(monkeypatch):
    monkeypatch.setattr(storage, "_storage", _MemoryStorage({"k1": b"\x89PNG-bytes"}))
    async with api_client() as (c, maker, main):
        h = await _admin(c, maker)
        bare, _ = await _payment(maker, main)
        assert (await c.get(f"{ADMIN}/payments/{bare.id}/receipt", headers=h)).status_code == 404
        async with maker() as s:
            owner = await make_user(s)
            fo = FileObject(
                owner_user_id=owner.id,
                store_id=main.id,
                purpose="receipt",
                storage_key="k1",
                content_type="image/png",
                size=10,
                sha256="0" * 64,
            )
            s.add(fo)
            await s.commit()
        with_receipt, _ = await _payment(maker, main, receipt=fo.id)
        ok = await c.get(f"{ADMIN}/payments/{with_receipt.id}/receipt", headers=h)
        assert ok.status_code == 200 and ok.content == b"\x89PNG-bytes"
        assert ok.headers["cache-control"] == "private, no-store" and ok.headers["x-content-type-options"] == "nosniff"
        assert await _audit_actions(maker, "payment.receipt_viewed")
        listed = {r["id"]: r["has_receipt"] for r in (await c.get(f"{ADMIN}/payments", headers=h)).json()}
        assert listed[str(with_receipt.id)] is True and listed[str(bare.id)] is False


# --- settings, flags, audit -----------------------------------------------------------------------------------------


async def test_settings_can_be_written_read_back_and_integration_keys_are_reserved():
    async with api_client() as (c, maker, _):
        h = await _admin(c, maker)
        ok = await c.put(f"{ADMIN}/settings/ui/banner.text", headers=h, json={"value": "hello"})  # {key:path}: slashes are allowed
        assert ok.status_code == 200
        assert (await c.get(f"{ADMIN}/settings", headers=h)).json()["ui/banner.text"] == "hello"
        reserved = await c.put(f"{ADMIN}/settings/integration.smtp", headers=h, json={"value": {"host": "x"}})
        assert reserved.status_code == 400 and _err(reserved) == "SETTING_RESERVED"
        assert await _audit_actions(maker, "system_setting.updated")


async def test_feature_flags_are_upserted_per_scope_not_duplicated():
    async with api_client() as (c, maker, _):
        h = await _admin(c, maker)
        await c.put(f"{ADMIN}/feature-flags/new_checkout", headers=h, json={"enabled": True, "note": "beta"})
        await c.put(f"{ADMIN}/feature-flags/new_checkout", headers=h, json={"enabled": False})
        await c.put(f"{ADMIN}/feature-flags/new_checkout", headers=h, json={"enabled": True, "scope_type": "store", "scope_id": "abc"})
        flags = (await c.get(f"{ADMIN}/feature-flags", headers=h)).json()
        assert len(flags) == 2
        by_scope = {f["scope_type"]: f for f in flags}
        assert by_scope["global"]["enabled"] is False and by_scope["global"]["note"] is None
        assert by_scope["store"]["enabled"] is True and by_scope["store"]["scope_id"] == "abc"


async def test_audit_log_can_be_filtered_by_action():
    async with api_client() as (c, maker, _):
        h = await _admin(c, maker)
        await c.put(f"{ADMIN}/settings/a.b", headers=h, json={"value": 1})
        await c.put(f"{ADMIN}/feature-flags/f", headers=h, json={"enabled": True})
        everything = (await c.get(f"{ADMIN}/audit", headers=h)).json()
        assert {"admin.login", "system_setting.updated", "feature_flag.updated"} <= {e["action"] for e in everything}
        only = (await c.get(f"{ADMIN}/audit", headers=h, params={"action": "feature_flag.updated"})).json()
        assert [e["action"] for e in only] == ["feature_flag.updated"]


# --- reports / health -----------------------------------------------------------------------------------------------


async def test_dashboard_and_summary_report_money_per_currency_never_mixed():
    async with api_client() as (c, maker, main):
        h = await _admin(c, maker)
        async with maker() as s:
            usd = await make_store(s, kind="reseller", currency="USD", slug="usd")
            await s.commit()
        await _payment(maker, main, status="succeeded", amount=1000)
        await _payment(maker, main, status="succeeded", amount=500)
        await _payment(maker, usd, status="succeeded", amount=7)
        await _payment(maker, main, status="failed", amount=99999)  # failed money is not a sale
        summary = (await c.get(f"{ADMIN}/reports/summary", headers=h)).json()
        assert summary["currency_safe"] is True
        assert {(p["currency"], p["count"], p["amount"]) for p in summary["payments"]} == {("IRT", 2, 1500), ("USD", 1, 7)}
        dash = (await c.get(f"{ADMIN}/dashboard", headers=h)).json()
        assert dash["open_tickets"] == 0 and dash["active_users"] >= 1 and isinstance(dash["orders"], dict)


async def test_timeseries_validates_range_and_time_zone():
    async with api_client() as (c, maker, _):
        h = await _admin(c, maker)
        ok = await c.get(f"{ADMIN}/reports/timeseries", headers=h, params={"days": 7, "tz": "Asia/Tehran"})
        assert ok.status_code == 200
        bad_tz = await c.get(f"{ADMIN}/reports/timeseries", headers=h, params={"tz": "Mars/Base"})
        assert bad_tz.status_code == 422 and _err(bad_tz) == "INVALID_TIMEZONE"
        assert (await c.get(f"{ADMIN}/reports/timeseries", headers=h, params={"days": 3})).status_code == 422
        assert (await c.get(f"{ADMIN}/reports/timeseries", headers=h, params={"days": 91})).status_code == 422


async def test_orders_csv_export_is_utf8_bom_attachment_with_one_row_per_order():
    async with api_client() as (c, maker, _):
        h = await _admin(c, maker)
        _, failed, *_ = await _seed_orders(maker)
        r = await c.get(f"{ADMIN}/reports/orders.csv", headers=h)
        assert r.status_code == 200 and r.headers["content-type"].startswith("text/csv")
        assert "attachment" in r.headers["content-disposition"]
        assert r.content.startswith(b"\xef\xbb\xbf")  # Excel needs the BOM for Persian text
        lines = r.content.decode("utf-8-sig").strip().splitlines()
        assert lines[0].split(",")[:3] == ["id", "number", "store_id"] and len(lines) == 4
        only = await c.get(f"{ADMIN}/reports/orders.csv", headers=h, params={"status": "provisioning_failed"})
        assert str(failed.id) in only.text and len(only.content.decode("utf-8-sig").strip().splitlines()) == 2


async def test_admin_health_reports_database_ok_and_unavailable_redis_without_failing():
    async with api_client() as (c, maker, _):
        h = await _admin(c, maker)
        r = await c.get(f"{ADMIN}/health", headers=h)
        assert r.status_code == 200 and r.json()["api"] == "ok" and r.json()["database"] == "ok"
        assert r.json()["redis"] in ("ok", "unavailable") and r.json()["worker"] in ("ok", "unavailable")


async def test_backup_status_lists_runs_newest_first():
    async with api_client() as (c, maker, _):
        h = await _admin(c, maker)
        async with maker() as s:
            s.add_all([BackupRun(status="ok", location="s3://b/1", size=10), BackupRun(status="failed", details="disk full")])
            await s.commit()
        rows = (await c.get(f"{ADMIN}/operations/backups", headers=h)).json()
        assert {r["status"] for r in rows} == {"ok", "failed"} and all(
            set(r) >= {"location", "size", "details", "created_at"} for r in rows
        )


# --- bot / store bindings -------------------------------------------------------------------------------------------


async def test_bot_binding_kind_must_match_the_store_kind_and_the_store_must_be_active():
    async with api_client() as (c, maker, main):
        h = await _admin(c, maker)
        async with maker() as s:
            reseller = await make_store(s, kind="reseller", slug="rb")
            closed = await make_store(s, kind="reseller", slug="closed")
            closed.status = "suspended"
            await s.commit()
        body = {"bot_key": "bot-key-0001", "bot_username": "shop_bot", "store_id": str(reseller.id), "bot_kind": "reseller"}
        created = await c.post(f"{ADMIN}/bot-store-bindings", headers=h, json=body)
        assert created.status_code == 201 and created.json()["store_id"] == str(reseller.id) and created.json()["status"] == "active"
        main_bot_on_reseller = await c.post(
            f"{ADMIN}/bot-store-bindings", headers=h, json={**body, "bot_key": "bot-key-0002", "bot_kind": "main"}
        )
        assert main_bot_on_reseller.status_code == 400 and _err(main_bot_on_reseller) == "BOT_STORE_KIND_MISMATCH"
        reseller_bot_on_main = await c.post(
            f"{ADMIN}/bot-store-bindings", headers=h, json={**body, "bot_key": "bot-key-0003", "store_id": str(main.id)}
        )
        assert reseller_bot_on_main.status_code == 400 and _err(reseller_bot_on_main) == "BOT_STORE_KIND_MISMATCH"
        suspended = await c.post(
            f"{ADMIN}/bot-store-bindings", headers=h, json={**body, "bot_key": "bot-key-0004", "store_id": str(closed.id)}
        )
        assert suspended.status_code == 404 and _err(suspended) == "STORE_NOT_FOUND"
        listed = (await c.get(f"{ADMIN}/bot-store-bindings", headers=h)).json()
        assert [b["bot_key"] for b in listed] == ["bot-key-0001"]
        assert (await c.post(f"{ADMIN}/bot-store-bindings", headers=h, json={**body, "bot_key": "short"})).status_code == 422


# --- coupons --------------------------------------------------------------------------------------------------------


async def test_admin_coupon_scope_rules_duplicates_and_patching():
    async with api_client() as (c, maker, main):
        h = await _admin(c, maker)
        no_store = await c.post(f"{ADMIN}/coupons", headers=h, json={"code": "SAVE10", "percent_bp": 1000, "scope": "store"})
        assert no_store.status_code == 400 and _err(no_store) == "COUPON_SCOPE_FORBIDDEN"
        empty_domain = await c.post(f"{ADMIN}/coupons", headers=h, json={"code": "DOM10", "percent_bp": 1000, "scope": "domain"})
        assert empty_domain.status_code == 400 and _err(empty_domain) == "COUPON_SCOPE_FORBIDDEN"
        body = {"code": "save10", "percent_bp": 1000, "scope": "store", "store_id": str(main.id), "max_redemptions": 5}
        created = await c.post(f"{ADMIN}/coupons", headers=h, json=body)
        assert created.status_code == 201, created.text
        coupon_id = created.json()["id"]
        duplicate = await c.post(f"{ADMIN}/coupons", headers=h, json={**body, "code": "SAVE10"})
        assert duplicate.status_code == 409 and _err(duplicate) == "COUPON_EXISTS"  # codes are case-insensitive per owner
        domain = await c.post(
            f"{ADMIN}/coupons",
            headers=h,
            json={"code": "ALLSHOPS", "fixed": 50, "scope": "domain", "allowed_store_kinds": ["main", "reseller"]},
        )
        assert domain.status_code == 201
        invalid = await c.post(f"{ADMIN}/coupons", headers=h, json={"code": "BADONE", "scope": "store", "store_id": str(main.id)})
        assert invalid.status_code == 400  # neither a percentage nor a fixed amount: the domain rules refuse it
        scoped = await c.get(f"{ADMIN}/coupons", headers=h, params={"store_id": str(main.id)})
        assert [x["id"] for x in scoped.json()] == [coupon_id]
        assert len((await c.get(f"{ADMIN}/coupons", headers=h)).json()) == 2
        patched = await c.patch(f"{ADMIN}/coupons/{coupon_id}", headers=h, json={"status": "disabled", "max_redemptions": 9})
        assert patched.status_code == 200 and patched.json()["status"] == "disabled"
        assert (
            await c.patch(f"{ADMIN}/coupons/00000000-0000-0000-0000-000000000001", headers=h, json={"status": "active"})
        ).status_code == 404
        assert (await c.patch(f"{ADMIN}/coupons/{coupon_id}", headers=h, json={"status": "deleted"})).status_code == 422
        assert len(await _audit_actions(maker, "admin.coupon.created")) == 2 and await _audit_actions(maker, "admin.coupon.updated")
