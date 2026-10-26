"""The reseller's customers and manual wallet top-up/correction (also used by the versioned reseller API)."""

import uuid

from fastapi import APIRouter
from sqlalchemy import select

from melorin.core import admin_telegram, audit, settings_store
from melorin.core.deps import OwnerCtx, Session
from melorin.core.errors import AppError, NotFound
from melorin.kernel.models.identity import User
from melorin.kernel.models.stores import StoreMembership
from melorin.modules.reseller.schemas import (
    CustomerOut,
    CustomerWalletAdjustment,
)
from melorin.modules.wallet import service as wallet

router = APIRouter(tags=["reseller"])


@router.get("/stores/{store_id}/reseller/customers", response_model=list[CustomerOut])
async def customers(ctx: OwnerCtx, session: Session):
    q = (
        select(User, StoreMembership)
        .join(StoreMembership, StoreMembership.user_id == User.id)
        .where(StoreMembership.store_id == ctx.store.id, StoreMembership.role == "customer")
        .order_by(StoreMembership.created_at.desc())
    )
    return [
        CustomerOut(
            user_id=u.id,
            display_name=u.display_name,
            email=u.email,
            status=m.status,
            joined_at=m.created_at,
            telegram_id=admin_telegram.admin_telegram_id(u.identities),
        )
        for u, m in (await session.execute(q)).all()
    ]


async def adjust_customer_wallet_core(
    session, ctx, customer_id: uuid.UUID, body: CustomerWalletAdjustment, actor_type: str = "reseller"
) -> dict:
    """Reseller tops up its own customer's wallet in its own store. The cash went to the reseller, so the
    contra account is the store's reseller_cash account (never Main Store, never another store)."""
    membership = await session.scalar(
        select(StoreMembership).where(
            StoreMembership.store_id == ctx.store.id, StoreMembership.user_id == customer_id, StoreMembership.role == "customer"
        )
    )
    if not membership or membership.status != "active":
        raise NotFound("مشتری")
    if body.amount == 0:
        raise AppError("BAD_AMOUNT", "مبلغ نامعتبر است.", 400)
    cap = await settings_store.get(session, "reseller.manual_topup_max")
    if cap and abs(body.amount) > int(cap):
        raise AppError("BAD_AMOUNT", "مبلغ از سقف مجاز شارژ دستی بیشتر است.", 400)
    w = await wallet.get_wallet(session, customer_id, ctx.store.id, currency=ctx.store.currency)
    # Lock before checking a negative correction. The check and ledger post
    # must observe one serialized balance, not two concurrent snapshots.
    await wallet.lock_wallets(session, [w])
    if body.amount < 0 and w.balance + body.amount < 0:
        raise AppError("INSUFFICIENT_FUNDS", "اصلاح موجودی نمی‌تواند کیف پول را منفی کند.", 409)
    postings = [
        wallet.Posting(body.amount, wallet=w, min_balance=0),
        wallet.Posting(-body.amount, account=wallet.acc_reseller_cash(ctx.store.id)),
    ]
    tx, created = await wallet.post(
        session,
        kind="reseller_manual_topup" if body.amount > 0 else "reseller_manual_correction",
        key=f"reseller-adjust:{ctx.store.id}:{body.idempotency_key}",
        currency=ctx.store.currency,
        store_id=ctx.store.id,
        postings=postings,
        actor_id=ctx.user.id,
        memo=(body.reason + (f" | ref: {body.reference}" if body.reference else ""))[:500],
    )
    if created:
        audit.record(
            session,
            "reseller.customer_wallet_adjusted",
            actor_id=ctx.user.id,
            actor_type=actor_type,
            entity_type="wallet",
            entity_id=w.id,
            store_id=ctx.store.id,
            data={
                "customer_id": str(customer_id),
                "amount": body.amount,
                "reason": body.reason,
                "reference": body.reference,
                "tx": str(tx.id),
            },
        )
    await session.commit()
    return {"ok": True, "balance": w.balance, "transaction_id": tx.id}


@router.post("/stores/{store_id}/reseller/customers/{customer_id}/wallet")
async def adjust_customer_wallet(customer_id: uuid.UUID, body: CustomerWalletAdjustment, ctx: OwnerCtx, session: Session):
    return await adjust_customer_wallet_core(session, ctx, customer_id, body)
