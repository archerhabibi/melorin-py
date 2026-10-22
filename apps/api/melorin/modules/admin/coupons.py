"""Admin API - coupons routes (split from the former 1,900-line router; paths unchanged)."""

import logging
import uuid
from fastapi import APIRouter
from sqlalchemy import select
from melorin.core import audit
from melorin.core.deps import AdminUser, Session
from melorin.core.errors import AppError, NotFound
from melorin.modules.catalog.schemas import AdminCouponIn, CouponPatch
from melorin.kernel.models.catalog import Coupon

router = APIRouter(prefix="/admin", tags=["admin"])
log = logging.getLogger("melorin.admin")


# ----- Coupon administration: Admin may create Store or explicit domain coupons -----
@router.get("/coupons")
async def list_coupons(_: AdminUser, session: Session, store_id: uuid.UUID | None = None):
    q = select(Coupon).order_by(Coupon.created_at.desc())
    if store_id:
        q = q.where(Coupon.store_id == store_id)
    from melorin.modules.catalog.service import coupon_out

    return [coupon_out(c) for c in (await session.scalars(q)).all()]


@router.post("/coupons", status_code=201)
async def create_admin_coupon(body: AdminCouponIn, admin: AdminUser, session: Session):
    from melorin.domain import coupon as cdom
    from melorin.modules.catalog.service import norm_code

    code = norm_code(body.code)
    if body.scope == "store" and not body.store_id:
        raise AppError("COUPON_SCOPE_FORBIDDEN", "برای Coupon فروشگاه باید store_id مشخص شود.", 400)
    if body.scope == "domain" and not (body.allowed_store_ids or body.allowed_store_kinds):
        raise AppError("COUPON_SCOPE_FORBIDDEN", "دامنه Coupon خالی است.", 400)
    rule = cdom.CouponRule(
        code=code,
        creator_type="admin",
        scope=body.scope,
        store_id=str(body.store_id) if body.store_id else None,
        allowed_store_ids=tuple(str(x) for x in body.allowed_store_ids or []),
        allowed_store_kinds=tuple(body.allowed_store_kinds or []),
        percent_bp=body.percent_bp,
        fixed=body.fixed,
        max_discount=body.max_discount,
        min_amount=body.min_amount,
        starts_at=body.starts_at,
        ends_at=body.ends_at,
        max_redemptions=body.max_redemptions,
        per_customer_limit=body.per_customer_limit,
        currency=body.currency,
        status=body.status,
    )
    try:
        cdom.validate_definition(rule)
    except cdom.CouponError as e:
        raise AppError(e.code, e.message, 400) from e
    owner_key = "admin" if body.scope == "domain" else str(body.store_id)
    if await session.scalar(select(Coupon.id).where(Coupon.owner_key == owner_key, Coupon.code == code)):
        raise AppError("COUPON_EXISTS", "این کد تخفیف قبلاً ساخته شده است.", 409)
    c = Coupon(
        code=code,
        owner_key=owner_key,
        store_id=body.store_id,
        scope=body.scope,
        allowed_store_ids=[str(x) for x in body.allowed_store_ids or []] or None,
        allowed_store_kinds=body.allowed_store_kinds,
        creator_type="admin",
        creator_id=admin.id,
        funded_by=body.funded_by,
        percent_bp=body.percent_bp,
        fixed=body.fixed,
        max_discount=body.max_discount,
        min_amount=body.min_amount,
        currency=body.currency,
        starts_at=body.starts_at,
        ends_at=body.ends_at,
        max_redemptions=body.max_redemptions,
        per_customer_limit=body.per_customer_limit,
        product_ids=[str(x) for x in body.product_ids or []] or None,
        status=body.status,
    )
    session.add(c)
    audit.record(
        session,
        "admin.coupon.created",
        actor_id=admin.id,
        actor_type="admin",
        entity_type="coupon",
        entity_id=c.id,
        store_id=body.store_id,
        data={"code": code, "scope": body.scope, "funded_by": body.funded_by},
    )
    await session.commit()
    from melorin.modules.catalog.service import coupon_out

    return coupon_out(c)


@router.patch("/coupons/{coupon_id}")
async def patch_admin_coupon(coupon_id: uuid.UUID, body: CouponPatch, admin: AdminUser, session: Session):
    c = await session.get(Coupon, coupon_id, with_for_update=True)
    if not c:
        raise NotFound("کد تخفیف")
    for k, v in body.model_dump(exclude_none=True).items():
        setattr(c, k, v)
    audit.record(
        session, "admin.coupon.updated", actor_id=admin.id, actor_type="admin", entity_type="coupon", entity_id=c.id, store_id=c.store_id
    )
    await session.commit()
    from melorin.modules.catalog.service import coupon_out

    return coupon_out(c)
