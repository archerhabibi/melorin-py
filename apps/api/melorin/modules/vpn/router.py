"""Customer view of VPN accounts. EVERY route is store-scoped: a customer only ever gets his own accounts of the store he is
using (``core.scope.StoreScope``); accounts bought in another store or bot do not exist here. There is deliberately no
"all my accounts" route. The platform owner uses ``/admin/vpn-accounts``."""

import uuid

from fastapi import APIRouter, Query, Response

from melorin.core.deps import Session, StoreCtx
from melorin.core.errors import NotFound
from melorin.core.scope import StoreScope
from melorin.modules.vpn import inquiry, live, returns
from melorin.modules.vpn.qr import render_qr_png
from melorin.modules.vpn.schemas import VpnAccountOut

router = APIRouter(prefix="/stores/{store_id}/vpn-accounts", tags=["vpn-accounts"])


out = inquiry.account_out


async def _with_returns(session, scope, accounts):
    readings = await live.page_readings(session, accounts)  # ONE live read of the page: usage for the return rule AND the overlay
    used = {aid: r.traffic_used_bytes for aid, r in readings.items() if r is not None}
    elig = await returns.eligibility_for(session, scope, accounts, used=used)
    outs = [returns.account_view(a, elig.get(a.id)) for a in accounts]
    return await live.overlay_page(session, outs, accounts, readings)  # the panel's numbers, never an old copy


@router.get("", response_model=list[VpnAccountOut])
async def mine(
    ctx: StoreCtx,
    session: Session,
    response: Response,
    q: str | None = Query(None, max_length=200, description="search in the account name"),
    state: str | None = Query(None, pattern="^(active|expiring|expired)$", description="filter chip"),
    limit: int = Query(100, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    """The caller's OWN accounts in THIS store (list and search): the scope lives in ``inquiry.customer_accounts``."""
    rows, total = await inquiry.customer_accounts(session, StoreScope.of(ctx), q=q, state=state, limit=limit, offset=offset)
    response.headers["X-Total-Count"] = str(total)
    return await _with_returns(session, StoreScope.of(ctx), rows)


@router.get("/summary")
async def summary(ctx: StoreCtx, session: Session):
    """Chip counters (total / active / expiring / expired) over the caller's OWN accounts in THIS store."""
    return await inquiry.customer_summary(session, StoreScope.of(ctx))


@router.get("/return-rules")
async def return_rules(ctx: StoreCtx):
    """The rules as text and numbers, so every channel shows the same words."""
    return {
        "text": returns.RULES_TEXT,
        "max_days": returns.RETURN_MAX_DAYS,
        "max_usage_percent": returns.RETURN_MAX_USAGE_PERCENT,
        "daily_limit": returns.RETURN_DAILY_LIMIT,
    }


@router.post("/{account_id}/refresh", response_model=VpnAccountOut)
async def refresh(account_id: uuid.UUID, ctx: StoreCtx, session: Session, response: Response):
    """Re-read this account from its VPN panel (live expiry, usage, links) and return the fresh card."""
    a = await inquiry.customer_account(session, StoreScope.of(ctx), account_id)
    response.headers["X-Panel-Synced"] = "1" if await inquiry.refresh_from_panel(session, a) else "0"
    return (await _with_returns(session, StoreScope.of(ctx), [a]))[0]


@router.get("/{account_id}", response_model=VpnAccountOut)
async def get(account_id: uuid.UUID, ctx: StoreCtx, session: Session):
    scope = StoreScope.of(ctx)
    return (await _with_returns(session, scope, [await inquiry.customer_account(session, scope, account_id)]))[0]


@router.get("/{account_id}/qr.png", response_class=Response, responses={200: {"content": {"image/png": {}}}})
async def qr(account_id: uuid.UUID, ctx: StoreCtx, session: Session):
    """PNG QR code of the account's subscription link (same image the Telegram delivery post uses)."""
    a = await inquiry.customer_account(session, StoreScope.of(ctx), account_id)
    link = await live.current_link(session, a)  # R8: the panel's link, stored copy only as fallback
    if not link:
        raise NotFound("لینک اشتراک")
    return Response(render_qr_png(link), media_type="image/png", headers={"Cache-Control": "private, no-store"})
