"""Customer account return (مرجوعی), executing half: the rules live in ``melorin.modules.vpn.returns`` (the lower layer);
this module, which may import ``orders``, turns an allowed return into a normal order refund."""

from __future__ import annotations

import uuid

from melorin.core.scope import StoreScope
from melorin.modules.orders.service.refund import _refund
from melorin.modules.vpn import returns


async def return_account(session, scope: StoreScope, account_id: uuid.UUID) -> dict:
    """Return the customer's own account of THIS store; raises a 409 ``AppError`` with Core's words when it is not allowed."""
    _account, order = await returns.prepare_return(session, scope, account_id)
    await _refund(session, order.id, actor_id=scope.user_id, actor_type="customer", reason="مرجوعی اکانت توسط مشتری")  # commits
    return {
        "ok": True,
        "order_id": order.id,
        "refunded": int(order.total),
        "currency": order.currency,
        "message": "اکانت مرجوع شد و مبلغ آن به کیف پول شما برگشت داده شد.",
    }
