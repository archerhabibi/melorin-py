"""Order refunds (admin-initiated and automatic after a provisioning failure)."""

import uuid
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from melorin.core import audit, events
from melorin.core.errors import AppError
from melorin.domain.order_state import REFUNDABLE, VpnStatus
from melorin.modules.catalog import service as catalog
from melorin.kernel.models.identity import User
from melorin.kernel.models.orders import Order
from melorin.kernel.models.vpn import VpnAccount
from melorin.modules.wallet import service as wallet
from melorin.modules.orders.service.base import S, transition


async def _refund(
    session: AsyncSession,
    order_id: uuid.UUID,
    *,
    actor_id,  # None for system-triggered refunds
    actor_type: str,  # "admin" | "system"
    reason: str | None,
) -> None:
    """Internal single-writer compensating ledger reversal. Idempotent on repeated calls."""
    order = await session.get(Order, order_id, with_for_update=True, populate_existing=True)
    if not order:
        return
    if order.status == S.REFUNDED:
        return
    if order.status not in REFUNDABLE:
        raise AppError("INVALID_ORDER_STATE", "این سفارش قابل استرداد نیست.", 409)
    await transition(session, order, S.REFUND_PENDING, reason=reason, actor_id=actor_id)
    tx = await wallet.find_tx(session, f"order:{order.id}:payment")
    if tx:
        await wallet.reverse(
            session,
            tx,
            key=f"order:{order.id}:refund",
            kind="refund",
            actor_id=actor_id,
            memo=f"استرداد سفارش {order.number}",
        )
    cost_tx = await wallet.find_tx(session, f"order:{order.id}:reseller_cost")
    if cost_tx:
        await wallet.reverse(
            session,
            cost_tx,
            key=f"order:{order.id}:reseller_cost_refund",
            kind="reseller_cost_refund",
            actor_id=actor_id,
            memo=f"برگشت هزینه نمایندگی {order.number}",
        )
    await catalog.release_redemption(session, order.id)
    await transition(session, order, S.REFUNDED, reason=reason, actor_id=actor_id)
    acc = (
        await session.get(VpnAccount, order.vpn_account_id)
        if order.vpn_account_id
        else await session.scalar(select(VpnAccount).where(VpnAccount.order_id == order.id))
    )
    if acc and acc.status not in (VpnStatus.REVOKED, VpnStatus.ARCHIVED):
        if order.kind == "renewal" and (order.pricing_snapshot or {}).get("renewal_before"):
            await events.emit(
                session,
                events.VPN_RENEWAL_ROLLBACK,
                {"vpn_account_id": acc.id, "before": order.pricing_snapshot["renewal_before"]},
                dedup_key=f"renewal_rollback:{order.id}",
            )
        else:
            await events.emit(session, events.VPN_REVOKE, {"vpn_account_id": acc.id})
    await events.emit(
        session,
        events.ORDER_REFUNDED,
        {"order_id": order.id, "store_id": order.store_id},
        dedup_key=f"order_refunded:{order.id}",
    )
    refund_body = (
        f"ساخت اکانت سفارش {order.number} ناموفق بود و مبلغ آن به کیف پول شما برگشت داده شد."
        if actor_type == "system"
        else f"مبلغ سفارش {order.number} به کیف پول شما برگشت داده شد."
    )
    await events.emit(
        session,
        events.NOTIFY,
        {"user_id": order.user_id, "store_id": order.store_id, "kind": "refund", "title": "استرداد سفارش", "body": refund_body},
    )
    audit.record(
        session,
        "order.refunded",
        actor_id=actor_id,
        actor_type=actor_type,
        entity_type="order",
        entity_id=order.id,
        store_id=order.store_id,
        data={"reason": reason, "total": order.total},
    )
    await session.commit()


async def refund(session: AsyncSession, order: Order, admin: User, reason: str | None) -> None:
    """Admin-triggered refund. Delegates to _refund() with the admin as actor."""
    await _refund(session, order.id, actor_id=admin.id, actor_type="admin", reason=reason)


async def auto_refund(session: AsyncSession, order_id: uuid.UUID, *, reason: str | None) -> None:
    """System-triggered refund after all provisioning retries are exhausted.

    No admin action is required; the system is the actor. Admin notification
    is emitted before this call (by orders.provisioning._give_up) via PROVISIONING_FAILED.
    """
    await _refund(session, order_id, actor_id=None, actor_type="system", reason=reason)
