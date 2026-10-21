"""What a store offers and at what price: sellable bundles and packages, the price layers (product, reseller cost, retail) and the below-cost rule."""

from __future__ import annotations

import dataclasses
import uuid
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from melorin.core.errors import AppError, NotFound
from melorin.modules.catalog import service as catalog_service
from melorin.kernel.models.catalog import Product, StoreBundlePrice, StoreProduct
from melorin.kernel.models.stores import Store
from melorin.kernel.models.vpn import Panel
from melorin.kernel.models.bundles import Bundle, BundleMember, BundleProduct, StoreBundle


async def bundle_product(session: AsyncSession, group_id: uuid.UUID | None, product_id: uuid.UUID) -> BundleProduct | None:
    if group_id is None:
        return None
    return await session.scalar(select(BundleProduct).where(BundleProduct.bundle_id == group_id, BundleProduct.product_id == product_id))


async def account_bundle_id(session: AsyncSession, account) -> uuid.UUID | None:
    """The bundle an account was originally sold through (renewals are priced and listed from the same bundle)."""
    from melorin.kernel.models.orders import Order

    order = await session.get(Order, account.order_id) if getattr(account, "order_id", None) else None
    return order.bundle_id if order else None


def effective_prices(product: Product, pp: BundleProduct | None) -> tuple[int, int]:
    """(main_price, reseller_price) for a package inside a bundle: the bundle's override, else the product's own."""
    main = pp.main_price if pp is not None and pp.main_price is not None else product.main_price
    reseller = pp.reseller_price if pp is not None and pp.reseller_price is not None else product.reseller_price
    return main, reseller


def retail_price(sp: StoreProduct | None, bundle_price: int | None) -> int | None:
    """What a reseller store charges for one package in one bundle: the bundle's own price when the reseller set
    one, otherwise the store-wide price of the package. None = no price (the package is not sold there)."""
    return bundle_price or (sp.customer_price if sp else None) or None


def below_cost(price: int | None, reseller_price: int) -> bool:
    return bool(price) and price < reseller_price


def unit_price(store: Store, product: Product, retail: int | None, pp: BundleProduct | None) -> int:
    if store.kind == "reseller":
        return retail or 0
    return effective_prices(product, pp)[0]


async def store_bundle_prices(
    session: AsyncSession, store_id: uuid.UUID, *, group_id: uuid.UUID | None = None
) -> dict[tuple[uuid.UUID, uuid.UUID], int]:
    """The store's own per-bundle retail prices as ``{(bundle id, product id): price}`` (one query)."""
    q = select(StoreBundlePrice).where(StoreBundlePrice.store_id == store_id)
    if group_id is not None:
        q = q.where(StoreBundlePrice.bundle_id == group_id)
    return {(r.bundle_id, r.product_id): int(r.customer_price) for r in (await session.scalars(q)).all()}


@dataclasses.dataclass(frozen=True)
class BundleView:
    group: Bundle
    panels: list[tuple[uuid.UUID, str]]  # manual bundles only: (panel id, label the customer sees)


async def bundle_packages(
    session: AsyncSession, store: Store, group_id: uuid.UUID
) -> list[tuple[Product, StoreProduct, BundleProduct, int]]:
    """Packages a customer of ``store`` can buy in one bundle, each with the price shown to that customer."""
    q = (
        select(Product, StoreProduct, BundleProduct)
        .join(BundleProduct, (BundleProduct.product_id == Product.id) & (BundleProduct.bundle_id == group_id))
        .join(StoreProduct, (StoreProduct.product_id == Product.id) & (StoreProduct.store_id == store.id))
        .where(
            Product.is_active.is_(True),
            Product.archived_at.is_(None),
            Product.is_test.is_(False),
            StoreProduct.is_enabled.is_(True),
            StoreProduct.is_listed.is_(True),
            BundleProduct.is_listed.is_(True),
        )
    )
    if store.kind == "reseller":
        q = q.where(Product.reseller_enabled.is_(True))
    out = []
    own = await store_bundle_prices(session, store.id, group_id=group_id) if store.kind == "reseller" else {}
    for p, sp, pp in (await session.execute(q)).all():
        retail = None
        if store.kind == "reseller":
            retail = retail_price(sp, own.get((group_id, p.id)))
            if not retail or below_cost(retail, effective_prices(p, pp)[1]):
                continue
        elif p.currency != store.currency:
            continue
        out.append((p, sp, pp, unit_price(store, p, retail, pp)))
    out.sort(key=lambda r: (r[2].sort, r[3], r[0].sort))
    return out


async def sellable_bundles(session: AsyncSession, store: Store) -> list[BundleView]:
    """Bundles a customer of ``store`` may see: enabled, not sold out, open to the store, with a sellable package
    and (manual bundles) at least one healthy panel the customer can pick."""
    q = select(Bundle).where(Bundle.is_enabled.is_(True))
    q = q.outerjoin(StoreBundle, (StoreBundle.bundle_id == Bundle.id) & (StoreBundle.store_id == store.id))
    if store.kind == "reseller":
        q = q.where(Bundle.reseller_enabled.is_(True))
    q = q.where(StoreBundle.id.is_(None) | StoreBundle.is_enabled.is_(True))
    out: list[BundleView] = []
    for g in (await session.scalars(q.order_by(Bundle.created_at))).all():
        if g.sales_limit is not None and g.sold_count >= g.sales_limit:
            continue
        if not await bundle_packages(session, store, g.id):
            continue
        panels: list[tuple[uuid.UUID, str]] = []
        if g.selection_mode == "manual":
            rows = (
                await session.execute(
                    select(BundleMember, Panel)
                    .join(Panel, Panel.id == BundleMember.panel_id)
                    .where(
                        BundleMember.bundle_id == g.id,
                        BundleMember.is_enabled.is_(True),
                        Panel.is_enabled.is_(True),
                        Panel.health_status == "healthy",
                    )
                    .order_by(BundleMember.sort)
                )
            ).all()
            panels = [
                (m.panel_id, m.label or f"گزینه {i + 1}")
                for i, (m, _) in enumerate(rows)
                if m.sales_limit is None or m.sold_count < m.sales_limit
            ]
            if not panels:
                continue
        out.append(BundleView(g, panels))
    return out


async def packages_for_bundle(
    session: AsyncSession, store: Store, bundle_id: uuid.UUID
) -> list[tuple[Product, StoreProduct, BundleProduct, int]]:
    if bundle_id not in {v.group.id for v in await sellable_bundles(session, store)}:
        raise NotFound("بسته فروش")
    return await bundle_packages(session, store, bundle_id)


async def sellable_products_priced(session: AsyncSession, store: Store) -> list[tuple[Product, StoreProduct, int]]:
    """Flat catalog with the price to show: only products that at least one bundle lists and (reseller stores)
    whose retail price covers that bundle's reseller price. A reseller package that is priced per bundle shows its
    lowest valid bundle price. A product in no bundle is never shown (there is no bundle-less route)."""
    pps: dict[uuid.UUID, list[BundleProduct]] = {}
    for pp in (await session.scalars(select(BundleProduct).where(BundleProduct.is_listed.is_(True)))).all():
        pps.setdefault(pp.product_id, []).append(pp)
    own = await store_bundle_prices(session, store.id) if store.kind == "reseller" else {}
    out = []
    for p, sp in await catalog_service.store_catalog(session, store):
        rows = pps.get(p.id, [])
        if store.kind == "reseller":
            prices = []
            for pp in rows:
                retail = retail_price(sp, own.get((pp.bundle_id, p.id)))
                if retail and not below_cost(retail, effective_prices(p, pp)[1]):
                    prices.append(retail)
            if prices:
                out.append((p, sp, min(prices)))
        elif rows:
            out.append((p, sp, p.main_price))
    return out


async def sellable_products(session: AsyncSession, store: Store) -> list[tuple[Product, StoreProduct]]:
    """``sellable_products_priced`` without the price, for callers that only need to know what is sellable."""
    return [(p, sp) for p, sp, _price in await sellable_products_priced(session, store)]


async def reseller_price_floor(session: AsyncSession, product: Product) -> int:
    """The lowest customer price a reseller may set: the highest reseller price over the bundles selling the product."""
    rows = (await session.scalars(select(BundleProduct).where(BundleProduct.product_id == product.id))).all()
    return max((effective_prices(product, pp)[1] for pp in rows), default=product.reseller_price)


async def ensure_customer_price(session: AsyncSession, product: Product, customer_price: int | None) -> None:
    """Refuse a reseller retail price below the reseller price of any bundle that sells the product."""
    if not customer_price:
        return
    floor = await reseller_price_floor(session, product)
    if customer_price < floor:
        raise AppError("CUSTOMER_PRICE_BELOW_COST", f"قیمت فروش نماینده نمی‌تواند از قیمت همکاری بسته‌ها ({floor}) کمتر باشد.", 422)


async def stores_below_cost(session: AsyncSession, product: Product, reseller_price: int, group_id: uuid.UUID | None = None) -> int:
    """How many reseller stores would have this product hidden if a bundle's reseller price became ``reseller_price``.

    With ``group_id`` the check is exact for that bundle: a store's own price in the bundle wins over its store-wide
    price. Without it only the store-wide prices are compared (legacy callers)."""
    rows = (
        await session.execute(
            select(StoreProduct.store_id, StoreProduct.customer_price)
            .join(Store, Store.id == StoreProduct.store_id)
            .where(StoreProduct.product_id == product.id, Store.kind == "reseller")
        )
    ).all()
    own: dict[uuid.UUID, int] = {}
    if group_id is not None:
        own = {
            r.store_id: int(r.customer_price)
            for r in (
                await session.scalars(
                    select(StoreBundlePrice).where(StoreBundlePrice.bundle_id == group_id, StoreBundlePrice.product_id == product.id)
                )
            ).all()
        }
    hidden = {sid for sid, price in rows if below_cost(own.get(sid) or price or None, reseller_price)}
    hidden |= {sid for sid, price in own.items() if below_cost(price, reseller_price)}
    return len(hidden)
