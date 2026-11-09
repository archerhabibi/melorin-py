"""The reseller owner's own store: profile + debt state, branding, order report."""

from fastapi import APIRouter
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from melorin.core import audit, settings_store
from melorin.core.deps import OwnerCtx, Session, main_store
from melorin.domain.order_kinds import not_manual
from melorin.kernel.models.orders import Order
from melorin.kernel.models.stores import ResellerProfile
from melorin.modules.reseller.schemas import (
    StoreBrandingUpdate,
)
from melorin.modules.vpn import sub_branding
from melorin.modules.wallet import service as wallet

router = APIRouter(tags=["reseller"])


@router.get("/stores/{store_id}/reseller/profile")
async def profile(ctx: OwnerCtx, session: Session):
    p = await session.scalar(select(ResellerProfile).where(ResellerProfile.store_id == ctx.store.id))
    main = await main_store(session)
    w = await wallet.get_wallet(session, ctx.store.owner_user_id, main.id, currency=main.currency)
    await session.commit()
    near = float(await settings_store.get(session, "debt.near_ratio") or 0.8)
    from melorin.domain import debt

    return {
        "store_id": ctx.store.id,
        "store_name": ctx.store.name,
        "store_currency": ctx.store.currency,
        "debt_limit": p.debt_limit if p else 0,
        "sales_enabled": p.sales_enabled if p else False,
        "api_enabled": p.api_enabled if p else False,
        "main_wallet": {"balance": w.balance, "currency": w.currency, "debt_state": debt.state(w.balance, p.debt_limit if p else 0, near)},
    }


@router.patch("/stores/{store_id}/reseller/branding")
async def branding(body: StoreBrandingUpdate, ctx: OwnerCtx, session: Session):
    if body.branding is not None:
        # "sub" / "sub_applied" belong to the validated subscription-branding endpoints and the admin apply action: this generic
        # patch can neither set nor wipe them.
        keep = {k: v for k, v in (ctx.store.branding or {}).items() if k in ("sub", "sub_applied")}
        ctx.store.branding = {**{k: v for k, v in body.branding.items() if k not in ("sub", "sub_applied")}, **keep}
    if body.bot_messages is not None:
        ctx.store.bot_messages = body.bot_messages
    audit.record(
        session, "reseller.branding_updated", actor_id=ctx.user.id, entity_type="store", entity_id=ctx.store.id, store_id=ctx.store.id
    )
    await session.commit()
    return {"ok": True}


@router.get("/stores/{store_id}/reseller/reports")
async def report(ctx: OwnerCtx, session: Session):
    rows = (
        await session.execute(
            select(Order.status, func.count(), func.coalesce(func.sum(Order.total), 0), func.coalesce(func.sum(Order.reseller_cost), 0))
            .where(Order.store_id == ctx.store.id, not_manual(Order.kind))
            .group_by(Order.status)
        )
    ).all()
    return {
        "store_id": ctx.store.id,
        "currency": ctx.store.currency,
        "orders": [{"status": s, "count": n, "total": total, "reseller_cost": cost} for s, n, total, cost in rows],
    }


class SubBrandingIn(BaseModel):
    display_name: str | None = Field(default=None, max_length=64)
    support_url: str | None = Field(default=None, max_length=512)
    logo_url: str | None = Field(default=None, max_length=512)


@router.get("/stores/{store_id}/reseller/sub-branding")
async def sub_branding_get(ctx: OwnerCtx):
    """The three fields the owner chose for the subscription page. Saved in Melorin only; the admin puts them on the panel."""
    return {"fields": sub_branding.get(ctx.store), "applied_on": sorted((ctx.store.branding or {}).get("sub_applied") or {})}


@router.put("/stores/{store_id}/reseller/sub-branding")
async def sub_branding_put(body: SubBrandingIn, ctx: OwnerCtx, session: Session):
    """Save name / support link / logo (plain text and https links only; an empty string clears a field). Nothing is sent to a panel."""
    fields = sub_branding.save(ctx.store, body.model_dump(exclude_unset=True))
    audit.record(
        session,
        "reseller.sub_branding_saved",
        actor_id=ctx.user.id,
        entity_type="store",
        entity_id=ctx.store.id,
        store_id=ctx.store.id,
        data={"fields": sorted(fields)},
    )
    await session.commit()
    return {"fields": fields, "note": "ذخیره شد. اعمال روی صفحهٔ اشتراک پس از تأیید مدیر انجام می‌شود."}
