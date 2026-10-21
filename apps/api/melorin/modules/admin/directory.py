"""Admin API - directory routes (split from the former 1,900-line router; paths unchanged)."""

import logging
import uuid
from fastapi import APIRouter, Query
from fastapi.responses import Response
from sqlalchemy import select
from melorin.core.deps import AdminUser, Session
from melorin.core.errors import NotFound
from melorin.kernel.models.identity import User
from melorin.kernel.models.stores import Store
from melorin.modules.catalog import allocation
from melorin.modules.vpn import inquiry

router = APIRouter(prefix="/admin", tags=["admin"])
log = logging.getLogger("melorin.admin")


@router.get("/users", response_model=list[dict])
async def users(_: AdminUser, session: Session):
    rows = (await session.scalars(select(User).order_by(User.created_at.desc()).limit(500))).all()
    return [
        {
            "id": u.id,
            "email": u.email,
            "display_name": u.display_name,
            "is_active": u.is_active,
            "is_super_admin": u.is_super_admin,
            "created_at": u.created_at,
        }
        for u in rows
    ]


@router.get("/stores/{store_id}/reseller-prices")
async def reseller_store_prices(store_id: uuid.UUID, _: AdminUser, session: Session):
    """READ-ONLY: the retail prices a reseller store charges. Only the reseller sets them (reseller panel / bot)."""
    st = await session.get(Store, store_id)
    if not st or st.kind != "reseller":
        raise NotFound("فروشگاه نماینده")
    return await allocation.reseller_price_table(session, st)


@router.get("/stores", response_model=list[dict])
async def stores(_: AdminUser, session: Session):
    rows = (await session.scalars(select(Store).order_by(Store.created_at.desc()).limit(500))).all()
    return [
        {
            "id": s.id,
            "name": s.name,
            "slug": s.slug,
            "kind": s.kind,
            "status": s.status,
            "currency": s.currency,
            "owner_user_id": s.owner_user_id,
            "domain": s.domain,
            "parent_store_id": s.parent_store_id,
            "bot_username": s.bot_username,
        }
        for s in rows
    ]


@router.get("/vpn-accounts", response_model=list[dict])
async def vpn_accounts(
    _: AdminUser,
    session: Session,
    response: Response,
    q: str | None = Query(None, max_length=200, description="account name, customer name or e-mail"),
    store_id: uuid.UUID | None = Query(None),
    state: str | None = Query(None, pattern="^(active|expiring|expired)$"),
    limit: int = Query(100, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    """The platform owner's inquiry: every account of every store, searchable and paged (``inquiry.admin_accounts``)."""
    rows, total = await inquiry.admin_accounts(session, q=q, store_id=store_id, state=state, limit=limit, offset=offset)
    response.headers["X-Total-Count"] = str(total)
    return [
        {
            "id": a.id,
            "user_id": a.user_id,
            "customer_name": u.display_name or u.email,
            "store_id": a.store_id,
            "username": a.username,
            "status": a.status,
            "health": inquiry.health(a),
            "days_left": inquiry.days_left(a),
            "expires_at": a.expires_at,
            "traffic_limit_bytes": a.traffic_limit_bytes,
            "traffic_used_bytes": a.traffic_used_bytes,
        }
        for a, u in rows
    ]
