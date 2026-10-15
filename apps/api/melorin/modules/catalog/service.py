import uuid

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from melorin.core.db import utcnow
from melorin.core.errors import AppError
from melorin.domain import coupon as cdom
from melorin.domain.pricing import Discount, PricingError, Quote, quote
from melorin.modules.catalog.models import Coupon, CouponRedemption, Product, StoreProduct
from melorin.modules.stores.models import Store


async def store_catalog(session: AsyncSession, store: Store) -> list[tuple[Product, StoreProduct]]:
    """Products listed for a store, before pools are considered. Customers only ever see ``allocation.sellable_products``."""
    q = (
        select(Product, StoreProduct)
        .join(StoreProduct, (StoreProduct.product_id == Product.id) & (StoreProduct.store_id == store.id))
        .where(Product.is_active.is_(True), Product.archived_at.is_(None), Product.is_test.is_(False), StoreProduct.is_enabled.is_(True), StoreProduct.is_listed.is_(True))
        .order_by(Product.sort, Product.main_price)
    )
    rows = (await session.execute(q)).all()
    if store.kind == "reseller":
        rows = [r for r in rows if r[1].customer_price]
    else:
        rows = [r for r in rows if r[0].currency == store.currency]  # no implicit conversion
    return rows


async def get_sellable(session: AsyncSession, store: Store, product_id, *, allow_test: bool = False) -> tuple[Product, StoreProduct | None]:
    product = await session.get(Product, product_id)
    if not product or not product.is_active or product.archived_at is not None:
        raise AppError("PRODUCT_UNAVAILABLE", "این محصول در دسترس نیست.", 404)
    if product.is_test:
        if not allow_test:
            raise AppError("PRODUCT_UNAVAILABLE", "این محصول در دسترس نیست.", 404)
        return product, None
    sp = await session.scalar(select(StoreProduct).where(StoreProduct.store_id == store.id, StoreProduct.product_id == product.id))
    if not sp or not sp.is_enabled:
        raise AppError("PRODUCT_NOT_IN_STORE", "این محصول در این فروشگاه قابل فروش نیست.", 404)
    return product, sp


# ---------------------------------------------------------------- coupons
def to_rule(c: Coupon) -> cdom.CouponRule:
    return cdom.CouponRule(
        code=c.code, status=c.status, creator_type=c.creator_type, scope=c.scope,
        store_id=str(c.store_id) if c.store_id else None,
        allowed_store_ids=tuple(str(x) for x in (c.allowed_store_ids or [])),
        allowed_store_kinds=tuple(c.allowed_store_kinds or []),
        product_ids=tuple(str(x) for x in (c.product_ids or [])),
        percent_bp=c.percent_bp, fixed=c.fixed, max_discount=c.max_discount, min_amount=c.min_amount or 0,
        starts_at=c.starts_at, ends_at=c.ends_at, max_redemptions=c.max_redemptions,
        per_customer_limit=c.per_customer_limit, redemptions=c.redemptions, currency=c.currency, combinable=c.combinable,
    )


def norm_code(code: str) -> str:
    return code.strip().upper()


async def find_coupon(session: AsyncSession, store: Store, code: str, *, lock: bool) -> Coupon | None:
    """Store-owned coupon wins over an Admin domain coupon with the same code (central selection rule)."""
    q = select(Coupon).where(Coupon.code == norm_code(code), or_(Coupon.owner_key == str(store.id), Coupon.owner_key == "admin"))
    if lock:
        q = q.with_for_update()
    rows = (await session.scalars(q)).all()
    rows.sort(key=lambda c: 0 if c.owner_key == str(store.id) else 1)
    return rows[0] if rows else None


async def customer_redemptions(session: AsyncSession, coupon_id: uuid.UUID, user_id: uuid.UUID) -> int:
    return await session.scalar(
        select(func.count()).select_from(CouponRedemption).where(CouponRedemption.coupon_id == coupon_id, CouponRedemption.user_id == user_id, CouponRedemption.status == "applied")
    ) or 0


async def resolve_coupon(session: AsyncSession, store: Store, user_id: uuid.UUID, product: Product, unit_price: int, code: str | None, *, lock: bool) -> tuple[Coupon | None, int]:
    """Validate a coupon entirely in Core. With lock=True the coupon row is held until commit (quota is atomic)."""
    if not code or not code.strip():
        return None, 0
    try:
        code = cdom.pick_one([code])
    except cdom.CouponError as e:
        raise AppError(e.code, e.message, 400) from e
    c = await find_coupon(session, store, code, lock=lock)
    if not c:
        raise AppError("COUPON_INVALID", "کد تخفیف معتبر نیست.", 400)
    use = cdom.CouponUse(
        store_id=str(store.id), store_kind=store.kind, product_id=str(product.id), amount=unit_price, currency=store.currency,
        customer_redemptions=await customer_redemptions(session, c.id, user_id), now=utcnow(),
    )
    try:
        amount = cdom.evaluate(to_rule(c), use)
    except cdom.CouponError as e:
        raise AppError(e.code, e.message, 409 if e.code in ("COUPON_EXHAUSTED", "COUPON_CUSTOMER_LIMIT") else 400) from e
    return c, amount


async def redeem(session: AsyncSession, c: Coupon, *, order_id, user_id, store_id, amount: int, currency: str) -> None:
    """Call only with the coupon row locked (resolve_coupon(lock=True)) inside the order transaction."""
    c.redemptions += 1
    session.add(CouponRedemption(coupon_id=c.id, order_id=order_id, user_id=user_id, store_id=store_id, amount=amount, currency=currency))


async def release_redemption(session: AsyncSession, order_id) -> None:
    """Refund: give quota back (redemption kept for history as reversed)."""
    rows = (await session.scalars(select(CouponRedemption).where(CouponRedemption.order_id == order_id, CouponRedemption.status == "applied"))).all()
    for r in rows:
        c = await session.get(Coupon, r.coupon_id, with_for_update=True)
        r.status = "reversed"
        if c and c.redemptions > 0:
            c.redemptions -= 1


async def build_quote(
    session: AsyncSession, store: Store, product: Product, sp: StoreProduct | None, coupon: Coupon | None, discount: int = 0,
    *, main_currency: str | None = None, prices: tuple[int, int] | None = None,
) -> Quote:
    if product.is_test:
        return Quote(store.kind, str(product.id), 0, 0, 0, None, store.currency, None)
    if store.kind == "main" and product.currency != store.currency:
        raise AppError("CURRENCY_MISMATCH", "واحد پول محصول با فروشگاه یکسان نیست؛ تبدیل خودکار ارز مجاز نیست.", 409)
    if store.kind == "reseller" and main_currency and product.currency != main_currency:
        raise AppError("CURRENCY_MISMATCH", "واحد پول قیمت نمایندگی با فروشگاه اصلی یکسان نیست.", 409)
    d = Discount(coupon.code, 0, discount, None) if coupon and discount else None
    main_price, reseller_price = prices or (product.main_price, product.reseller_price)  # the core hands over pool prices
    try:
        return quote(
            store_kind=store.kind, product_id=str(product.id), main_price=main_price, reseller_price=reseller_price,
            customer_price=sp.customer_price if sp else None, currency=store.currency, discount=d,
            reseller_currency=product.currency if store.kind == "reseller" else None,
            platform_funded=bool(coupon and coupon.funded_by == "platform"),
        )
    except PricingError as e:
        raise AppError(e.code, e.message, 409) from e


def product_snapshot(p: Product) -> dict:
    return {"id": str(p.id), "code": p.code, "name": p.name, "duration_days": p.duration_days, "traffic_gb": p.traffic_gb, "max_devices": p.max_devices}


def coupon_out(c: Coupon) -> dict:
    return {
        "id": c.id, "code": c.code, "scope": c.scope, "store_id": c.store_id, "allowed_store_ids": c.allowed_store_ids, "allowed_store_kinds": c.allowed_store_kinds,
        "product_ids": c.product_ids, "creator_type": c.creator_type, "funded_by": c.funded_by, "percent_bp": c.percent_bp, "fixed": c.fixed,
        "max_discount": c.max_discount, "min_amount": c.min_amount, "currency": c.currency, "starts_at": c.starts_at, "ends_at": c.ends_at,
        "max_redemptions": c.max_redemptions, "per_customer_limit": c.per_customer_limit, "redemptions": c.redemptions, "combinable": c.combinable, "status": c.status,
    }
