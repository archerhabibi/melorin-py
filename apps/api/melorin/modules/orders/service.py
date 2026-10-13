"""Order use cases. Financial mutations happen in one DB transaction; Panel calls never do."""
import datetime as dt
import secrets
import uuid

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from melorin.core import audit, events, flags, settings_store
from melorin.core.deps import StoreContext, main_store
from melorin.core.db import utcnow
from melorin.core.errors import AppError
from melorin.domain import debt
from melorin.domain.order_state import REFUNDABLE, RETRYABLE, InvalidTransition, OrderStatus, VpnStatus, assert_transition
from melorin.modules.catalog import service as catalog
from melorin.modules.identity.models import User
from melorin.modules.orders.models import Order, OrderStateTransition
from melorin.modules.stores.models import ResellerProfile, Store
from melorin.modules.system.models import TestAccountGrant
from melorin.modules.vpn.models import VpnAccount
from melorin.modules.wallet import service as wallet

S = OrderStatus


def new_order_number() -> str:
    return "M" + utcnow().strftime("%y%m%d") + secrets.token_hex(3).upper()


async def transition(session: AsyncSession, order: Order, to: OrderStatus, *, reason: str | None = None, actor_id=None) -> None:
    try:
        assert_transition(order.status, to)
    except InvalidTransition as e:
        raise AppError("INVALID_ORDER_STATE", f"تغییر وضعیت سفارش از {e.src} به {e.dst} مجاز نیست.", 409) from e
    session.add(OrderStateTransition(order_id=order.id, from_status=order.status, to_status=to, reason=reason, actor_id=actor_id))
    order.status = to


class ResellerDebtLimitReached(AppError):
    def __init__(self, store_id):
        super().__init__("RESELLER_DEBT_LIMIT", "فروش این فروشگاه موقتاً متوقف است. لطفاً با پشتیبانی فروشگاه تماس بگیرید.", 409)
        self.store_id = store_id


async def create_order(
    session: AsyncSession,
    ctx: StoreContext,
    *,
    product_id: uuid.UUID,
    idempotency_key: str,
    payment_method: str = "wallet",
    coupon_code: str | None = None,
    kind: str = "purchase",
    vpn_account_id: uuid.UUID | None = None,
    panel_group_id: uuid.UUID | None = None,
    selected_panel_id: uuid.UUID | None = None,
    account_name: str | None = None,
    channel: str = "web",
) -> Order:
    """Wallet-first checkout (v1.1): every purchase is paid only from the wallet of the same Store.

    Gateways/manual transfers only top up that wallet. Customer debit, reseller cost in Main Store,
    coupon redemption, order and ledger entries are committed in ONE transaction; provisioning follows via outbox.
    """
    store, user = ctx.store, ctx.user
    existing = await session.scalar(select(Order).where(Order.user_id == user.id, Order.store_id == store.id, Order.idempotency_key == idempotency_key))
    if existing:
        if existing.product_id != product_id or existing.kind != kind or existing.vpn_account_id != vpn_account_id:
            raise AppError("IDEMPOTENCY_KEY_REUSE", "کلید idempotency با سفارش دیگری استفاده شده است.", 409)
        return existing
    if payment_method != "wallet":
        raise AppError("WALLET_ONLY", "خرید فقط از کیف پول همین فروشگاه انجام می‌شود؛ ابتدا کیف پول را شارژ کنید.", 400)
    if ctx.membership is None or ctx.membership.status != "active":
        raise AppError("NOT_A_MEMBER", "برای خرید باید عضو این فروشگاه باشید.", 403)
    await flags.ensure_enabled(session, "purchase", store_id=store.id, channel=channel)
    if store.kind == "reseller":
        await flags.ensure_enabled(session, "reseller_sales", store_id=store.id)

    product, sp = await catalog.get_sellable(session, store, product_id)
    account = None
    if kind == "renewal":
        account = await session.get(VpnAccount, vpn_account_id) if vpn_account_id else None
        if not account or account.user_id != user.id or account.store_id != store.id or account.status in (VpnStatus.REVOKED, VpnStatus.ARCHIVED, VpnStatus.PENDING, VpnStatus.PROVISIONING) or account.is_test:
            raise AppError("ACCOUNT_NOT_RENEWABLE", "این اکانت قابل تمدید نیست.", 409)
    elif kind != "purchase":
        raise AppError("BAD_ORDER_KIND", "نوع سفارش نامعتبر است.", 400)

    main = await main_store(session)
    unit = catalog.unit_price_of(store, product, sp)
    coupon, disc = await catalog.resolve_coupon(session, store, user.id, product, unit, coupon_code, lock=True)
    q = await catalog.build_quote(session, store, product, sp, coupon, disc, main_currency=main.currency)
    snapshot = q.snapshot()
    if kind == "renewal" and account:
        snapshot["renewal_before"] = {"expires_at": account.expires_at.isoformat() if account.expires_at else None, "traffic_limit_bytes": account.traffic_limit_bytes}
    order = Order(
        number=new_order_number(), user_id=user.id, store_id=store.id, product_id=product.id, kind=kind,
        vpn_account_id=account.id if account else None, status=S.PENDING, payment_method="wallet", channel=channel,
        currency=q.currency, unit_price=q.unit_price, discount=q.discount, total=q.total, reseller_cost=q.reseller_cost,
        coupon_code=q.coupon_code, pricing_snapshot=snapshot, product_snapshot=catalog.product_snapshot(product),
        panel_group_id=panel_group_id, selected_panel_id=selected_panel_id, requested_account_name=account_name,
        idempotency_key=idempotency_key,
    )
    # The pre-check above is only an optimization. Two requests can pass it
    # concurrently, so the unique constraint is the real idempotency gate.
    # Isolate the insert in a savepoint: a losing request must recover the
    # committed winner instead of poisoning the whole transaction with 500.
    try:
        async with session.begin_nested():
            session.add(order)
            await session.flush()
    except IntegrityError:
        existing = await session.scalar(
            select(Order).where(
                Order.user_id == user.id,
                Order.store_id == store.id,
                Order.idempotency_key == idempotency_key,
            )
        )
        if existing:
            if existing.product_id != product_id or existing.kind != kind or existing.vpn_account_id != vpn_account_id:
                raise AppError("IDEMPOTENCY_KEY_REUSE", "کلید idempotency با سفارش دیگری استفاده شده است.", 409)
            return existing
        raise
    session.add(OrderStateTransition(order_id=order.id, from_status="-", to_status=S.PENDING, actor_id=user.id))
    if coupon and q.discount:
        await catalog.redeem(session, coupon, order_id=order.id, user_id=user.id, store_id=store.id, amount=q.discount, currency=q.currency)
    audit.record(session, "order.created", actor_id=user.id, entity_type="order", entity_id=order.id, store_id=store.id, data={"total": order.total, "coupon": q.coupon_code, "channel": channel})
    try:
        await pay_with_wallet(session, order, store, main=main)
    except ResellerDebtLimitReached:
        await session.rollback()
        await notify_debt_reached(session, store)
        await session.commit()
        raise
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        existing = await session.scalar(select(Order).where(Order.user_id == user.id, Order.store_id == store.id, Order.idempotency_key == idempotency_key))
        if existing:
            return existing
        raise
    return order


async def pay_with_wallet(session: AsyncSession, order: Order, store: Store | None = None, *, main: Store | None = None) -> None:
    """Customer debit (+ reseller credit-account debit in Main Store) + order PAID + outbox, atomically.

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
        res_w = await wallet.get_wallet(session, store.owner_user_id, main.id, currency=res_currency, kind="reseller_credit")
        to_lock.append(res_w)
    await wallet.lock_wallets(session, to_lock)
    if res_w is not None and not debt.can_afford(res_w.balance, order.reseller_cost, profile.debt_limit):
        raise ResellerDebtLimitReached(store.id)
    if cust.balance < order.total:
        raise AppError("INSUFFICIENT_FUNDS", "موجودی کیف پول کافی نیست. لطفاً ابتدا کیف پول این فروشگاه را شارژ کنید.", 402, {"balance": cust.balance, "required": order.total})
    if order.total > 0:
        await wallet.post(
            session, kind="purchase", key=f"order:{order.id}:payment", currency=order.currency, store_id=store.id, order_id=order.id,
            postings=[wallet.Posting(-order.total, wallet=cust, min_balance=0), wallet.Posting(order.total, account=wallet.acc_revenue(store.id))],
            memo=f"سفارش {order.number}",
        )
    if res_w is not None:
        await wallet.post(
            session, kind="reseller_cost", key=f"order:{order.id}:reseller_cost", currency=res_currency, store_id=main.id, order_id=order.id,
            postings=[wallet.Posting(-order.reseller_cost, wallet=res_w, min_balance=debt.min_balance(profile.debt_limit)), wallet.Posting(order.reseller_cost, account=wallet.acc_revenue(main.id))],
            memo=f"هزینه نمایندگی سفارش {order.number}",
        )
    order.paid_at = utcnow()
    await transition(session, order, S.PAID)
    await events.emit(session, events.ORDER_PAID, {"order_id": order.id}, dedup_key=f"order_paid:{order.id}")
    if profile and res_w:
        near = float(await settings_store.get(session, "debt.near_ratio") or 0.8)
        st = debt.state(res_w.balance, profile.debt_limit, near)
        if st != debt.DebtState.OK:
            await events.emit(session, events.RESELLER_DEBT, {"store_id": store.id, "state": st, "balance": res_w.balance, "limit": profile.debt_limit})


async def notify_debt_reached(session: AsyncSession, store: Store) -> None:
    await events.emit(session, events.RESELLER_DEBT, {"store_id": store.id, "state": "reached"}, dedup_key=f"debt_reached:{store.id}:{utcnow():%Y%m%d%H}")


async def create_test_order(session: AsyncSession, ctx: StoreContext, channel: str) -> Order:
    await flags.ensure_enabled(session, "test_account", store_id=ctx.store.id, channel=channel)
    if not await settings_store.get(session, "test.enabled"):
        raise AppError("TEST_DISABLED", "اکانت تست فعلاً ارائه نمی‌شود.", 403)
    from melorin.modules.catalog.models import Product

    code = await settings_store.get(session, "test.product_code")
    product = await session.scalar(select(Product).where(Product.code == code, Product.is_test.is_(True), Product.is_active.is_(True)))
    if not product:
        raise AppError("TEST_DISABLED", "اکانت تست فعلاً ارائه نمی‌شود.", 403)
    # Serialise per user (row lock) so parallel requests cannot bypass limits.
    await session.execute(select(User.id).where(User.id == ctx.user.id).with_for_update())
    max_n = int(await settings_store.get(session, "test.max_per_user") or 1)
    cooldown = int(await settings_store.get(session, "test.cooldown_hours") or 0)
    grants = (await session.scalars(select(TestAccountGrant).where(TestAccountGrant.user_id == ctx.user.id).order_by(TestAccountGrant.created_at.desc()))).all()
    if len(grants) >= max_n:
        raise AppError("TEST_LIMIT", "سقف دریافت اکانت تست شما پر شده است.", 409)
    if grants and grants[0].created_at.replace(tzinfo=dt.UTC) > utcnow() - dt.timedelta(hours=cooldown):
        raise AppError("TEST_COOLDOWN", "هنوز امکان دریافت اکانت تست جدید نیست.", 409)
    order = Order(
        number=new_order_number(), user_id=ctx.user.id, store_id=ctx.store.id, product_id=product.id, kind="test", status=S.PENDING,
        payment_method="free", channel=channel, currency=product.currency, unit_price=0, discount=0, total=0,
        pricing_snapshot={"test": True}, product_snapshot=catalog.product_snapshot(product), idempotency_key=f"test:{uuid.uuid4()}",
    )
    session.add(order)
    await session.flush()
    ids = [f"{i.provider}:{i.subject}" for i in ctx.user.identities]
    session.add(TestAccountGrant(user_id=ctx.user.id, store_id=ctx.store.id, order_id=order.id, identity_keys=ids))
    order.paid_at = utcnow()
    await transition(session, order, S.PAID, reason="test account")
    await events.emit(session, events.ORDER_PAID, {"order_id": order.id}, dedup_key=f"order_paid:{order.id}")
    audit.record(session, "test_account.granted", actor_id=ctx.user.id, entity_type="order", entity_id=order.id, store_id=ctx.store.id)
    await session.commit()
    return order


async def cancel(session: AsyncSession, order: Order, actor_id) -> None:
    await transition(session, order, S.CANCELLED, actor_id=actor_id)
    audit.record(session, "order.cancelled", actor_id=actor_id, entity_type="order", entity_id=order.id, store_id=order.store_id)
    await session.commit()


async def admin_retry(session: AsyncSession, order: Order, admin: User) -> None:
    if order.status not in RETRYABLE:
        raise AppError("INVALID_ORDER_STATE", "این سفارش قابل تلاش مجدد نیست.", 409)
    await transition(session, order, S.PROCESSING, reason="admin retry", actor_id=admin.id)
    retry_generation = order.provisioning_attempts + 1
    order.provisioning_attempts = retry_generation
    order.needs_review = False
    await events.emit(session, events.ORDER_PAID, {"order_id": order.id, "retry_generation": retry_generation}, dedup_key=f"order_paid_retry:{order.id}:{retry_generation}")
    audit.record(session, "provisioning.retry", actor_id=admin.id, actor_type="admin", entity_type="order", entity_id=order.id, store_id=order.store_id)
    await session.commit()


async def admin_mark_review(session: AsyncSession, order: Order, admin: User, note: str | None) -> None:
    await transition(session, order, S.MANUAL_REVIEW, reason=note, actor_id=admin.id)
    order.needs_review = True
    audit.record(session, "order.manual_review", actor_id=admin.id, actor_type="admin", entity_type="order", entity_id=order.id)
    await session.commit()


async def refund(session: AsyncSession, order: Order, admin: User, reason: str | None) -> None:
    """Refund = compensating ledger transaction back to the customer's wallet (+ reseller credit restored)."""
    order = await session.get(Order, order.id, with_for_update=True, populate_existing=True)
    # The row lock makes refund a single-writer operation. A repeated request
    # is intentionally a successful no-op, never a second ledger reversal.
    if order.status == S.REFUNDED:
        return
    if order.status not in REFUNDABLE:
        raise AppError("INVALID_ORDER_STATE", "این سفارش قابل استرداد نیست.", 409)
    await transition(session, order, S.REFUND_PENDING, reason=reason, actor_id=admin.id)
    tx = await wallet.find_tx(session, f"order:{order.id}:payment")
    if tx:
        await wallet.reverse(session, tx, key=f"order:{order.id}:refund", kind="refund", actor_id=admin.id, memo=f"استرداد سفارش {order.number}")
    cost_tx = await wallet.find_tx(session, f"order:{order.id}:reseller_cost")
    if cost_tx:
        await wallet.reverse(session, cost_tx, key=f"order:{order.id}:reseller_cost_refund", kind="reseller_cost_refund", actor_id=admin.id, memo=f"برگشت هزینه نمایندگی {order.number}")
    await catalog.release_redemption(session, order.id)
    await transition(session, order, S.REFUNDED, reason=reason, actor_id=admin.id)
    # Renewals keep the original account's order_id, so use the snapshot
    # pointer on the renewal order instead of searching by order_id.
    acc = await session.get(VpnAccount, order.vpn_account_id) if order.vpn_account_id else await session.scalar(select(VpnAccount).where(VpnAccount.order_id == order.id))
    if acc and acc.status not in (VpnStatus.REVOKED, VpnStatus.ARCHIVED):
        if order.kind == "renewal" and (order.pricing_snapshot or {}).get("renewal_before"):
            await events.emit(session, events.VPN_RENEWAL_ROLLBACK, {"vpn_account_id": acc.id, "before": order.pricing_snapshot["renewal_before"]}, dedup_key=f"renewal_rollback:{order.id}")
        else:
            await events.emit(session, events.VPN_REVOKE, {"vpn_account_id": acc.id})
    await events.emit(session, events.ORDER_REFUNDED, {"order_id": order.id, "store_id": order.store_id}, dedup_key=f"order_refunded:{order.id}")
    await events.emit(session, events.NOTIFY, {"user_id": order.user_id, "store_id": order.store_id, "kind": "refund", "title": "استرداد سفارش", "body": f"مبلغ سفارش {order.number} به کیف پول شما برگشت داده شد."})
    audit.record(session, "order.refunded", actor_id=admin.id, actor_type="admin", entity_type="order", entity_id=order.id, store_id=order.store_id, data={"reason": reason, "total": order.total})
    await session.commit()


async def count_by_status(session: AsyncSession, store_id=None) -> dict[str, int]:
    q = select(Order.status, func.count()).group_by(Order.status)
    if store_id:
        q = q.where(Order.store_id == store_id)
    return {s: n for s, n in (await session.execute(q)).all()}
