"""Panel sync entry points. The comparison itself lives in :mod:`melorin.modules.vpn.reconcile` (PG-04, reconcile v2).

The order -> account workflow (retries, auto-refund) lives in :mod:`melorin.modules.orders.provisioning`."""

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from melorin.modules.vpn import reconcile as _reconcile


async def reconcile(session: AsyncSession, account_id: uuid.UUID) -> str:
    """Compare ONE account with its panel and record any difference (kept for callers that need a single account)."""
    return await _reconcile.reconcile_account(session, account_id)
