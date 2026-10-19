"""Order use cases. Financial mutations happen in one DB transaction; Panel calls never do."""

import datetime as dt
import uuid

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from melorin.core import audit, codes, events, flags, settings_store
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
from melorin.modules.vpn import allocation, renewal
from melorin.modules.vpn.models import VpnAccount
from melorin.modules.wallet import service as wallet

S = OrderStatus


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
    bundle_id: uuid.UUID | None = None,
    selected_panel_id: uuid.UUID | None = None,
    account_name: str | None = None,
    channel: str = "web",
) -> Order:
    """Wallet-first checkout (v1.1): every purchase is paid only from the wallet of the same Store.

    Gateways/manual transfers only top up that wallet. Customer debit, reseller cost in Main Store,
    coupon redemption, order and ledger entries are committed in ONE transaction; provisioning follows via outbox.
    """
    store, user = ctx.store, ctx.user
    # Plain values on purpose: ``session.rollback()`` expires every ORM instance and async code cannot lazy-load them
    # afterwards (MissingGreenlet -> HTTP 500). Every recovery path below must use these, never ``store.id``/``user.id``.
    store_id, user_id = store.id, user.id
    existing = await session.scalar(
        select(Order).where(Order.user_id == user_id, Order.store_id == store_id, Order.idempotency_key == idempotency_key)
    )
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

    account = None
    if kind == "renewal":
        # Renewal rules live in the core (vpn.renewal) and are identical for the website and the bots. The account row is
        # locked so two parallel requests cannot both pass the "no renewal in progress" check and charge twice.
        account = await session.get(VpnAccount, vpn_account_id, with_for_update=True) if vpn_account_id else None
        await renewal.check_renewable(session, account, user_id=user_id, store_id=store_id)
        if product_id != account.product_id:
            raise AppError("RENEWAL_PRODUCT_MISMATCH", "تمدید فقط با همان پکیجی انجام می‌شود که اکانت با آن ساخته شده است.", 409)
        try:
            product, sp = await catalog.get_sellable(session, store, product_id)
        except AppError as e:
            raise AppError("RENEWAL_PRODUCT_UNAVAILABLE", "پکیج این اکانت دیگر فروخته نمی‌شود؛ تمدید ممکن نیست و باید اکانت جدید تهیه کنید.", 409) from e
    elif kind == "purchase":
        product, sp = await catalog.get_sellable(session, store, product_id)
    else:
        raise AppError("BAD_ORDER_KIND", "نوع سفارش نامعتبر است.", 400)
    # Every channel gets the same answer from the core: bundle, package membership, panel choice, account name
    # and price are decided there, before any money moves. Nothing below chooses or prices a route.
    plan = await allocation.plan_sale(
        session,
        store=store,
        product=product,
        sp=sp,
        kind=kind,
        account=account,
        bundle_id=bundle_id,
        selected_panel_id=selected_panel_id,
        account_name=account_name,
    )
    bundle = plan.group if kind == "purchase" else None
    if kind == "purchase":
        bundle_id, selected_panel_id, account_name = plan.group_id, plan.selected_panel_id, plan.account_name

    main = await main_store(session)
    unit = plan.unit_price
    coupon, disc = await catalog.resolve_coupon(session, store, user.id, product, unit, coupon_code, lock=True)
    q = await catalog.build_quote(
        session,
        store,
        product,
        sp,
        coupon,
        disc,
        main_currency=main.currency,
        prices=plan.prices,
        customer_price=plan.unit_price if store.kind == "reseller" else None,
    )
    snapshot = q.snapshot()
    if bundle is not None:
        snapshot["bundle"] = {"id": str(bundle.id), "name": bundle.name, "kind_label": bundle.kind_label}
    if kind == "renewal" and account:
        snapshot["renewal_before"] = {
            "expires_at": account.expires_at.isoformat() if account.expires_at else None,
            "traffic_limit_bytes": account.traffic_limit_bytes,
        }
        snapshot["renewal"] = {
            "package": {"id": str(product.id), "name": product.name, "duration_days": product.duration_days, "traffic_gb": product.traffic_gb},
            "bundle_id": str(plan.group_id) if plan.group_id else None,
            "unit_price": plan.unit_price,  # the package's current price in the original bundle, charged now
        }
    order = Order(
        number=await codes.next_code(session, codes.ORDER_SEQ),
        user_id=user.id,
        store_id=store.id,
        product_id=product.id,
        kind=kind,
        vpn_account_id=account.id if account else None,
        status=S.PENDING,
        payment_method="wallet",
        channel=channel,
        currency=q.currency,
        unit_price=q.unit_price,
        discount=q.discount,
        total=q.total,
        reseller_cost=q.reseller_cost,
        coupon_code=q.coupon_code,
        pricing_snapshot=snapshot,
        product_snapshot=catalog.product_snapshot(product),
        bundle_id=bundle_id,
        selected_panel_id=selected_panel_id,
        requested_account_name=account_name,
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
                Order.user_id == user_id,
                Order.store_id == store_id,
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
    audit.record(
        session,
        "order.created",
        actor_id=user.id,
        entity_type="order",
        entity_id=order.id,
        store_id=store.id,
        data={"total": order.total, "coupon": q.coupon_code, "channel": channel},
    )
    try:
        await pay_with_wallet(session, order, store, main=main)
    except ResellerDebtLimitReached:
        # The sale is refused (a clean 409 for the bot / website); only the owner alert is kept.
        await session.rollback()
        await notify_debt_reached(session, store_id)
        await session.commit()
        raise
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        existing = await session.scalar(
            select(Order).where(Order.user_id == user_id, Order.store_id == store_id, Order.idempotency_key == idempotency_key)
        )
        if existing:
            return existing
        raise
    return order


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
    grants = (
        await session.scalars(
            select(TestAccountGrant).where(TestAccountGrant.user_id == ctx.user.id).order_by(TestAccountGrant.created_at.desc())
        )
    ).all()
    if len(grants) >= max_n:
        raise AppError("TEST_LIMIT", "سقف دریافت اکانت تست شما پر شده است.", 409)
    if grants and grants[0].created_at.replace(tzinfo=dt.UTC) > utcnow() - dt.timedelta(hours=cooldown):
        raise AppError("TEST_COOLDOWN", "هنوز امکان دریافت اکانت تست جدید نیست.", 409)
    # Test accounts are placed by the same core rule as purchases (product default group, same eligibility).
    bundle_id, selected_panel_id = await allocation.resolve_order_group(session, store_id=ctx.store.id, product=product)
    order = Order(
        bundle_id=bundle_id,
        selected_panel_id=selected_panel_id,
        number=await codes.next_code(session, codes.ORDER_SEQ),
        user_id=ctx.user.id,
        store_id=ctx.store.id,
        product_id=product.id,
        kind="test",
        status=S.PENDING,
        payment_method="free",
        channel=channel,
        currency=product.currency,
        unit_price=0,
        discount=0,
        total=0,
        pricing_snapshot={"test": True},
        product_snapshot=catalog.product_snapshot(product),
        idempotency_key=f"test:{uuid.uuid4()}",
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
    await events.emit(
        session,
        events.ORDER_PAID,
        {"order_id": order.id, "retry_generation": retry_generation},
        dedup_key=f"order_paid_retry:{order.id}:{retry_generation}",
    )
    audit.record(
        session,
        "provisioning.retry",
        actor_id=admin.id,
        actor_type="admin",
        entity_type="order",
        entity_id=order.id,
        store_id=order.store_id,
    )
    await session.commit()


async def admin_mark_review(session: AsyncSession, order: Order, admin: User, note: str | None) -> None:
    await transition(session, order, S.MANUAL_REVIEW, reason=note, actor_id=admin.id)
    order.needs_review = True
    audit.record(session, "order.manual_review", actor_id=admin.id, actor_type="admin", entity_type="order", entity_id=order.id)
    await session.commit()


async def _refund(
    session: AsyncSession,
    order_id: uuid.UUID,
    *,
    actor_id,  # None for system-triggered refunds
    actor_type: str,  # "admin" | "system"
    reason: str | None,
) -> None:
    """Internal single-writer compensating ledger reversal. Idempotent on repeated calls."""
    order = await session.get(Order, order_id, with_for_update=True, populate_existing=True)
    if not order:
        return
    if order.status == S.REFUNDED:
        return
    if order.status not in REFUNDABLE:
        raise AppError("INVALID_ORDER_STATE", "این سفارش قابل استرداد نیست.", 409)
    await transition(session, order, S.REFUND_PENDING, reason=reason, actor_id=actor_id)
    tx = await wallet.find_tx(session, f"order:{order.id}:payment")
    if tx:
        await wallet.reverse(
            session,
            tx,
            key=f"order:{order.id}:refund",
            kind="refund",
            actor_id=actor_id,
            memo=f"استرداد سفارش {order.number}",
        )
    cost_tx = await wallet.find_tx(session, f"order:{order.id}:reseller_cost")
    if cost_tx:
        await wallet.reverse(
            session,
            cost_tx,
            key=f"order:{order.id}:reseller_cost_refund",
            kind="reseller_cost_refund",
            actor_id=actor_id,
            memo=f"برگشت هزینه نمایندگی {order.number}",
        )
    await catalog.release_redemption(session, order.id)
    await transition(session, order, S.REFUNDED, reason=reason, actor_id=actor_id)
    acc = (
        await session.get(VpnAccount, order.vpn_account_id)
        if order.vpn_account_id
        else await session.scalar(select(VpnAccount).where(VpnAccount.order_id == order.id))
    )
    if acc and acc.status not in (VpnStatus.REVOKED, VpnStatus.ARCHIVED):
        if order.kind == "renewal" and (order.pricing_snapshot or {}).get("renewal_before"):
            await events.emit(
                session,
                events.VPN_RENEWAL_ROLLBACK,
                {"vpn_account_id": acc.id, "before": order.pricing_snapshot["renewal_before"]},
                dedup_key=f"renewal_rollback:{order.id}",
            )
        else:
            await events.emit(session, events.VPN_REVOKE, {"vpn_account_id": acc.id})
    await events.emit(
        session,
        events.ORDER_REFUNDED,
        {"order_id": order.id, "store_id": order.store_id},
        dedup_key=f"order_refunded:{order.id}",
    )
    refund_body = (
        f"ساخت اکانت سفارش {order.number} ناموفق بود و مبلغ آن به کیف پول شما برگشت داده شد."
        if actor_type == "system"
        else f"مبلغ سفارش {order.number} به کیف پول شما برگشت داده شد."
    )
    await events.emit(
        session,
        events.NOTIFY,
        {"user_id": order.user_id, "store_id": order.store_id, "kind": "refund", "title": "استرداد سفارش", "body": refund_body},
    )
    audit.record(
        session,
        "order.refunded",
        actor_id=actor_id,
        actor_type=actor_type,
        entity_type="order",
        entity_id=order.id,
        store_id=order.store_id,
        data={"reason": reason, "total": order.total},
    )
    await session.commit()


async def refund(session: AsyncSession, order: Order, admin: User, reason: str | None) -> None:
    """Admin-triggered refund. Delegates to _refund() with the admin as actor."""
    await _refund(session, order.id, actor_id=admin.id, actor_type="admin", reason=reason)


async def auto_refund(session: AsyncSession, order_id: uuid.UUID, *, reason: str | None) -> None:
    """System-triggered refund after all provisioning retries are exhausted.

    No admin action is required; the system is the actor. Admin notification
    is emitted before this call (by vpn.service._give_up) via PROVISIONING_FAILED.
    """
    await _refund(session, order_id, actor_id=None, actor_type="system", reason=reason)


async def count_by_status(session: AsyncSession, store_id=None) -> dict[str, int]:
    q = select(Order.status, func.count()).group_by(Order.status)
    if store_id:
        q = q.where(Order.store_id == store_id)
    return {s: n for s, n in (await session.execute(q)).all()}
