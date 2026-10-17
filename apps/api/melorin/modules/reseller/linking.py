"""Keeps every reseller store connected to the main catalog (packages and sales bundles).

A reseller store sells only what the main store opened for it: a ``StoreProduct`` row per package and a
``StoreBundle`` row per sales bundle. Without those rows a reseller sees an empty price table and cannot sell,
so the rows are created automatically at every point where the catalog or the set of stores grows:

* a new reseller store      -> ``link_store_catalog`` (all current packages and bundles)
* a new package             -> ``link_product_to_resellers``
* a new / reseller-enabled bundle -> ``link_bundle_to_resellers``

Linking only ever ADDS missing rows (enabled, listed, no price). A row that already exists is never touched, so an
admin's later "disable for this store" and a reseller's own prices are never overwritten.
"""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from melorin.modules.catalog.models import Product, StoreProduct
from melorin.modules.stores.models import Store
from melorin.modules.vpn.bundles import Bundle, StoreBundle


async def _reseller_store_ids(session: AsyncSession) -> list[uuid.UUID]:
    return list((await session.scalars(select(Store.id).where(Store.kind == "reseller"))).all())


async def _link_products(session: AsyncSession, store_ids: list[uuid.UUID], product_ids: list[uuid.UUID]) -> int:
    if not store_ids or not product_ids:
        return 0
    have = set(
        (
            await session.execute(
                select(StoreProduct.store_id, StoreProduct.product_id).where(
                    StoreProduct.store_id.in_(store_ids), StoreProduct.product_id.in_(product_ids)
                )
            )
        ).all()
    )
    added = 0
    for sid in store_ids:
        for pid in product_ids:
            if (sid, pid) not in have:
                session.add(StoreProduct(store_id=sid, product_id=pid, is_enabled=True, is_listed=True, customer_price=None))
                added += 1
    return added


async def _link_bundles(session: AsyncSession, store_ids: list[uuid.UUID], bundle_ids: list[uuid.UUID]) -> int:
    if not store_ids or not bundle_ids:
        return 0
    have = set(
        (
            await session.execute(
                select(StoreBundle.store_id, StoreBundle.bundle_id).where(
                    StoreBundle.store_id.in_(store_ids), StoreBundle.bundle_id.in_(bundle_ids)
                )
            )
        ).all()
    )
    added = 0
    for sid in store_ids:
        for bid in bundle_ids:
            if (sid, bid) not in have:
                session.add(StoreBundle(store_id=sid, bundle_id=bid, is_enabled=True))
                added += 1
    return added


async def link_store_catalog(session: AsyncSession, store: Store) -> tuple[int, int]:
    """Connect one reseller store to all current sellable packages and reseller-enabled bundles. Returns (packages, bundles) added."""
    if store.kind != "reseller":
        return 0, 0
    products = list(
        (
            await session.scalars(
                select(Product.id).where(Product.is_active.is_(True), Product.archived_at.is_(None), Product.is_test.is_(False))
            )
        ).all()
    )
    bundles = list((await session.scalars(select(Bundle.id).where(Bundle.reseller_enabled.is_(True)))).all())
    return await _link_products(session, [store.id], products), await _link_bundles(session, [store.id], bundles)


async def link_product_to_resellers(session: AsyncSession, product: Product) -> int:
    """A new package is opened for every existing reseller store (the admin can still disable it per store)."""
    if product.is_test or product.archived_at is not None:
        return 0
    return await _link_products(session, await _reseller_store_ids(session), [product.id])


async def link_bundle_to_resellers(session: AsyncSession, bundle: Bundle) -> int:
    """A reseller-enabled bundle is opened for every existing reseller store."""
    if not bundle.reseller_enabled:
        return 0
    return await _link_bundles(session, await _reseller_store_ids(session), [bundle.id])
