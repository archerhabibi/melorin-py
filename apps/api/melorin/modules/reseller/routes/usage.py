"""The store owner's usage report: how much the store's customers used, read live from the panel (read-only)."""

from fastapi import APIRouter

from melorin.core.deps import OwnerCtx, Session
from melorin.modules.panelops import store_usage

router = APIRouter(tags=["reseller"])


@router.get("/stores/{store_id}/reseller/usage-report")
async def usage_report(ctx: OwnerCtx, session: Session):
    """Accounts by state, total volume used, the 5 heaviest accounts, and how many are near expiry / near exhaustion.

    Every number is read from the panel now; a panel that cannot answer shows no number (``live=false`` and a note), never an
    old one. No IP address, connection detail or subscription link is part of the answer. Only this store's own panel admin
    is read, so a store can never see another store's accounts."""
    return await store_usage.report(session, ctx.store)
