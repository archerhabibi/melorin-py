"""Admin API - bundles routes (split from the former 1,900-line router; paths unchanged)."""

import logging
import uuid
from fastapi import APIRouter
from sqlalchemy import delete, func, select
from melorin.core import audit
from melorin.core.deps import AdminUser, Session
from melorin.core.errors import AppError, NotFound
from melorin.kernel.models.catalog import Product, StoreBundlePrice
from melorin.kernel.models.orders import Order
from melorin.kernel.models.stores import Store
from melorin.modules.reseller.linking import link_bundle_to_resellers
from melorin.modules.catalog import allocation
from melorin.kernel.models.vpn import Panel
from melorin.kernel.models.bundles import Bundle, BundleMember, BundleProduct, StoreBundle
from melorin.modules.admin.schemas import (
    BundleProductIn,
    CreateBundle,
    UpdateBundle,
)
from melorin.modules.admin._common import (
    _commit_or_conflict,
    _count,
    _names,
)

router = APIRouter(prefix="/admin", tags=["admin"])
log = logging.getLogger("melorin.admin")


async def _add_all_products_to_bundle(session, bundle: Bundle) -> None:
    """A new sales bundle starts with every sellable package, listed."""
    have = set((await session.scalars(select(BundleProduct.product_id).where(BundleProduct.bundle_id == bundle.id))).all())
    ids = (
        await session.scalars(
            select(Product.id).where(Product.is_test.is_(False), Product.archived_at.is_(None)).order_by(Product.sort, Product.created_at)
        )
    ).all()
    for i, pid in enumerate(ids):
        if pid not in have:
            session.add(BundleProduct(bundle_id=bundle.id, product_id=pid, is_listed=True, sort=i))


async def _bundle_product_ids(session, group_id) -> list[str]:
    return [str(x) for x in (await session.scalars(select(BundleProduct.product_id).where(BundleProduct.bundle_id == group_id))).all()]


def _bundle_out(b, panels, product_ids=()):
    return {
        "product_ids": list(product_ids),
        **{
            "id": b.id,
            "name": b.name,
            "selection_mode": b.selection_mode,
            "naming_mode": b.naming_mode,
            "kind_label": b.kind_label,
            "is_enabled": b.is_enabled,
            "reseller_enabled": b.reseller_enabled,
            "sales_limit": b.sales_limit,
            "sold_count": b.sold_count,
            "panels": [
                {
                    "id": p.id,
                    "panel_id": p.panel_id,
                    "is_enabled": p.is_enabled,
                    "sales_limit": p.sales_limit,
                    "sold_count": p.sold_count,
                    "sort": p.sort,
                    "label": p.label,
                }
                for p in panels
            ],
        },
    }


@router.get("/bundles")
async def list_bundles(_: AdminUser, session: Session):
    bundles = (await session.scalars(select(Bundle).order_by(Bundle.created_at.desc()))).all()
    result = []
    for b in bundles:
        rows = (await session.scalars(select(BundleMember).where(BundleMember.bundle_id == b.id).order_by(BundleMember.sort))).all()
        result.append(_bundle_out(b, rows, await _bundle_product_ids(session, b.id)))
    return result


@router.post("/bundles", status_code=201)
async def create_bundle(body: CreateBundle, admin: AdminUser, session: Session):
    if body.selection_mode == "manual" and not body.panel_ids:
        raise AppError("BUNDLE_PANELS_REQUIRED", "بسته دستی باید حداقل یک پنل داشته باشد.", 400)
    valid = (await session.scalars(select(Panel.id).where(Panel.id.in_(body.panel_ids)))).all()
    if len(valid) != len(set(body.panel_ids)):
        raise NotFound("بسته فروش")
    b = Bundle(
        name=body.name,
        selection_mode=body.selection_mode,
        naming_mode=body.naming_mode,
        kind_label=body.kind_label,
        is_enabled=body.is_enabled,
        reseller_enabled=body.reseller_enabled,
        sales_limit=body.sales_limit,
    )
    session.add(b)
    await session.flush()
    for i, pid in enumerate(body.panel_ids):
        session.add(BundleMember(bundle_id=b.id, panel_id=pid, sort=i, label=(body.member_labels.get(pid) or "").strip() or None))
    await _add_all_products_to_bundle(session, b)  # every package is sold in a new bundle by default
    await link_bundle_to_resellers(session, b)  # reseller stores get the new bundle too
    audit.record(session, "bundle.created", actor_id=admin.id, actor_type="admin", entity_type="bundle", entity_id=b.id)
    await session.commit()
    rows = (await session.scalars(select(BundleMember).where(BundleMember.bundle_id == b.id))).all()
    return _bundle_out(b, rows, await _bundle_product_ids(session, b.id))


@router.patch("/bundles/{bundle_id}")
async def update_bundle(bundle_id: uuid.UUID, body: UpdateBundle, admin: AdminUser, session: Session):
    b = await session.get(Bundle, bundle_id)
    if not b:
        raise NotFound("بسته فروش")
    if (
        body.selection_mode == "manual"
        and b.selection_mode != "manual"
        and await session.scalar(select(func.count()).select_from(Product).where(Product.default_bundle_id == b.id))
    ):
        raise AppError(
            "DEFAULT_GROUP_IN_USE",
            "این بسته پیش‌فرض یک یا چند محصول است و نمی‌تواند دستی شود؛ ابتدا بسته پیش‌فرض آن محصولات را تغییر دهید.",
            409,
        )
    # Explicit null is meaningful only for sales_limit (= unlimited); other fields ignore null.
    for k, v in body.model_dump(exclude_unset=True, exclude={"panel_ids", "member_labels"}).items():
        if v is not None or k == "sales_limit":
            setattr(b, k, v)
    if body.panel_ids is not None:
        valid = (await session.scalars(select(Panel.id).where(Panel.id.in_(body.panel_ids)))).all()
        if len(valid) != len(set(body.panel_ids)):
            raise NotFound("بسته فروش")
        if b.selection_mode == "manual" and not body.panel_ids:
            raise AppError("BUNDLE_PANELS_REQUIRED", "بسته دستی باید حداقل یک پنل داشته باشد.", 400)
        # Sync instead of delete+insert so per-panel sold_count / limits survive edits.
        existing = {m.panel_id: m for m in (await session.scalars(select(BundleMember).where(BundleMember.bundle_id == b.id))).all()}
        wanted = list(dict.fromkeys(body.panel_ids))
        for pid, m in existing.items():
            if pid not in wanted:
                await session.delete(m)
        for i, pid in enumerate(wanted):
            if pid in existing:
                existing[pid].sort = i
            else:
                session.add(BundleMember(bundle_id=b.id, panel_id=pid, sort=i))
    if body.member_labels is not None:
        members = (await session.scalars(select(BundleMember).where(BundleMember.bundle_id == b.id))).all()
        for m in members:
            if m.panel_id in body.member_labels:
                m.label = (body.member_labels[m.panel_id] or "").strip() or None
    await link_bundle_to_resellers(session, b)  # turning "reseller sales" on opens the bundle for every reseller store
    audit.record(session, "bundle.updated", actor_id=admin.id, actor_type="admin", entity_type="bundle", entity_id=b.id)
    await session.commit()
    rows = (await session.scalars(select(BundleMember).where(BundleMember.bundle_id == b.id).order_by(BundleMember.sort))).all()
    return _bundle_out(b, rows, await _bundle_product_ids(session, b.id))


def _bundle_product_out(pp: BundleProduct, p: Product) -> dict:
    return {
        "product_id": p.id,
        "code": p.code,
        "name": p.name,
        "traffic_gb": p.traffic_gb,
        "duration_days": p.duration_days,
        "is_active": p.is_active,
        "reseller_enabled": p.reseller_enabled,
        "base_main_price": p.main_price,
        "base_reseller_price": p.reseller_price,
        "main_price": pp.main_price,
        "reseller_price": pp.reseller_price,
        "is_listed": pp.is_listed,
        "sort": pp.sort,
        "is_default": p.default_bundle_id == pp.bundle_id,
    }


@router.get("/bundles/{bundle_id}/products")
async def list_bundle_products(bundle_id: uuid.UUID, _: AdminUser, session: Session):
    if not await session.get(Bundle, bundle_id):
        raise NotFound("بسته فروش")
    rows = (
        await session.execute(
            select(BundleProduct, Product)
            .join(Product, Product.id == BundleProduct.product_id)
            .where(BundleProduct.bundle_id == bundle_id)
            .order_by(BundleProduct.sort, Product.sort)
        )
    ).all()
    return [_bundle_product_out(pp, p) for pp, p in rows]


@router.put("/bundles/{bundle_id}/products/{product_id}")
async def set_bundle_product(bundle_id: uuid.UUID, product_id: uuid.UUID, body: BundleProductIn, admin: AdminUser, session: Session):
    group, product = await session.get(Bundle, bundle_id), await session.get(Product, product_id)
    if not group or not product:
        raise NotFound("بسته فروش یا پکیج")
    if product.is_test:
        raise AppError("TEST_PRODUCT_NOT_SELLABLE", "پکیج تست در بسته فروخته نمی‌شود؛ فقط گروه پیش‌فرض دارد.", 422)
    pp = await session.scalar(select(BundleProduct).where(BundleProduct.bundle_id == group.id, BundleProduct.product_id == product.id))
    if not pp:
        pp = BundleProduct(bundle_id=group.id, product_id=product.id)
        session.add(pp)
    pp.main_price, pp.reseller_price, pp.is_listed, pp.sort = body.main_price, body.reseller_price, body.is_listed, body.sort
    audit.record(
        session,
        "bundle_product.set",
        actor_id=admin.id,
        actor_type="admin",
        entity_type="bundle",
        entity_id=group.id,
        data={
            "product_id": str(product.id),
            "main_price": body.main_price,
            "reseller_price": body.reseller_price,
            "is_listed": body.is_listed,
        },
    )
    hidden = await allocation.stores_below_cost(session, product, allocation.effective_prices(product, pp)[1], group.id)
    await session.commit()
    return {**_bundle_product_out(pp, product), "stores_below_cost": hidden}


@router.delete("/bundles/{bundle_id}/products/{product_id}")
async def remove_bundle_product(bundle_id: uuid.UUID, product_id: uuid.UUID, admin: AdminUser, session: Session):
    product = await session.get(Product, product_id)
    pp = await session.scalar(select(BundleProduct).where(BundleProduct.bundle_id == bundle_id, BundleProduct.product_id == product_id))
    if not pp or not product:
        raise NotFound("پکیج بسته")
    if product.default_bundle_id == bundle_id:
        raise AppError("PRODUCT_DEFAULT_BUNDLE", "این بسته، بسته پیش‌فرض این پکیج است. ابتدا بسته پیش‌فرض پکیج را عوض کنید.", 409)
    audit.record(
        session,
        "bundle_product.removed",
        actor_id=admin.id,
        actor_type="admin",
        entity_type="bundle",
        entity_id=bundle_id,
        data={"product_id": str(product_id)},
    )
    await session.execute(
        delete(StoreBundlePrice).where(StoreBundlePrice.bundle_id == bundle_id, StoreBundlePrice.product_id == product_id)
    )
    await session.delete(pp)
    await session.commit()
    return {"ok": True}


@router.get("/bundle-products/unassigned")
async def unassigned_products(_: AdminUser, session: Session):
    """Sellable products that no bundle sells: customers cannot buy them until an admin puts them in a bundle."""
    rows = (
        await session.scalars(
            select(Product)
            .where(
                Product.is_test.is_(False),
                Product.archived_at.is_(None),
                ~select(BundleProduct.id).where(BundleProduct.product_id == Product.id).exists(),
            )
            .order_by(Product.sort)
        )
    ).all()
    return [{"product_id": p.id, "code": p.code, "name": p.name, "is_active": p.is_active} for p in rows]


@router.put("/bundles/{bundle_id}/stores/{store_id}")
async def set_bundle_store(bundle_id: uuid.UUID, store_id: uuid.UUID, body: dict, admin: AdminUser, session: Session):
    if not await session.get(Bundle, bundle_id) or not await session.get(Store, store_id):
        raise NotFound("گروه یا فروشگاه")
    row = await session.scalar(select(StoreBundle).where(StoreBundle.bundle_id == bundle_id, StoreBundle.store_id == store_id))
    if not row:
        row = StoreBundle(bundle_id=bundle_id, store_id=store_id)
        session.add(row)
    row.is_enabled = bool(body.get("is_enabled", True))
    await session.commit()
    return {"ok": True, "is_enabled": row.is_enabled}


@router.delete("/bundles/{bundle_id}")
async def delete_bundle(bundle_id: uuid.UUID, admin: AdminUser, session: Session):
    b = await session.get(Bundle, bundle_id)
    if not b:
        raise NotFound("بسته فروش")
    products = [x.name for x in (await session.scalars(select(Product).where(Product.default_bundle_id == b.id))).all()]
    if products:
        raise AppError(
            "BUNDLE_IN_USE",
            f"این بسته، بسته پیش‌فرض محصول {_names(products)} است. ابتدا گروه آن محصولات را تغییر دهید.",
            409,
            {"products": products},
        )
    orders = await _count(session, Order, Order.bundle_id == b.id)
    if orders:
        raise AppError(
            "BUNDLE_HAS_HISTORY",
            f"{orders} سفارش از طریق این بسته ساخته شده است؛ حذف آن تاریخچه را خراب می‌کند. به‌جای حذف، بسته را غیرفعال کنید.",
            409,
            {"orders": orders},
        )
    await session.execute(delete(BundleMember).where(BundleMember.bundle_id == b.id))
    await session.execute(delete(StoreBundlePrice).where(StoreBundlePrice.bundle_id == b.id))
    await session.execute(delete(BundleProduct).where(BundleProduct.bundle_id == b.id))
    await session.execute(delete(StoreBundle).where(StoreBundle.bundle_id == b.id))
    audit.record(
        session, "bundle.deleted", actor_id=admin.id, actor_type="admin", entity_type="bundle", entity_id=b.id, data={"name": b.name}
    )
    await session.delete(b)
    await _commit_or_conflict(session, "این بسته")
    return {"ok": True}
