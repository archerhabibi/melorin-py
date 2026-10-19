import uuid

from fastapi import APIRouter, Query, Response
from sqlalchemy import func, select

from melorin.core.deps import CurrentUser, Session
from melorin.core.errors import NotFound
from melorin.modules.vpn import inquiry
from melorin.modules.vpn.models import VpnAccount
from melorin.modules.vpn.schemas import VpnAccountOut

router = APIRouter(prefix="/vpn-accounts", tags=["vpn-accounts"])


out = inquiry.account_out


@router.get("", response_model=list[VpnAccountOut])
async def mine(
    user: CurrentUser,
    session: Session,
    response: Response,
    q: str | None = Query(None, max_length=200, description="search in the account name"),
    store_id: uuid.UUID | None = Query(None, description="only accounts bought in this store"),
    limit: int = Query(100, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    """Always the caller's OWN accounts: ``user_id`` is part of every query, whatever the filters are."""
    cond = [VpnAccount.user_id == user.id, VpnAccount.archived_at.is_(None)]
    if store_id:
        cond.append(VpnAccount.store_id == store_id)
    if term := inquiry.clean_query(q):
        cond.append(inquiry.username_clause(term))
    total = await session.scalar(select(func.count()).select_from(VpnAccount).where(*cond))
    response.headers["X-Total-Count"] = str(total or 0)
    rows = await session.scalars(select(VpnAccount).where(*cond).order_by(VpnAccount.created_at.desc()).limit(limit).offset(offset))
    return [out(a) for a in rows.all()]


@router.get("/{account_id}", response_model=VpnAccountOut)
async def get(account_id: uuid.UUID, user: CurrentUser, session: Session):
    a = await session.get(VpnAccount, account_id)
    if not a or (a.user_id != user.id and not user.is_super_admin):
        raise NotFound("اکانت VPN")
    return out(a)


@router.get("/{account_id}/qr.png", response_class=Response, responses={200: {"content": {"image/png": {}}}})
async def qr(account_id: uuid.UUID, user: CurrentUser, session: Session):
    """PNG QR code of the account's subscription link (same image the Telegram delivery post uses)."""
    a = await session.get(VpnAccount, account_id)
    if not a or (a.user_id != user.id and not user.is_super_admin):
        raise NotFound("اکانت VPN")
    link = a.subscription_url or (a.links[0] if isinstance(a.links, list) and a.links else None)
    if not link:
        raise NotFound("لینک اشتراک")
    from melorin.modules.orders.delivery import render_qr_png  # lazy: avoids a vpn <-> orders import cycle

    return Response(render_qr_png(link), media_type="image/png", headers={"Cache-Control": "private, no-store"})
