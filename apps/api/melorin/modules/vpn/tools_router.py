"""PG-10 account tools over HTTP: the same tools for the customer, the store owner and the platform admin.

One handler set, three scopes. The scope is resolved BEFORE the tool runs (customer: his own account in this store; owner: an
account of his store; admin: any account); a tool a role does not have is not even registered for it. Rules live in
:mod:`melorin.modules.vpn.account_tools`.
"""


import uuid
from dataclasses import dataclass
from typing import Annotated

from fastapi import APIRouter, Depends, Query

from melorin.core.deps import AdminUser, OwnerCtx, Session, StoreCtx
from melorin.core.errors import NotFound
from melorin.core.scope import StoreScope
from melorin.kernel.models.vpn import Panel, VpnAccount
from melorin.modules.vpn import account_tools as tools
from melorin.modules.vpn import inquiry
from melorin.modules.vpn.schemas import (
    AdjustIn,
    DevicesOut,
    PresenceOut,
    ReasonIn,
    ToolOut,
    UsageOut,
    VpnAccountOut,
)

router = APIRouter(tags=["vpn-account-tools"])


@dataclass(frozen=True)
class Target:
    account: VpnAccount
    actor_id: uuid.UUID
    role: str


async def _customer(account_id: uuid.UUID, ctx: StoreCtx, session: Session) -> Target:
    return Target(await inquiry.customer_account(session, StoreScope.of(ctx), account_id), ctx.user.id, tools.CUSTOMER)


async def _owner(account_id: uuid.UUID, ctx: OwnerCtx, session: Session) -> Target:
    account, _holder = await inquiry.reseller_find(session, ctx.user.id, ctx.store.id, account_id)
    return Target(account, ctx.user.id, tools.OWNER)


async def _admin(account_id: uuid.UUID, admin: AdminUser, session: Session) -> Target:
    account = await session.get(VpnAccount, account_id)
    if account is None:
        raise NotFound("اکانت VPN")
    return Target(account, admin.id, tools.ADMIN)


def _register(prefix: str, dep) -> None:
    T = Annotated[Target, Depends(dep)]  # noqa: N806
    base = f"{prefix}/{{account_id}}/tools"
    role_of = {tools.CUSTOMER: _customer, tools.OWNER: _owner, tools.ADMIN: _admin}
    role = next(r for r, d in role_of.items() if d is dep)

    @router.get(base, response_model=list[ToolOut], name=f"tools_{role}")
    async def matrix(t: T, session: Session):
        panel = await session.get(Panel, t.account.panel_id) if t.account.panel_id else None
        return tools.available(t.account, t.role, panel)

    @router.get(f"{base}/usage", response_model=UsageOut, name=f"usage_{role}")
    async def usage(
        t: T,
        session: Session,
        period: str = Query("day", pattern="^(hour|day)$"),
        days: int = Query(30, ge=1, le=tools.MAX_USAGE_DAYS),
    ):
        return await tools.usage(session, t.account, role=t.role, period=period, days=days)

    @router.get(f"{base}/devices", response_model=DevicesOut, name=f"devices_{role}")
    async def devices(t: T, session: Session):
        return await tools.devices(session, t.account, role=t.role)

    @router.delete(f"{base}/devices/{{hwid}}", status_code=204, name=f"device_delete_{role}")
    async def device_delete(hwid: str, t: T, session: Session):
        await tools.delete_device(session, t.account, role=t.role, actor_id=t.actor_id, hwid=hwid)

    @router.post(f"{base}/devices/reset", status_code=204, name=f"devices_reset_{role}")
    async def devices_reset(t: T, session: Session):
        await tools.reset_devices(session, t.account, role=t.role, actor_id=t.actor_id)

    @router.post(f"{base}/rotate-subscription", response_model=VpnAccountOut, name=f"rotate_{role}")
    async def rotate(t: T, session: Session):
        return inquiry.account_out(await tools.rotate_subscription(session, t.account, role=t.role, actor_id=t.actor_id))

    if role == tools.CUSTOMER:
        return

    @router.get(f"{base}/presence", response_model=PresenceOut, name=f"presence_{role}")
    async def presence(t: T, session: Session):
        panel = await session.get(Panel, t.account.panel_id) if t.account.panel_id else None
        return tools.presence(t.account, t.role, panel)

    @router.post(f"{base}/suspend", response_model=VpnAccountOut, name=f"suspend_{role}")
    async def suspend(body: ReasonIn, t: T, session: Session):
        return inquiry.account_out(await tools.suspend(session, t.account, role=t.role, actor_id=t.actor_id, reason=body.reason))

    @router.post(f"{base}/resume", response_model=VpnAccountOut, name=f"resume_{role}")
    async def resume(t: T, session: Session):
        return inquiry.account_out(await tools.resume(session, t.account, role=t.role, actor_id=t.actor_id))

    if role == tools.ADMIN:

        @router.post(f"{base}/adjust", response_model=VpnAccountOut, name=f"adjust_{role}")
        async def adjust(body: AdjustIn, t: T, session: Session):
            account = await tools.adjust(
                session, t.account, actor_id=t.actor_id, add_days=body.add_days, add_traffic_gb=body.add_traffic_gb, reason=body.reason
            )
            return inquiry.account_out(account)


_register("/stores/{store_id}/vpn-accounts", _customer)
_register("/stores/{store_id}/reseller/accounts", _owner)
_register("/admin/vpn-accounts", _admin)
