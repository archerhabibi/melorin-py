"""What a reseller prices (panel + bot): the price table and the store-wide / per-bundle price setters. Core enforces the cost floor."""

from __future__ import annotations

import uuid
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from melorin.core.errors import AppError, NotFound
from melorin.modules.catalog import service as catalog_service
from melorin.kernel.models.catalog import Product, StoreBundlePrice, StoreProduct
from melorin.kernel.models.stores import Store
from melorin.kernel.models.bundles import Bundle, BundleProduct, StoreBundle
from melorin.modules.catalog.allocation.offers import (
    bundle_product,
    effective_prices,
    ensure_customer_price,
    retail_price,
    store_bundle_prices,
)


def _bundle_state(price: int | None, cost: int) -> str:
    return "unset" if not price else ("below_cost" if price < cost else "ok")


async def reseller_price_table(session: AsyncSession, store: Store) -> list[dict]:
    """What a reseller sees when pricing: every product the main store enabled for this store and that some
    bundle sells. Per product: the store-wide price (``customer_price``), the cost floor over all bundles and, in
    ``bundles``, one row per bundle with its cost (reseller price), the store's own price there, the price that is
    actually charged (``effective_price``, ``source`` = bundle | store) and the resulting state.
    The bundle-level ``costs`` list is kept for older clients (Telegram bot)."""
    bundle_rows = (await session.execute(select(BundleProduct, Bundle).join(Bundle, Bundle.id == BundleProduct.bundle_id))).all()
    by_product: dict[uuid.UUID, list[tuple[BundleProduct, Bundle]]] = {}
    for pp, g in bundle_rows:
        by_product.setdefault(pp.product_id, []).append((pp, g))
    own = await store_bundle_prices(session, store.id)
    closed = {
        r.bundle_id
        for r in (
            await session.scalars(select(StoreBundle).where(StoreBundle.store_id == store.id, StoreBundle.is_enabled.is_(False)))
        ).all()
    }
    out = []
    for p, sp in await catalog_service.enabled_for_store(session, store):
        rows = by_product.get(p.id)
        if not rows:
            continue
        costs = [{"bundle_id": g.id, "bundle_name": g.name, "cost": effective_prices(p, pp)[1]} for pp, g in rows]
        floor = max(c["cost"] for c in costs)
        price = sp.customer_price or None
        bundles = []
        for pp, g in sorted(rows, key=lambda r: (r[1].created_at, str(r[1].id))):
            if not g.is_enabled or not g.reseller_enabled:
                continue  # a bundle the reseller cannot sell through is not worth pricing
            cost = effective_prices(p, pp)[1]
            mine = own.get((g.id, p.id))
            effective = retail_price(sp, mine)
            bundles.append(
                {
                    "bundle_id": g.id,
                    "bundle_name": g.name,
                    "kind_label": g.kind_label,
                    "cost": cost,
                    "price": mine,
                    "effective_price": effective,
                    "source": "bundle" if mine else ("store" if effective else None),
                    "state": _bundle_state(effective, cost),
                    "listed": bool(pp.is_listed),
                    "open_for_store": g.id not in closed,
                }
            )
        out.append(
            {
                "product_id": p.id,
                "code": p.code,
                "name": p.name,
                "duration_days": p.duration_days,
                "traffic_gb": p.traffic_gb,
                "currency": p.currency,
                "customer_price": price,
                "cost_floor": floor,
                "costs": costs,
                "bundles": bundles,
                "state": "unset" if price is None else ("below_cost" if price < floor else "ok"),
            }
        )
    return out


async def _priced_product(session: AsyncSession, store: Store, product_id: uuid.UUID) -> tuple[Product, StoreProduct]:
    """The product a reseller may price: enabled for the store by the main store, active, not a test package."""
    if store.kind != "reseller":
        raise AppError("NOT_A_RESELLER_STORE", "قیمت فروش فقط برای فروشگاه نماینده تعیین می‌شود.", 403)
    product = await session.get(Product, product_id)
    sp = await session.scalar(select(StoreProduct).where(StoreProduct.store_id == store.id, StoreProduct.product_id == product_id))
    if not product or not sp or not sp.is_enabled or product.is_test or not product.is_active or product.archived_at is not None:
        raise NotFound("محصول")
    return product, sp


async def set_customer_price(session: AsyncSession, store: Store, product_id: uuid.UUID, customer_price: int | None) -> StoreProduct:
    """The reseller sets the store-wide retail price of one product in ONE store. None or 0 clears it.
    The price must cover the reseller price of every bundle that sells the product; a bundle can still have its own
    price (``set_bundle_price``), which wins there."""
    product, sp = await _priced_product(session, store, product_id)
    if await session.scalar(select(BundleProduct.id).where(BundleProduct.product_id == product_id).limit(1)) is None:
        raise AppError("PRODUCT_NOT_IN_BUNDLE", "این محصول در هیچ بسته‌ای نیست و قابل فروش نیست.", 422)
    await ensure_customer_price(session, product, customer_price)
    sp.customer_price = customer_price or None
    return sp


async def set_bundle_price(
    session: AsyncSession, store: Store, group_id: uuid.UUID, product_id: uuid.UUID, customer_price: int | None
) -> int | None:
    """The reseller sets the retail price of one package in ONE bundle of this store. None or 0 removes it and the
    bundle falls back to the store-wide price. The price must cover THIS bundle's reseller price (the cost).
    Returns the stored price (None when cleared)."""
    product, _sp = await _priced_product(session, store, product_id)
    group = await session.get(Bundle, group_id)
    if not group or not group.is_enabled or not group.reseller_enabled:
        raise NotFound("بسته فروش")
    pp = await bundle_product(session, group_id, product_id)
    if pp is None:
        raise AppError("PRODUCT_NOT_IN_BUNDLE", "این پکیج در بسته انتخاب‌شده فروخته نمی‌شود.", 422)
    row = await session.scalar(
        select(StoreBundlePrice).where(
            StoreBundlePrice.store_id == store.id, StoreBundlePrice.bundle_id == group_id, StoreBundlePrice.product_id == product_id
        )
    )
    if not customer_price:
        if row is not None:
            await session.delete(row)
        return None
    cost = effective_prices(product, pp)[1]
    if customer_price < cost:
        raise AppError(
            "CUSTOMER_PRICE_BELOW_COST", f"قیمت فروش در بسته «{group.name}» نمی‌تواند از قیمت همکاری همین بسته ({cost}) کمتر باشد.", 422
        )
    if row is None:
        session.add(StoreBundlePrice(store_id=store.id, bundle_id=group_id, product_id=product_id, customer_price=customer_price))
    else:
        row.customer_price = customer_price
    return customer_price


async def set_prices_batch(
    session: AsyncSession, store: Store, items: list[tuple[uuid.UUID | None, uuid.UUID, int | None]]
) -> list[tuple[uuid.UUID | None, uuid.UUID, int | None]]:
    """Apply many price edits in one go, all or nothing. ``(bundle id or None for the store-wide price, product id, price)``.

    Every item is validated by the same rules as the single edits; if any is refused nothing is written and one
    error lists every refused item. Returns the items whose stored price actually changed (for the audit log)."""
    seen: set[tuple[uuid.UUID | None, uuid.UUID]] = set()
    errors: list[dict] = []
    changed: list[tuple[uuid.UUID | None, uuid.UUID, int | None]] = []
    before_bundle = await store_bundle_prices(session, store.id)
    for group_id, product_id, price in items:
        if (group_id, product_id) in seen:
            errors.append(
                {
                    "bundle_id": group_id,
                    "product_id": product_id,
                    "code": "DUPLICATE_ITEM",
                    "message": "این ردیف بیش از یک بار فرستاده شده است.",
                }
            )
            continue
        seen.add((group_id, product_id))
        try:
            if group_id is None:
                _p, sp = await _priced_product(session, store, product_id)
                old = sp.customer_price or None
                await set_customer_price(session, store, product_id, price)
            else:
                old = before_bundle.get((group_id, product_id))
                await set_bundle_price(session, store, group_id, product_id, price)
        except AppError as e:
            errors.append({"bundle_id": group_id, "product_id": product_id, "code": e.code, "message": e.message})
            continue
        if (old or None) != (price or None):
            changed.append((group_id, product_id, price or None))
    if errors:
        raise AppError(
            "PRICES_INVALID",
            f"{len(errors)} قیمت معتبر نیست؛ هیچ تغییری ذخیره نشد.",
            422,
            {
                "errors": [
                    {**e, "bundle_id": str(e["bundle_id"]) if e["bundle_id"] else None, "product_id": str(e["product_id"])} for e in errors
                ]
            },
        )
    return changed
