"""Referral and commission visibility/configuration endpoints."""
import uuid

from fastapi import APIRouter
from pydantic import BaseModel, Field
from sqlalchemy import select

from melorin.core.deps import AdminUser, CurrentUser, Session
from melorin.core.errors import AppError
from melorin.modules.referral.models import Commission, CommissionRule, ReferralRelationship

router = APIRouter(tags=["referrals"])


class CommissionRuleIn(BaseModel):
    store_id: uuid.UUID
    product_id: uuid.UUID | None = None
    kind: str = Field(pattern="^(signup_reward|commission)$")
    model: str = Field(pattern="^(fixed|percent)$")
    value: int = Field(ge=0)
    max_amount: int | None = Field(default=None, ge=0)
    is_active: bool = True


@router.get("/me/referrals")
async def my_referrals(user: CurrentUser, session: Session):
    relationship = await session.scalar(select(ReferralRelationship).where(ReferralRelationship.referrer_user_id == user.id))
    commissions = (await session.scalars(
        select(Commission).where(Commission.referrer_user_id == user.id).order_by(Commission.created_at.desc()).limit(200)
    )).all()
    return {
        "referral_code": user.referral_code,
        "referred_count": len((await session.scalars(
            select(ReferralRelationship).where(ReferralRelationship.referrer_user_id == user.id)
        )).all()),
        "first_relationship_store_id": relationship.store_id if relationship else None,
        "commissions": [
            {"id": c.id, "store_id": c.store_id, "order_id": c.order_id, "kind": c.kind, "amount": c.amount,
             "offset_amount": c.offset_amount, "reversed_amount": c.reversed_amount, "status": c.status, "currency": c.currency}
            for c in commissions
        ],
    }


@router.get("/admin/referral-rules")
async def list_rules(_: AdminUser, session: Session):
    rows = (await session.scalars(select(CommissionRule).order_by(CommissionRule.store_id, CommissionRule.kind))).all()
    return [rule_out(r) for r in rows]


@router.put("/admin/referral-rules")
async def upsert_rule(body: CommissionRuleIn, admin: AdminUser, session: Session):
    row = await session.scalar(select(CommissionRule).where(
        CommissionRule.store_id == body.store_id,
        CommissionRule.product_id == body.product_id,
        CommissionRule.kind == body.kind,
    ))
    if not row:
        row = CommissionRule(store_id=body.store_id, product_id=body.product_id, kind=body.kind)
        session.add(row)
    row.model, row.value, row.max_amount, row.is_active = body.model, body.value, body.max_amount, body.is_active
    await session.commit()
    return rule_out(row)


def rule_out(r: CommissionRule) -> dict:
    return {"id": r.id, "store_id": r.store_id, "product_id": r.product_id, "kind": r.kind, "model": r.model, "value": r.value, "max_amount": r.max_amount, "is_active": r.is_active}
