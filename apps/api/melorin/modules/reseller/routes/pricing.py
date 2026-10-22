"""Sales bundles the store may sell and the prices the reseller sets (store-wide and per bundle); Core enforces the cost floor."""

import uuid

from fastapi import APIRouter
from sqlalchemy import select

from melorin.core import audit
from melorin.core.deps import OwnerCtx, Session
from melorin.core.errors import NotFound
from melorin.kernel.models.bundles import Bundle, StoreBundle
from melorin.modules.catalog import allocation
from melorin.modules.reseller.schemas import (
    PriceBatchIn,
    PriceIn,
)

router = APIRouter(tags=["reseller"])


@router.get("/stores/{store_id}/reseller/bundles")
async def reseller_bundles(ctx: OwnerCtx, session: Session):
    rows = (
        await session.execute(
            select(Bundle, StoreBundle)
            .join(StoreBundle, StoreBundle.bundle_id == Bundle.id, isouter=True)
            .where(Bundle.is_enabled.is_(True), Bundle.reseller_enabled.is_(True))
            .order_by(Bundle.created_at.desc())
        )
    ).all()
    return [
        {
            "id": b.id,
            "name": b.name,
            "selection_mode": b.selection_mode,
            "naming_mode": b.naming_mode,
            "is_enabled": access.is_enabled if access else True,
            "sales_limit": b.sales_limit,
            "sold_count": b.sold_count,
        }
        for b, access in rows
    ]


@router.put("/stores/{store_id}/reseller/bundles/{bundle_id}")
async def toggle_reseller_bundle(bundle_id: uuid.UUID, body: dict, ctx: OwnerCtx, session: Session):
    b = await session.get(Bundle, bundle_id)
    if not b or not b.is_enabled or not b.reseller_enabled:
        raise NotFound("بسته فروش")
    row = await session.scalar(select(StoreBundle).where(StoreBundle.store_id == ctx.store.id, StoreBundle.bundle_id == b.id))
    if not row:
        row = StoreBundle(store_id=ctx.store.id, bundle_id=b.id)
        session.add(row)
    row.is_enabled = bool(body.get("is_enabled", True))
    audit.record(
        session,
        "reseller.bundle_toggled",
        actor_id=ctx.user.id,
        actor_type="reseller",
        entity_type="bundle",
        entity_id=b.id,
        store_id=ctx.store.id,
        data={"enabled": row.is_enabled},
    )
    await session.commit()
    return {"ok": True, "is_enabled": row.is_enabled}


@router.get("/stores/{store_id}/reseller/prices")
async def reseller_prices(ctx: OwnerCtx, session: Session):
    """Products this store may sell. Per product: the store-wide retail price and, per sales bundle, the cost
    (reseller price), the store's own price in that bundle, the price actually charged and its state."""
    return await allocation.reseller_price_table(session, ctx.store)


@router.put("/stores/{store_id}/reseller/prices/{product_id}")
async def set_reseller_price(product_id: uuid.UUID, body: PriceIn, ctx: OwnerCtx, session: Session):
    """The reseller sets the retail price of one product for THIS store only. The core enforces the cost floor."""
    sp = await allocation.set_customer_price(session, ctx.store, product_id, body.customer_price)
    audit.record(
        session,
        "reseller.price_set",
        actor_id=ctx.user.id,
        actor_type="reseller",
        entity_type="product",
        entity_id=product_id,
        store_id=ctx.store.id,
        data={"customer_price": sp.customer_price},
    )
    await session.commit()
    return {"ok": True, "product_id": product_id, "customer_price": sp.customer_price}


@router.put("/stores/{store_id}/reseller/bundles/{bundle_id}/prices/{product_id}")
async def set_reseller_bundle_price(bundle_id: uuid.UUID, product_id: uuid.UUID, body: PriceIn, ctx: OwnerCtx, session: Session):
    """The reseller sets the retail price of one package in ONE sales bundle of THIS store. Null or 0 removes it and the
    bundle uses the store-wide price again. The core refuses a price below that bundle's reseller price (the cost)."""
    price = await allocation.set_bundle_price(session, ctx.store, bundle_id, product_id, body.customer_price)
    audit.record(
        session,
        "reseller.bundle_price_set",
        actor_id=ctx.user.id,
        actor_type="reseller",
        entity_type="product",
        entity_id=product_id,
        store_id=ctx.store.id,
        data={"bundle_id": str(bundle_id), "customer_price": price},
    )
    await session.commit()
    return {"ok": True, "bundle_id": bundle_id, "product_id": product_id, "customer_price": price}


@router.post("/stores/{store_id}/reseller/prices/batch")
async def set_reseller_prices_batch(body: PriceBatchIn, ctx: OwnerCtx, session: Session):
    """Save many prices at once (the pricing table of the panel), all or nothing: store-wide and per-bundle prices share
    one request. Returns the fresh price table. A refused item lists every problem and nothing is saved."""
    changed = await allocation.set_prices_batch(session, ctx.store, [(i.bundle_id, i.product_id, i.customer_price) for i in body.items])
    for bundle_id, product_id, price in changed:
        action = "reseller.price_set" if bundle_id is None else "reseller.bundle_price_set"
        audit.record(
            session,
            action,
            actor_id=ctx.user.id,
            actor_type="reseller",
            entity_type="product",
            entity_id=product_id,
            store_id=ctx.store.id,
            data={"bundle_id": str(bundle_id) if bundle_id else None, "customer_price": price, "batch": True},
        )
    await session.commit()
    return {"ok": True, "changed": len(changed), "prices": await allocation.reseller_price_table(session, ctx.store)}
