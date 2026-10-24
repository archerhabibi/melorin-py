"""Panel sync: compare one VPN account with what its panel reports and record any difference.

The order -> account workflow (retries, auto-refund) lives in :mod:`melorin.modules.orders.provisioning`."""

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from melorin.domain.order_state import VpnStatus
from melorin.kernel.models.vpn import Panel, ReconciliationIssue, VpnAccount
from melorin.modules.vpn.adapters.base import PanelError
from melorin.modules.vpn.adapters.registry import build_adapter_for


async def reconcile(session: AsyncSession, account_id: uuid.UUID) -> str:
    account = await session.get(VpnAccount, account_id)
    if not account or not account.panel_id:
        return "missing"
    panel = await session.get(Panel, account.panel_id)
    adapter = build_adapter_for(panel, account)
    try:
        remote = await adapter.get_account(account.username)
    except PanelError as e:
        session.add(ReconciliationIssue(vpn_account_id=account.id, kind="panel_unreachable", details={"error": e.message}))
        await session.commit()
        return "issue"
    if not remote:
        session.add(ReconciliationIssue(vpn_account_id=account.id, kind="missing_on_panel", details={"username": account.username}))
        await session.commit()
        return "issue"
    changed = False
    if account.status == VpnStatus.ACTIVE and remote.status == "disabled":
        account.status = VpnStatus.SUSPENDED
        changed = True
    account.traffic_used_bytes = remote.traffic_used_bytes
    account.subscription_url, account.links = remote.subscription_url, remote.links
    if remote.expire_at:
        account.expires_at = remote.expire_at
    await session.commit()
    return "updated" if changed else "ok"
