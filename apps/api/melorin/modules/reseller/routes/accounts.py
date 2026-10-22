"""The reseller's VPN-account inquiry, live refresh, renewal and QR; Core owns every rule (see ``vpn.inquiry``)."""

import uuid

from fastapi import APIRouter, Header, Query, Response
from pydantic import BaseModel, Field

from melorin.core.deps import OwnerCtx, Session
from melorin.core.errors import NotFound
from melorin.modules.reseller import renewal as reseller_renewal
from melorin.modules.reseller.schemas import OwnerRenewalOut
from melorin.modules.vpn import inquiry
from melorin.modules.vpn.schemas import OwnerAccountOut

router = APIRouter(tags=["reseller"])


@router.get("/stores/{store_id}/reseller/accounts", response_model=list[OwnerAccountOut])
async def store_accounts(
    ctx: OwnerCtx,
    session: Session,
    response: Response,
    q: str | None = Query(None, max_length=200, description="account name, customer name or e-mail"),
    state: str | None = Query(None, pattern="^(active|expiring|expired)$", description="filter chip"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    """The reseller's inquiry: the LIST is only his own accounts, a SEARCH also finds his own customers' (``inquiry``)."""
    rows, total = await inquiry.reseller_accounts(session, ctx.user.id, ctx.store.id, q=q, state=state, limit=limit, offset=offset)
    response.headers["X-Total-Count"] = str(total)
    return [inquiry.owner_account_out(a, u, owner_id=ctx.user.id) for a, u in rows]


@router.get("/stores/{store_id}/reseller/accounts/summary")
async def store_accounts_summary(ctx: OwnerCtx, session: Session):
    """Chip counters over the list scope (the reseller's OWN accounts) + Core's note explaining that scope."""
    return await inquiry.reseller_summary(session, ctx.user.id, ctx.store.id)


async def _store_account(session, ctx, account_id: uuid.UUID):
    return await inquiry.reseller_find(session, ctx.user.id, ctx.store.id, account_id)


@router.get("/stores/{store_id}/reseller/accounts/{account_id}", response_model=OwnerAccountOut)
async def store_account(account_id: uuid.UUID, ctx: OwnerCtx, session: Session):
    a, u = await _store_account(session, ctx, account_id)
    return inquiry.owner_account_out(a, u, owner_id=ctx.user.id)


@router.post("/stores/{store_id}/reseller/accounts/{account_id}/refresh", response_model=OwnerAccountOut)
async def store_account_refresh(account_id: uuid.UUID, ctx: OwnerCtx, session: Session, response: Response):
    """Owner's live view: re-read one of the store's accounts from its VPN panel."""
    a, u = await _store_account(session, ctx, account_id)
    response.headers["X-Panel-Synced"] = "1" if await inquiry.refresh_from_panel(session, a) else "0"
    return inquiry.owner_account_out(a, u, owner_id=ctx.user.id)


@router.get("/stores/{store_id}/reseller/accounts/{account_id}/renewal", response_model=OwnerRenewalOut)
async def store_account_renewal(account_id: uuid.UUID, ctx: OwnerCtx, session: Session):
    """What a renewal of this account would be (package, price, new expiry, who pays): Core's answer, shown as is."""
    return await reseller_renewal.reseller_renewal_offer(session, ctx.user.id, ctx.store.id, account_id)


class OwnerRenewIn(BaseModel):
    channel: str = Field(default="web", pattern="^(web|telegram)$")


@router.post("/stores/{store_id}/reseller/accounts/{account_id}/renew", status_code=201)
async def store_account_renew(
    account_id: uuid.UUID,
    body: OwnerRenewIn,
    ctx: OwnerCtx,
    session: Session,
    idempotency_key: str = Header(..., alias="Idempotency-Key", min_length=8, max_length=100),
):
    """Renew the reseller's own account or one of his own customers' accounts (everything else: 404); see ``inquiry``."""
    from melorin.modules.orders.router import out as order_out  # lazy: orders imports the vpn package

    order = await reseller_renewal.reseller_renew(
        session, ctx.user.id, ctx.store.id, account_id, idempotency_key=idempotency_key, channel=body.channel
    )
    return order_out(order)


@router.get(
    "/stores/{store_id}/reseller/accounts/{account_id}/qr.png", response_class=Response, responses={200: {"content": {"image/png": {}}}}
)
async def store_account_qr(account_id: uuid.UUID, ctx: OwnerCtx, session: Session):
    a, _ = await _store_account(session, ctx, account_id)
    link = a.subscription_url or (a.links[0] if isinstance(a.links, list) and a.links else None)
    if not link:
        raise NotFound("لینک اشتراک")
    from melorin.modules.orders.delivery import render_qr_png  # lazy: avoids a vpn <-> orders import cycle

    return Response(render_qr_png(link), media_type="image/png", headers={"Cache-Control": "private, no-store"})
