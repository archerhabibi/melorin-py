import uuid

from fastapi import APIRouter, Response
from sqlalchemy import select

from melorin.core.deps import CurrentUser, Session
from melorin.core.errors import NotFound
from melorin.modules.vpn.models import VpnAccount
from melorin.modules.vpn.schemas import VpnAccountOut

router = APIRouter(prefix="/vpn-accounts", tags=["vpn-accounts"])


def out(a: VpnAccount) -> VpnAccountOut:
    return VpnAccountOut(
        id=a.id,
        username=a.username,
        status=a.status,
        is_test=a.is_test,
        expires_at=a.expires_at,
        traffic_limit_bytes=a.traffic_limit_bytes,
        traffic_used_bytes=a.traffic_used_bytes,
        subscription_url=a.subscription_url,
        links=a.links,
        server_id=a.server_id,
        created_at=a.created_at,
        updated_at=a.updated_at,
    )


@router.get("", response_model=list[VpnAccountOut])
async def mine(user: CurrentUser, session: Session):
    return [
        out(a)
        for a in (
            await session.scalars(
                select(VpnAccount)
                .where(VpnAccount.user_id == user.id, VpnAccount.archived_at.is_(None))
                .order_by(VpnAccount.created_at.desc())
            )
        ).all()
    ]


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
