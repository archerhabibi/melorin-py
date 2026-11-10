from fastapi import APIRouter, Depends
from melorin.core import admin_telegram
from melorin.core.deps import Session, StoreCtx
from melorin.core.pagination import Page, PageParams
from melorin.modules.wallet import queries, service
from melorin.modules.wallet.schemas import LedgerEntryOut, WalletOut

router = APIRouter(prefix="/stores/{store_id}/wallet", tags=["wallet"])


@router.get("", response_model=WalletOut)
async def my_wallet(ctx: StoreCtx, session: Session):
    w = await service.get_wallet(session, ctx.user.id, ctx.store.id, currency=ctx.store.currency)
    await session.commit()
    out = WalletOut.model_validate(w, from_attributes=True)
    out.telegram_id = await admin_telegram.current(session, ctx.user.id)
    return out


@router.get("/transactions", response_model=Page[LedgerEntryOut])
async def my_transactions(ctx: StoreCtx, session: Session, page: PageParams = Depends()):
    w = await service.get_wallet(session, ctx.user.id, ctx.store.id, currency=ctx.store.currency)
    total, rows = await queries.ledger_page(session, w.id, limit=page.limit, offset=page.offset)
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
    return Page(items=items, total=total, limit=page.limit, offset=page.offset)
