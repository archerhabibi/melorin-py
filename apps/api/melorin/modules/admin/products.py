"""Admin API - products routes (split from the former 1,900-line router; paths unchanged)."""

import logging
import uuid
from fastapi import APIRouter, Query
from sqlalchemy import delete, select
from melorin.core import audit
from melorin.core.deps import AdminUser, Session
from melorin.core.errors import AppError, NotFound
from melorin.kernel.models.catalog import Coupon, Product, StoreBundlePrice, StoreProduct
from melorin.kernel.models.orders import Order
from melorin.kernel.models.referral import CommissionRule
from melorin.kernel.models.stores import Store
from melorin.modules.reseller.linking import link_product_to_resellers
from melorin.kernel.models.vpn import Server, VpnAccount
from melorin.kernel.models.bundles import Bundle, BundleProduct
from melorin.modules.admin.schemas import (
    Availability,
    CreateProduct,
    ProductOut,
    ProductPatch,
)
from melorin.modules.admin._common import (
    _commit_or_conflict,
    _count,
    _names,
)

router = APIRouter(prefix="/admin", tags=["admin"])
log = logging.getLogger("melorin.admin")


# ----- Catalog -----
async def _check_default_group(session, group_id) -> None:
    """A product's default group is applied by the core to every channel, so it must be usable without any choice by the buyer."""
    group = await session.get(Bundle, group_id)
    if not group:
        raise NotFound("بسته فروش")
    if not group.is_enabled:
        raise AppError("DEFAULT_GROUP_DISABLED", "بسته پیش‌فرض محصول باید فعال باشد.", 422)
    if group.selection_mode != "automatic":
        raise AppError("DEFAULT_GROUP_MANUAL", "بسته پیش‌فرض محصول باید انتخاب خودکار باشد؛ ربات و سایت پنل را انتخاب نمی‌کنند.", 422)


async def _add_product_to_all_bundles(session, product: Product) -> None:
    """Every sellable package is sold in every sales bundle by default (the admin can hide it per bundle)."""
    if product.is_test or product.archived_at is not None:
        return
    have = set((await session.scalars(select(BundleProduct.bundle_id).where(BundleProduct.product_id == product.id))).all())
    for bid in (await session.scalars(select(Bundle.id))).all():
        if bid not in have:
            session.add(BundleProduct(bundle_id=bid, product_id=product.id, is_listed=True, sort=0))


@router.post("/products", response_model=ProductOut, status_code=201)
async def create_product(body: CreateProduct, admin: AdminUser, session: Session):
    if await session.scalar(select(Product.id).where(Product.code == body.code)):
        raise AppError("PRODUCT_CODE_EXISTS", "کد محصول تکراری است.", 409)
    if body.default_bundle_id is not None:
        await _check_default_group(session, body.default_bundle_id)
    data = body.model_dump()
    if data.get("reseller_price") is None:
        data["reseller_price"] = body.main_price  # per-bundle cooperation prices override this
    p = Product(**data)
    session.add(p)
    await session.flush()
    if p.default_bundle_id and not p.is_test:
        await _ensure_bundle_product(session, p.default_bundle_id, p.id)
    await _add_product_to_all_bundles(session, p)
    main = await session.scalar(select(Store).where(Store.kind == "main", Store.status == "active"))
    if main:
        session.add(
            StoreProduct(
                product_id=p.id,
                store_id=main.id,
                is_enabled=True,
                is_listed=True,
                customer_price=None,
            )
        )
    await link_product_to_resellers(session, p)  # reseller stores get the new package too
    audit.record(
        session,
        "product.created",
        actor_id=admin.id,
        actor_type="admin",
        entity_type="product",
        entity_id=p.id,
        data=body.model_dump(mode="json"),
    )
    await session.commit()
    return p


@router.get("/products", response_model=list[ProductOut])
async def list_products(_: AdminUser, session: Session):
    return (await session.scalars(select(Product).order_by(Product.sort, Product.created_at.desc()))).all()


@router.patch("/products/{product_id}", response_model=ProductOut)
async def update_product(product_id: uuid.UUID, body: ProductPatch, admin: AdminUser, session: Session):
    p = await session.get(Product, product_id)
    if not p:
        raise NotFound("محصول")
    before = {
        "main_price": p.main_price,
        "reseller_price": p.reseller_price,
        "duration_days": p.duration_days,
        "traffic_gb": p.traffic_gb,
        "is_active": p.is_active,
        "reseller_enabled": p.reseller_enabled,
        "default_bundle_id": str(p.default_bundle_id) if p.default_bundle_id else None,
    }
    # Explicit null clears these optional fields (e.g. "unlimited devices"); other fields ignore null.
    changes = {
        k: v
        for k, v in body.model_dump(exclude_unset=True).items()
        if v is not None or k in {"max_devices", "description", "category", "default_bundle_id"}
    }
    if changes.get("default_bundle_id") is not None:
        await _check_default_group(session, changes["default_bundle_id"])
    if "code" in changes and changes["code"] != p.code and await session.scalar(select(Product.id).where(Product.code == changes["code"])):
        raise AppError("PRODUCT_CODE_EXISTS", "کد محصول تکراری است.", 409)
    for k, v in changes.items():
        setattr(p, k, v)
    if changes.get("default_bundle_id") is not None and not p.is_test:
        await _ensure_bundle_product(session, p.default_bundle_id, p.id)
    audit.record(
        session,
        "product.updated",
        actor_id=admin.id,
        actor_type="admin",
        entity_type="product",
        entity_id=p.id,
        data={"before": before, "after": {k: (str(v) if isinstance(v, uuid.UUID) else v) for k, v in changes.items()}},
    )
    await session.commit()
    return p


@router.get("/products/{product_id}/availability", response_model=dict)
async def get_availability(product_id: uuid.UUID, admin: AdminUser, session: Session, store_id: uuid.UUID = Query(...)):
    """Current per-store availability, so the admin form shows the stored state instead of blind defaults."""
    p = await session.get(Product, product_id)
    st = await session.get(Store, store_id)
    if not p or not st:
        raise NotFound("محصول یا فروشگاه")
    row = await session.scalar(select(StoreProduct).where(StoreProduct.product_id == p.id, StoreProduct.store_id == st.id))
    if not row:
        return {"store_id": str(st.id), "enabled": True, "listed": True, "customer_price": None}
    return {"store_id": str(st.id), "enabled": row.is_enabled, "listed": row.is_listed, "customer_price": row.customer_price}


@router.post("/products/{product_id}/availability", response_model=dict)
async def set_availability(product_id: uuid.UUID, body: Availability, admin: AdminUser, session: Session):
    p = await session.get(Product, product_id)
    st = await session.get(Store, body.store_id)
    if not p or not st:
        raise NotFound("محصول یا فروشگاه")
    row = await session.scalar(select(StoreProduct).where(StoreProduct.product_id == p.id, StoreProduct.store_id == st.id))
    if not row:
        row = StoreProduct(product_id=p.id, store_id=st.id)
        session.add(row)
    # customer_price belongs to the reseller (PUT /stores/{id}/reseller/prices/{product_id}); the admin only
    # decides availability, so a reseller store keeps its own price. Main-store rows never carry one.
    row.is_enabled, row.is_listed = body.enabled, body.listed
    if st.kind != "reseller":
        row.customer_price = None
    audit.record(
        session,
        "catalog.availability_updated",
        actor_id=admin.id,
        actor_type="admin",
        entity_type="product",
        entity_id=p.id,
        store_id=st.id,
    )
    await session.commit()
    return {"ok": True}


async def _ensure_bundle_product(session, group_id, product_id) -> None:
    """A product's default bundle must also sell it, otherwise the default would be unusable at checkout."""
    if not await session.scalar(
        select(BundleProduct.id).where(BundleProduct.bundle_id == group_id, BundleProduct.product_id == product_id)
    ):
        session.add(BundleProduct(bundle_id=group_id, product_id=product_id, is_listed=True, sort=0))


@router.delete("/products/{product_id}")
async def delete_product(product_id: uuid.UUID, admin: AdminUser, session: Session):
    p = await session.get(Product, product_id)
    if not p:
        raise NotFound("محصول")
    orders = await _count(session, Order, Order.product_id == p.id)
    accounts = await _count(session, VpnAccount, VpnAccount.product_id == p.id)
    if orders or accounts:
        raise AppError(
            "PRODUCT_HAS_HISTORY",
            f"این محصول {orders} سفارش و {accounts} اکانت دارد؛ حذف آن تاریخچه فروش را خراب می‌کند. به‌جای حذف، محصول را غیرفعال کنید.",
            409,
            {"orders": orders, "accounts": accounts},
        )
    servers = [
        s.name
        for s in (await session.scalars(select(Server).where(Server.product_codes.is_not(None)))).all()
        if p.code in (s.product_codes or [])
    ]
    if servers:
        raise AppError(
            "PRODUCT_USED_BY_SERVERS",
            f"این محصول در فهرست محصولاتِ سرورهای {_names(servers)} است. ابتدا آن را از فهرست سرورها بردارید.",
            409,
            {"servers": servers},
        )
    coupons = [
        c.code
        for c in (await session.scalars(select(Coupon).where(Coupon.product_ids.is_not(None)))).all()
        if str(p.id) in {str(x) for x in (c.product_ids or [])}
    ]
    if coupons:
        raise AppError(
            "PRODUCT_USED_BY_COUPONS",
            f"این محصول در محدوده‌ی کد تخفیف {_names(coupons)} است. ابتدا کد تخفیف را ویرایش یا غیرفعال کنید.",
            409,
            {"coupons": coupons},
        )
    rules = await _count(session, CommissionRule, CommissionRule.product_id == p.id)
    if rules:
        raise AppError(
            "PRODUCT_USED_BY_COMMISSION_RULES",
            f"برای این محصول {rules} قانون پورسانت/پاداش اختصاصی تعریف شده است. ابتدا آن‌ها را حذف کنید.",
            409,
            {"rules": rules},
        )
    await session.execute(delete(StoreBundlePrice).where(StoreBundlePrice.product_id == p.id))
    await session.execute(delete(StoreProduct).where(StoreProduct.product_id == p.id))
    await session.execute(delete(BundleProduct).where(BundleProduct.product_id == p.id))
    audit.record(
        session,
        "product.deleted",
        actor_id=admin.id,
        actor_type="admin",
        entity_type="product",
        entity_id=p.id,
        data={"code": p.code, "name": p.name},
    )
    await session.delete(p)
    await _commit_or_conflict(session, "این محصول")
    return {"ok": True}
