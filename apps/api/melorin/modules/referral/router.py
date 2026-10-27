"""Referral and commission endpoints - every one of them is about ONE store.

* customer plane  ``/stores/{store_id}/referral``                     his link, the store's programme and his standing there
* owner plane     ``/stores/{store_id}/referral-rules|referrals/...``  the reseller manages ONLY his own store's programme
* admin plane     ``/admin/referral-rules``, ``/admin/stores/{id}/referrals/summary``  any store
* ``/me/referrals`` stays as the session-store view used by the bots.
"""

import uuid

from fastapi import APIRouter
from pydantic import BaseModel, Field
from sqlalchemy import select

from melorin.core.deps import AdminUser, CurrentAuth, OwnerCtx, Session, StoreCtx
from melorin.core.errors import NotFound
from melorin.kernel.models.referral import Commission, CommissionRule, ReferralRelationship
from melorin.kernel.models.stores import Store
from melorin.modules.referral import service

router = APIRouter(tags=["referrals"])


class StoreRuleIn(BaseModel):
    """A plan of the store named in the URL (the store is never part of the body, so it cannot be spoofed)."""

    product_id: uuid.UUID | None = None
    kind: str = Field(pattern="^(signup_reward|commission)$")
    model: str = Field(pattern="^(fixed|percent)$")
    value: int = Field(ge=0)
    max_amount: int | None = Field(default=None, ge=0)
    is_active: bool = True


class CommissionRuleIn(StoreRuleIn):
    store_id: uuid.UUID


def _links(store: Store, code: str) -> dict:
    """Share links of THIS store: its own website and its own bot (never another store's)."""
    return {
        "web": f"https://{store.domain}/?ref={code}" if store.domain else None,
        "telegram": f"https://t.me/{store.bot_username}?start=ref_{code}" if store.bot_username else None,
    }


def _commission_out(c: Commission) -> dict:
    return {
        "id": c.id,
        "store_id": c.store_id,
        "order_id": c.order_id,
        "kind": c.kind,
        "amount": c.amount,
        "offset_amount": c.offset_amount,
        "reversed_amount": c.reversed_amount,
        "status": c.status,
        "currency": c.currency,
    }


# ------------------------------------------------------------------ customer plane
@router.get("/stores/{store_id}/referral")
async def store_referral(ctx: StoreCtx, session: Session):
    """The programme of the store the customer is in: how to invite, what it pays, and his own standing in THIS store only."""
    user, store = ctx.user, ctx.store
    rel_scope = (ReferralRelationship.referrer_user_id == user.id, ReferralRelationship.store_id == store.id)
    com_scope = (Commission.referrer_user_id == user.id, Commission.store_id == store.id)
    invited = len((await session.scalars(select(ReferralRelationship.id).where(*rel_scope))).all())
    commissions = (await session.scalars(select(Commission).where(*com_scope).order_by(Commission.created_at.desc()).limit(50))).all()
    earned = sum(c.amount - c.offset_amount - (c.reversed_amount if c.status == "reversed" else 0) for c in commissions)
    return {
        "store_id": store.id,
        "referral_code": user.referral_code,
        "links": _links(store, user.referral_code),
        "program": await service.program_for(session, store),
        "invited": invited,
        "earned": max(0, earned),
        "currency": store.currency,
        "commissions": [_commission_out(c) for c in commissions],
    }


@router.get("/me/referrals")
async def my_referrals(auth: CurrentAuth, session: Session):
    """Referral standing in the store this session belongs to (a customer's invites/commissions of another store stay there)."""
    user = auth.user
    rel_scope = [ReferralRelationship.referrer_user_id == user.id]
    com_scope = [Commission.referrer_user_id == user.id]
    if not auth.claims.is_admin:
        rel_scope.append(ReferralRelationship.store_id == auth.claims.store_id)
        com_scope.append(Commission.store_id == auth.claims.store_id)
    relationship = await session.scalar(select(ReferralRelationship).where(*rel_scope))
    commissions = (await session.scalars(select(Commission).where(*com_scope).order_by(Commission.created_at.desc()).limit(200))).all()
    store = await session.get(Store, auth.claims.store_id) if auth.claims.store_id else None
    return {
        "referral_code": user.referral_code,
        "referred_count": len((await session.scalars(select(ReferralRelationship).where(*rel_scope))).all()),
        "first_relationship_store_id": relationship.store_id if relationship else None,
        "links": _links(store, user.referral_code) if store else None,
        "program": await service.program_for(session, store) if store else None,
        "commissions": [_commission_out(c) for c in commissions],
    }


# ------------------------------------------------------------------ owner plane (reseller: his own store only)
@router.get("/stores/{store_id}/referral-rules")
async def owner_list_rules(ctx: OwnerCtx, session: Session):
    return [service.rule_out(r) for r in await service.list_rules(session, ctx.store.id)]


@router.put("/stores/{store_id}/referral-rules")
async def owner_upsert_rule(body: StoreRuleIn, ctx: OwnerCtx, session: Session):
    row = await service.upsert_rule(
        session,
        ctx.store,
        product_id=body.product_id,
        kind=body.kind,
        model=body.model,
        value=body.value,
        max_amount=body.max_amount,
        is_active=body.is_active,
        actor_id=ctx.user.id,
        actor_type="admin" if ctx.is_admin and not ctx.is_owner else "reseller",
    )
    await session.commit()
    return service.rule_out(row)


@router.get("/stores/{store_id}/referrals/summary")
async def owner_summary(ctx: OwnerCtx, session: Session):
    return await service.store_summary(session, ctx.store.id)


# ------------------------------------------------------------------ admin plane (any store)
@router.get("/admin/referral-rules")
async def list_rules(_: AdminUser, session: Session, store_id: uuid.UUID | None = None):
    if store_id:
        return [service.rule_out(r) for r in await service.list_rules(session, store_id)]
    rows = (await session.scalars(select(CommissionRule).order_by(CommissionRule.store_id, CommissionRule.kind))).all()
    return [service.rule_out(r) for r in rows]


@router.put("/admin/referral-rules")
async def upsert_rule(body: CommissionRuleIn, admin: AdminUser, session: Session):
    store = await session.get(Store, body.store_id)
    if not store:
        raise NotFound("فروشگاه")
    row = await service.upsert_rule(
        session,
        store,
        product_id=body.product_id,
        kind=body.kind,
        model=body.model,
        value=body.value,
        max_amount=body.max_amount,
        is_active=body.is_active,
        actor_id=admin.id,
        actor_type="admin",
    )
    await session.commit()
    return service.rule_out(row)


@router.get("/admin/stores/{store_id}/referrals/summary")
async def admin_summary(store_id: uuid.UUID, _: AdminUser, session: Session):
    if not await session.get(Store, store_id):
        raise NotFound("فروشگاه")
    return await service.store_summary(session, store_id)
