"""Wallet payment of an order and the reseller debt-limit notification."""

import uuid
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from melorin.core import events, settings_store
from melorin.core.deps import main_store
from melorin.core.db import utcnow
from melorin.core.errors import AppError
from melorin.domain import debt
from melorin.kernel.models.orders import Order
from melorin.kernel.models.stores import ResellerProfile, Store
from melorin.modules.wallet import service as wallet
from melorin.modules.orders.service.base import ResellerDebtLimitReached, S, transition


async def pay_with_wallet(session: AsyncSession, order: Order, store: Store | None = None, *, main: Store | None = None) -> None:
    """Customer debit (+ owner's Main Store wallet debit for the reseller cost) + order PAID + outbox, atomically.

    Both the customer balance and the reseller debt limit are checked under row locks BEFORE any debit.
    """
    store = store or await session.get(Store, order.store_id)
    cust = await wallet.get_wallet(session, order.user_id, store.id, currency=order.currency)
    profile = None
    res_w = None
    res_currency = (order.pricing_snapshot or {}).get("reseller_currency") or order.currency
    to_lock = [cust]
    if store.kind == "reseller" and order.reseller_cost:
        profile = await session.scalar(select(ResellerProfile).where(ResellerProfile.store_id == store.id).with_for_update())
        if not profile or not profile.sales_enabled:
            raise AppError("RESELLER_SALES_DISABLED", "فروش این فروشگاه غیرفعال است.", 403)
        main = main or await main_store(session)
        # The owner's ordinary Main Store wallet doubles as the reseller account: it may dip to -debt_limit.
        res_w = await wallet.get_wallet(session, store.owner_user_id, main.id, currency=res_currency)
        to_lock.append(res_w)
    await wallet.lock_wallets(session, to_lock)
    if res_w is not None and not debt.can_afford(res_w.balance, order.reseller_cost, profile.debt_limit):
        raise ResellerDebtLimitReached(store.id)
    if cust.balance < order.total:
        raise AppError(
            "INSUFFICIENT_FUNDS",
            "موجودی کیف پول کافی نیست. لطفاً ابتدا کیف پول این فروشگاه را شارژ کنید.",
            402,
            {"balance": cust.balance, "required": order.total},
        )
    if order.total > 0:
        await wallet.post(
            session,
            kind="purchase",
            key=f"order:{order.id}:payment",
            currency=order.currency,
            store_id=store.id,
            order_id=order.id,
            postings=[
                wallet.Posting(-order.total, wallet=cust, min_balance=0),
                wallet.Posting(order.total, account=wallet.acc_revenue(store.id)),
            ],
            memo=f"سفارش {order.number}",
        )
    if res_w is not None:
        await wallet.post(
            session,
            kind="reseller_cost",
            key=f"order:{order.id}:reseller_cost",
            currency=res_currency,
            store_id=main.id,
            order_id=order.id,
            postings=[
                wallet.Posting(-order.reseller_cost, wallet=res_w, min_balance=debt.min_balance(profile.debt_limit)),
                wallet.Posting(order.reseller_cost, account=wallet.acc_revenue(main.id)),
            ],
            memo=f"هزینه نمایندگی سفارش {order.number}",
        )
    order.paid_at = utcnow()
    await transition(session, order, S.PAID)
    await events.emit(session, events.ORDER_PAID, {"order_id": order.id}, dedup_key=f"order_paid:{order.id}")
    if profile and res_w:
        near = float(await settings_store.get(session, "debt.near_ratio") or 0.8)
        st = debt.state(res_w.balance, profile.debt_limit, near)
        if st != debt.DebtState.OK:
            await events.emit(
                session, events.RESELLER_DEBT, {"store_id": store.id, "state": st, "balance": res_w.balance, "limit": profile.debt_limit}
            )


async def notify_debt_reached(session: AsyncSession, store: Store | uuid.UUID) -> None:
    """Alert the owner that sales stopped. Takes the store id so it is safe right after a ``rollback()``."""
    store_id = store.id if isinstance(store, Store) else store
    await events.emit(
        session, events.RESELLER_DEBT, {"store_id": store_id, "state": "reached"}, dedup_key=f"debt_reached:{store_id}:{utcnow():%Y%m%d%H}"
    )
