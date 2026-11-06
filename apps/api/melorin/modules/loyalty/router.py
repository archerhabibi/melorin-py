"""Customer loyalty club endpoints - every one of them is about ONE store (docs/22).

* customer plane  ``/stores/{store_id}/loyalty[...]``           his standing, the ladder, rewards, history, redeeming
* manage plane    ``/stores/{store_id}/loyalty/manage/...``      the reseller manages ONLY his own store's club; Admin manages any
  store, the main store included. The store is always the one in the URL, never a body field, so it cannot be spoofed.
"""

import datetime as dt
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Header, Query
from pydantic import BaseModel, Field
from sqlalchemy import select

from melorin.core import deps
from melorin.core.deps import Session, StoreContext, StoreCtx
from melorin.core.errors import Forbidden
from melorin.domain import loyalty as rules
from melorin.domain.loyalty import Tier
from melorin.kernel.models.loyalty import LoyaltyRedemption
from melorin.modules.loyalty import service

router = APIRouter(tags=["loyalty"])

_POINTS = 1_000_000_000  # upper bound that keeps every number far inside the column types
_MONEY = 10**12


# ------------------------------------------------------------------ manage plane context
async def manage_context(ctx: Annotated[StoreContext, Depends(deps.owner_store_context)]) -> StoreContext:
    """Admin (admin-panel session of a super admin) for ANY store; otherwise the real owner of a RESELLER store.

    It stands on ``owner_store_context`` so the session's channel is checked against THIS store before anything else
    (the guard in ``test_channel_binding`` refuses a ``{store_id}`` route without it); that dependency already lets an
    admin-panel session through for any store and a store's owner through for his own.
    """
    if ctx.is_admin:
        return ctx
    if not ctx.is_owner or ctx.store.kind != "reseller":
        raise Forbidden()
    return ctx


ManageCtx = Annotated[StoreContext, Depends(manage_context)]


def _actor(ctx: StoreContext) -> tuple[uuid.UUID, str]:
    return ctx.user.id, "admin" if ctx.is_admin else "reseller"


# ------------------------------------------------------------------ bodies
class ProgramIn(BaseModel):
    enabled: bool
    earn_unit: int = Field(ge=1, le=_MONEY)
    points_per_unit: int = Field(ge=1, le=_POINTS)
    max_points_per_order: int | None = Field(default=None, ge=1, le=_POINTS)
    first_order_bonus: int = Field(default=0, ge=0, le=_POINTS)
    referral_bonus: int = Field(default=0, ge=0, le=_POINTS)


class TierIn(BaseModel):
    name: str = Field(min_length=1, max_length=rules.MAX_NAME)
    min_points: int = Field(ge=0, le=_POINTS)
    multiplier_bp: int = Field(default=rules.BASE_MULTIPLIER_BP, ge=1, le=rules.MAX_MULTIPLIER_BP * 2)


class TiersIn(BaseModel):
    tiers: list[TierIn] = Field(min_length=1, max_length=rules.MAX_TIERS + 1)


class RewardIn(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    description: str | None = Field(default=None, max_length=2000)
    kind: str = Field(default="wallet_credit", max_length=20)
    value: int = Field(ge=1, le=_MONEY)
    cost_points: int = Field(ge=1, le=_POINTS)
    stock: int | None = Field(default=None, ge=0, le=_POINTS)
    per_user_limit: int | None = Field(default=None, ge=1, le=_POINTS)
    sort_order: int = Field(default=0, ge=-10_000, le=10_000)
    is_active: bool = True


class AdjustIn(BaseModel):
    user_id: uuid.UUID
    delta: int = Field(ge=-_POINTS, le=_POINTS)
    reason: str = Field(min_length=1, max_length=255)
    idempotency_key: str | None = Field(default=None, min_length=8, max_length=64)


# ------------------------------------------------------------------ customer plane
@router.get("/stores/{store_id}/loyalty")
async def my_club(ctx: StoreCtx, session: Session):
    """The club of the store the customer is in: his points and tier, the ladder, the rewards and his latest entries."""
    return await service.customer_summary(session, ctx.store, ctx.user.id)


@router.get("/stores/{store_id}/loyalty/history")
async def my_history(
    ctx: StoreCtx,
    session: Session,
    limit: int = Query(default=20, ge=1, le=service.HISTORY_MAX),
    before: dt.datetime | None = None,
):
    """One page of his points entries in THIS store (newest first); pass the last ``created_at`` as ``before`` for the next page."""
    rows, more = await service.history(session, ctx.store.id, ctx.user.id, limit=limit, before=before)
    return {"items": [service.tx_out(t) for t in rows], "has_more": more}


@router.post("/stores/{store_id}/loyalty/rewards/{reward_id}/redeem")
async def redeem_reward(
    reward_id: uuid.UUID,
    ctx: StoreCtx,
    session: Session,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key", min_length=8, max_length=100),
):
    """Spend points on a reward. A retry with the same ``Idempotency-Key`` returns the first result and spends nothing more."""
    redemption, created = await service.redeem(session, ctx.store, ctx.user, reward_id, idempotency_key=idempotency_key)
    await session.commit()
    acc = await service.get_account(session, ctx.store.id, ctx.user.id)
    return {
        "id": redemption.id,
        "reward_id": redemption.reward_id,
        "points_spent": redemption.points_spent,
        "value": redemption.value,
        "currency": redemption.currency,
        "balance": acc.balance,
        "replayed": not created,
    }


@router.get("/stores/{store_id}/loyalty/redemptions")
async def my_redemptions(ctx: StoreCtx, session: Session, limit: int = Query(default=20, ge=1, le=service.HISTORY_MAX)):
    rows = (
        await session.scalars(
            select(LoyaltyRedemption)
            .where(LoyaltyRedemption.store_id == ctx.store.id, LoyaltyRedemption.user_id == ctx.user.id)
            .order_by(LoyaltyRedemption.created_at.desc())
            .limit(limit)
        )
    ).all()
    return [
        {
            "id": r.id,
            "reward_id": r.reward_id,
            "points_spent": r.points_spent,
            "value": r.value,
            "currency": r.currency,
            "created_at": r.created_at,
        }
        for r in rows
    ]


# ------------------------------------------------------------------ manage plane (owner of a reseller store, or Admin)
@router.get("/stores/{store_id}/loyalty/manage/program")
async def get_program(ctx: ManageCtx, session: Session):
    row = await service.get_program(session, ctx.store.id)
    tiers = await service.load_tiers(session, ctx.store.id)
    return {
        "store_id": ctx.store.id,
        "currency": ctx.store.currency,
        "program": service.program_out(row),
        "tiers": [service.tier_out(t) for t in tiers],
        "default_tiers": [{"name": t.name, "min_points": t.min_points, "multiplier_bp": t.multiplier_bp} for t in rules.DEFAULT_TIERS],
    }


@router.put("/stores/{store_id}/loyalty/manage/program")
async def put_program(body: ProgramIn, ctx: ManageCtx, session: Session):
    actor_id, actor_type = _actor(ctx)
    row = await service.upsert_program(
        session,
        ctx.store,
        enabled=body.enabled,
        earn_unit=body.earn_unit,
        points_per_unit=body.points_per_unit,
        max_points_per_order=body.max_points_per_order,
        first_order_bonus=body.first_order_bonus,
        referral_bonus=body.referral_bonus,
        actor_id=actor_id,
        actor_type=actor_type,
    )
    await session.commit()
    return service.program_out(row)


@router.put("/stores/{store_id}/loyalty/manage/tiers")
async def put_tiers(body: TiersIn, ctx: ManageCtx, session: Session):
    """Replace the whole ladder at once, so it is always valid: it starts at 0 points and the thresholds rise."""
    actor_id, actor_type = _actor(ctx)
    rows = await service.replace_tiers(
        session, ctx.store, [Tier(t.name, t.min_points, t.multiplier_bp) for t in body.tiers], actor_id=actor_id, actor_type=actor_type
    )
    await session.commit()
    return [service.tier_out(t) for t in rows]


@router.get("/stores/{store_id}/loyalty/manage/rewards")
async def list_rewards(ctx: ManageCtx, session: Session):
    return [service.reward_out(r) for r in await service.list_rewards(session, ctx.store.id)]


@router.post("/stores/{store_id}/loyalty/manage/rewards", status_code=201)
async def create_reward(body: RewardIn, ctx: ManageCtx, session: Session):
    actor_id, actor_type = _actor(ctx)
    row = await service.save_reward(session, ctx.store, None, actor_id=actor_id, actor_type=actor_type, **body.model_dump())
    await session.commit()
    return service.reward_out(row)


@router.put("/stores/{store_id}/loyalty/manage/rewards/{reward_id}")
async def update_reward(reward_id: uuid.UUID, body: RewardIn, ctx: ManageCtx, session: Session):
    actor_id, actor_type = _actor(ctx)
    row = await service.save_reward(session, ctx.store, reward_id, actor_id=actor_id, actor_type=actor_type, **body.model_dump())
    await session.commit()
    return service.reward_out(row)


@router.get("/stores/{store_id}/loyalty/manage/summary")
async def club_summary(ctx: ManageCtx, session: Session):
    return await service.store_summary(session, ctx.store.id)


@router.post("/stores/{store_id}/loyalty/manage/adjust")
async def adjust_points(body: AdjustIn, ctx: ManageCtx, session: Session):
    """Grant (+) or deduct (-) points of one member of this store; the reason is mandatory and audited."""
    actor_id, actor_type = _actor(ctx)
    tx = await service.adjust(
        session,
        ctx.store,
        body.user_id,
        body.delta,
        reason=body.reason,
        actor_id=actor_id,
        actor_type=actor_type,
        idempotency_key=body.idempotency_key,
    )
    await session.commit()
    return service.tx_out(tx)
