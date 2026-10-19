"""M7.1: order money paths through the service layer - wallet purchase, reseller debt limit, refund / auto-refund
(idempotent, wallet restored, reseller cost reversed) and order-state transitions with audit rows."""

import pytest
from sqlalchemy import select

from _db import make_order, make_product, make_store, make_user, open_session
from melorin.core.errors import AppError
from melorin.modules.orders import service as orders
from melorin.modules.orders.models import OrderStateTransition
from melorin.modules.stores.models import ResellerProfile
from melorin.modules.system.models import OutboxEvent
from melorin.modules.vpn.models import VpnAccount
from melorin.modules.wallet import service as wallet


async def _fund(s, user, store, amount, *, kind="customer", currency="IRT"):
    w = await wallet.get_wallet(s, user.id, store.id, currency=currency, kind=kind)
    await wallet.post(
        s,
        kind="topup",
        key=f"fund:{w.id}:{amount}",
        currency=currency,
        postings=[wallet.Posting(-amount, account="gateway:test:clearing"), wallet.Posting(amount, wallet=w)],
    )
    return w


async def _topics(s):
    return (await s.scalars(select(OutboxEvent.topic))).all()


# ------------------------------------------------------------ pay with wallet


async def test_wallet_purchase_debits_customer_credits_revenue_and_marks_paid():
    async with open_session() as s:
        store, user, product = await make_store(s), await make_user(s), await make_product(s)
        cust = await _fund(s, user, store, 5_000)
        order = await make_order(s, user=user, store=store, product=product, total=2_000, status="pending")
        await orders.pay_with_wallet(s, order, store)
        await s.commit()
        assert cust.balance == 3_000 and order.status == "paid" and order.paid_at is not None
        assert "order.paid" in await _topics(s)
        tx = await wallet.find_tx(s, f"order:{order.id}:payment")
        assert tx.kind == "purchase" and tx.order_id == order.id


async def test_wallet_purchase_with_insufficient_balance_is_402_and_changes_nothing():
    async with open_session() as s:
        store, user, product = await make_store(s), await make_user(s), await make_product(s)
        cust = await _fund(s, user, store, 1_999)
        order = await make_order(s, user=user, store=store, product=product, total=2_000, status="pending")
        with pytest.raises(AppError) as exc:
            await orders.pay_with_wallet(s, order, store)
        assert exc.value.code == "INSUFFICIENT_FUNDS" and exc.value.status == 402
        assert exc.value.details == {"balance": 1_999, "required": 2_000}
        assert cust.balance == 1_999 and order.status == "pending"
        assert await wallet.find_tx(s, f"order:{order.id}:payment") is None


async def test_paying_an_already_paid_order_is_rejected_by_the_state_machine():
    async with open_session() as s:
        store, user, product = await make_store(s), await make_user(s), await make_product(s)
        await _fund(s, user, store, 9_000)
        order = await make_order(s, user=user, store=store, product=product, total=2_000, status="pending")
        await orders.pay_with_wallet(s, order, store)
        with pytest.raises(AppError) as exc:
            await orders.pay_with_wallet(s, order, store)
        assert exc.value.code == "INVALID_ORDER_STATE"


async def test_free_order_posts_no_ledger_transaction_but_still_becomes_paid():
    async with open_session() as s:
        store, user, product = await make_store(s), await make_user(s), await make_product(s)
        order = await make_order(s, user=user, store=store, product=product, total=0, status="pending")
        await orders.pay_with_wallet(s, order, store)
        assert order.status == "paid"
        assert await wallet.find_tx(s, f"order:{order.id}:payment") is None


async def _reseller_setup(s, *, debt_limit=10_000, sales_enabled=True):
    main = await make_store(s)
    owner, customer, product = await make_user(s), await make_user(s), await make_product(s)
    reseller = await make_store(s, kind="reseller", owner=owner)
    s.add(ResellerProfile(store_id=reseller.id, user_id=owner.id, debt_limit=debt_limit, sales_enabled=sales_enabled))
    await s.flush()
    cust = await _fund(s, customer, reseller, 20_000)
    return main, owner, customer, product, reseller, cust


async def test_reseller_sale_charges_customer_and_books_reseller_cost_as_debt():
    async with open_session() as s:
        main, owner, customer, product, reseller, cust = await _reseller_setup(s)
        order = await make_order(s, user=customer, store=reseller, product=product, total=5_000, status="pending", reseller_cost=3_000)
        await orders.pay_with_wallet(s, order, reseller, main=main)
        credit = await wallet.get_wallet(s, owner.id, main.id)
        assert cust.balance == 15_000 and credit.balance == -3_000 and order.status == "paid"


async def test_reseller_sale_beyond_debt_limit_is_blocked_before_any_debit():
    async with open_session() as s:
        main, owner, customer, product, reseller, cust = await _reseller_setup(s, debt_limit=2_000)
        order = await make_order(s, user=customer, store=reseller, product=product, total=5_000, status="pending", reseller_cost=3_000)
        with pytest.raises(orders.ResellerDebtLimitReached):
            await orders.pay_with_wallet(s, order, reseller, main=main)
        credit = await wallet.get_wallet(s, owner.id, main.id)
        assert cust.balance == 20_000 and credit.balance == 0 and order.status == "pending"


async def test_reseller_sale_is_blocked_when_sales_are_disabled():
    async with open_session() as s:
        main, owner, customer, product, reseller, cust = await _reseller_setup(s, sales_enabled=False)
        order = await make_order(s, user=customer, store=reseller, product=product, total=1_000, status="pending", reseller_cost=500)
        with pytest.raises(AppError) as exc:
            await orders.pay_with_wallet(s, order, reseller, main=main)
        assert exc.value.code == "RESELLER_SALES_DISABLED" and exc.value.status == 403
        assert cust.balance == 20_000


async def test_reaching_the_debt_limit_emits_a_reseller_debt_event():
    async with open_session() as s:
        main, owner, customer, product, reseller, _ = await _reseller_setup(s, debt_limit=3_000)
        order = await make_order(s, user=customer, store=reseller, product=product, total=5_000, status="pending", reseller_cost=3_000)
        await orders.pay_with_wallet(s, order, reseller, main=main)
        assert "reseller.debt" in await _topics(s)


# ------------------------------------------------------------------- refund


async def _paid_order(s, *, total=2_000, funded=5_000):
    store, user, product = await make_store(s), await make_user(s), await make_product(s)
    cust = await _fund(s, user, store, funded)
    order = await make_order(s, user=user, store=store, product=product, total=total, status="pending")
    await orders.pay_with_wallet(s, order, store)
    await s.commit()
    return store, user, product, cust, order


async def test_admin_refund_restores_wallet_once_and_is_idempotent():
    async with open_session() as s:
        store, user, product, cust, order = await _paid_order(s)
        admin = await make_user(s, super_admin=True)
        await orders.refund(s, order, admin, "duplicate order")
        await orders.refund(s, order, admin, "duplicate order")
        assert order.status == "refunded" and cust.balance == 5_000
        assert (await wallet.find_tx(s, f"order:{order.id}:refund")).reverses_id is not None
        assert (await _topics(s)).count("order.refunded") == 1


async def test_refund_walks_paid_to_refund_pending_to_refunded_with_audit_rows():
    async with open_session() as s:
        _, _, _, _, order = await _paid_order(s)
        admin = await make_user(s, super_admin=True)
        await orders.refund(s, order, admin, "why")
        rows = (
            await s.scalars(
                select(OrderStateTransition).where(OrderStateTransition.order_id == order.id).order_by(OrderStateTransition.created_at)
            )
        ).all()
        assert [(r.from_status, r.to_status) for r in rows if r.to_status in {"refund_pending", "refunded"}] == [
            ("paid", "refund_pending"),
            ("refund_pending", "refunded"),
        ]
        assert all(r.actor_id == admin.id for r in rows if r.to_status == "refunded")


@pytest.mark.parametrize("status", ["pending", "payment_pending", "payment_failed", "processing", "provisioning", "cancelled"])
async def test_orders_that_were_not_paid_cannot_be_refunded(status):
    async with open_session() as s:
        store, user, product = await make_store(s), await make_user(s), await make_product(s)
        order = await make_order(s, user=user, store=store, product=product, status=status)
        admin = await make_user(s, super_admin=True)
        with pytest.raises(AppError) as exc:
            await orders.refund(s, order, admin, None)
        assert exc.value.code == "INVALID_ORDER_STATE" and exc.value.status == 409


async def test_reseller_refund_reverses_both_customer_payment_and_reseller_cost():
    async with open_session() as s:
        main, owner, customer, product, reseller, cust = await _reseller_setup(s)
        order = await make_order(s, user=customer, store=reseller, product=product, total=5_000, status="pending", reseller_cost=3_000)
        await orders.pay_with_wallet(s, order, reseller, main=main)
        await s.commit()
        admin = await make_user(s, super_admin=True)
        await orders.refund(s, order, admin, None)
        credit = await wallet.get_wallet(s, owner.id, main.id)
        assert cust.balance == 20_000 and credit.balance == 0
        assert await wallet.find_tx(s, f"order:{order.id}:reseller_cost_refund") is not None


async def test_auto_refund_uses_the_system_actor_and_revokes_the_account():
    async with open_session() as s:
        store, user, product, cust, order = await _paid_order(s)
        acc = VpnAccount(username="a1", user_id=user.id, store_id=store.id, order_id=order.id, product_id=product.id, status="active")
        s.add(acc)
        await s.flush()
        order.status = "provisioning_failed"
        await orders.auto_refund(s, order.id, reason="retries exhausted")
        assert order.status == "refunded" and cust.balance == 5_000
        topics = await _topics(s)
        assert "vpn.revoke" in topics and "order.refunded" in topics
        last = await s.scalar(select(OrderStateTransition).where(OrderStateTransition.to_status == "refunded"))
        assert last.actor_id is None


async def test_auto_refund_of_missing_or_already_refunded_order_is_a_noop():
    import uuid

    async with open_session() as s:
        _, _, _, cust, order = await _paid_order(s)
        await orders.auto_refund(s, uuid.uuid4(), reason="x")
        await orders.auto_refund(s, order.id, reason="x")
        await orders.auto_refund(s, order.id, reason="x")
        assert cust.balance == 5_000 and order.status == "refunded"


# ------------------------------------------------------- transitions / retry


async def test_transition_rejects_illegal_moves_with_a_409_and_writes_no_audit_row():
    async with open_session() as s:
        store, user, product = await make_store(s), await make_user(s), await make_product(s)
        order = await make_order(s, user=user, store=store, product=product, status="completed")
        with pytest.raises(AppError) as exc:
            await orders.transition(s, order, orders.S.CANCELLED)
        assert exc.value.code == "INVALID_ORDER_STATE" and exc.value.status == 409
        assert order.status == "completed"
        assert (await s.scalars(select(OrderStateTransition))).all() == []


async def test_cancel_only_works_before_payment():
    async with open_session() as s:
        store, user, product = await make_store(s), await make_user(s), await make_product(s)
        pending = await make_order(s, user=user, store=store, product=product, status="pending")
        paid = await make_order(s, user=user, store=store, product=product, status="paid")
        await orders.cancel(s, pending, user.id)
        assert pending.status == "cancelled"
        with pytest.raises(AppError):
            await orders.cancel(s, paid, user.id)


async def test_admin_retry_requeues_a_failed_provisioning_exactly_once_per_generation():
    async with open_session() as s:
        store, user, product = await make_store(s), await make_user(s), await make_product(s)
        admin = await make_user(s, super_admin=True)
        order = await make_order(s, user=user, store=store, product=product, status="provisioning_failed")
        await orders.admin_retry(s, order, admin)
        assert order.status == "processing" and order.provisioning_attempts == 1 and order.needs_review is False
        with pytest.raises(AppError):  # not retryable any more
            await orders.admin_retry(s, order, admin)
        events = (await s.scalars(select(OutboxEvent).where(OutboxEvent.topic == "order.paid"))).all()
        assert [e.dedup_key for e in events] == [f"order_paid_retry:{order.id}:1"]


async def test_manual_review_flags_the_order_and_can_then_be_retried():
    async with open_session() as s:
        store, user, product = await make_store(s), await make_user(s), await make_product(s)
        admin = await make_user(s, super_admin=True)
        order = await make_order(s, user=user, store=store, product=product, status="provisioning_failed")
        await orders.admin_mark_review(s, order, admin, "panel unreachable")
        assert order.status == "manual_review" and order.needs_review is True
        await orders.admin_retry(s, order, admin)
        assert order.status == "processing" and order.needs_review is False
