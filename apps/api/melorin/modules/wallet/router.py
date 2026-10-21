from fastapi import APIRouter, Depends
from sqlalchemy import func, select

from melorin.core.deps import Session, StoreCtx
from melorin.core.pagination import Page, PageParams
from melorin.modules.wallet import service
from melorin.kernel.models.wallet import LedgerEntry, LedgerTransaction
from melorin.modules.wallet.schemas import LedgerEntryOut, WalletOut

router = APIRouter(prefix="/stores/{store_id}/wallet", tags=["wallet"])


@router.get("", response_model=WalletOut)
async def my_wallet(ctx: StoreCtx, session: Session):
    w = await service.get_wallet(session, ctx.user.id, ctx.store.id, currency=ctx.store.currency)
    await session.commit()
    return WalletOut.model_validate(w, from_attributes=True)


@router.get("/transactions", response_model=Page[LedgerEntryOut])
async def my_transactions(ctx: StoreCtx, session: Session, page: PageParams = Depends()):
    w = await service.get_wallet(session, ctx.user.id, ctx.store.id, currency=ctx.store.currency)
    q = (
        select(LedgerEntry, LedgerTransaction)
        .join(LedgerTransaction, LedgerTransaction.id == LedgerEntry.transaction_id)
        .where(LedgerEntry.wallet_id == w.id)
    )
    total = await session.scalar(select(func.count()).select_from(LedgerEntry).where(LedgerEntry.wallet_id == w.id))
    rows = (await session.execute(q.order_by(LedgerEntry.created_at.desc()).limit(page.limit).offset(page.offset))).all()
    items = [
        LedgerEntryOut(
            transaction_id=t.id,
            kind=t.kind,
            amount=e.amount,
            balance_after=e.balance_after,
            memo=t.memo,
            order_id=t.order_id,
            created_at=e.created_at,
        )
        for e, t in rows
    ]
    return Page(items=items, total=total or 0, limit=page.limit, offset=page.offset)
