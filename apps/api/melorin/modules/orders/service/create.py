"""Order creation (priced quote, idempotency, allocation) and per-store test orders."""

import datetime as dt
import uuid
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from melorin.core import audit, codes, events, flags, settings_store
from melorin.core.deps import StoreContext, main_store
from melorin.core.db import utcnow
from melorin.core.errors import AppError
from melorin.core.scope import StoreScope
from melorin.modules.catalog import service as catalog
from melorin.kernel.models.orders import Order, OrderStateTransition
from melorin.kernel.models.stores import StoreMembership
from melorin.kernel.models.system import TestAccountGrant
from melorin.modules.catalog import allocation
from melorin.modules.vpn import renewal
from melorin.kernel.models.vpn import VpnAccount
from melorin.modules.orders.service.base import ResellerDebtLimitReached, S, transition
from melorin.modules.orders.service.payment import notify_debt_reached, pay_with_wallet


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
        # The lock is taken THROUGH the buyer's StoreScope (this user, this store): an id that belongs to another customer
        # or to another store is never locked, so it cannot stall its owner's renewal and cannot be probed through lock waits.
        # It then reads as "not found" and check_renewable answers it like any non-renewable account (409). Built from the
        # plain ids above on purpose (see the note on rollback), not from ORM instances.
        account = await StoreScope(store_id=store_id, user_id=user_id).lock(session, VpnAccount, vpn_account_id) if vpn_account_id else None
        await renewal.check_renewable(session, account, user_id=user_id, store_id=store_id)
        if product_id != account.product_id:
            raise AppError("RENEWAL_PRODUCT_MISMATCH", "تمدید فقط با همان پکیجی انجام می‌شود که اکانت با آن ساخته شده است.", 409)
        try:
            product, sp = await catalog.get_sellable(session, store, product_id)
        except AppError as e:
            raise AppError(
                "RENEWAL_PRODUCT_UNAVAILABLE", "پکیج این اکانت دیگر فروخته نمی‌شود؛ تمدید ممکن نیست و باید اکانت جدید تهیه کنید.", 409
            ) from e
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
            "package": {
                "id": str(product.id),
                "name": product.name,
                "duration_days": product.duration_days,
                "traffic_gb": product.traffic_gb,
            },
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


async def create_test_order(session: AsyncSession, ctx: StoreContext, channel: str) -> Order:
    await flags.ensure_enabled(session, "test_account", store_id=ctx.store.id, channel=channel)
    if not await settings_store.get(session, "test.enabled"):
        raise AppError("TEST_DISABLED", "اکانت تست فعلاً ارائه نمی‌شود.", 403)
    from melorin.kernel.models.catalog import Product

    code = await settings_store.get(session, "test.product_code")
    product = await session.scalar(select(Product).where(Product.code == code, Product.is_test.is_(True), Product.is_active.is_(True)))
    if not product:
        raise AppError("TEST_DISABLED", "اکانت تست فعلاً ارائه نمی‌شود.", 403)
    # The test quota is per customer PER STORE (same rule as wallets, orders and accounts: what he did in another store or bot
    # does not count here). Plain ids first: see the note in create_order about rollback and ORM instances.
    scope = StoreScope(store_id=ctx.store.id, user_id=ctx.user.id)
    # Serialise this customer's requests IN THIS STORE (row lock on his membership, taken through the scope) so parallel taps
    # cannot both pass the limit below. A request in another store takes a different lock and never waits for this one.
    # The lock also re-reads the membership, so a member blocked a moment ago cannot still claim a test account.
    member = await scope.lock(session, StoreMembership, ctx.membership.id) if ctx.membership is not None else None
    if member is None or member.status != "active":
        raise AppError("NOT_A_MEMBER", "برای دریافت اکانت تست باید عضو این فروشگاه باشید.", 403)
    max_n = int(await settings_store.get(session, "test.max_per_user") or 1)
    cooldown = int(await settings_store.get(session, "test.cooldown_hours") or 0)
    grants = (
        await session.scalars(select(TestAccountGrant).where(*scope.where(TestAccountGrant)).order_by(TestAccountGrant.created_at.desc()))
    ).all()
    if len(grants) >= max_n:
        raise AppError("TEST_LIMIT", "سقف دریافت اکانت تست شما در این فروشگاه پر شده است.", 409)
    if grants and grants[0].created_at.replace(tzinfo=dt.UTC) > utcnow() - dt.timedelta(hours=cooldown):
        raise AppError("TEST_COOLDOWN", "هنوز امکان دریافت اکانت تست جدید در این فروشگاه نیست.", 409)
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
