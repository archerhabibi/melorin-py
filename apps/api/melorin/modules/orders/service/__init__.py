"""Order lifecycle service. Public names are re-exported here so `from melorin.modules.orders import service` keeps working."""

from melorin.modules.orders.service.base import S, transition, ResellerDebtLimitReached, count_by_status
from melorin.modules.orders.service.create import create_order, create_test_order
from melorin.modules.orders.service.payment import pay_with_wallet, notify_debt_reached
from melorin.modules.orders.service.admin_actions import cancel, admin_retry, admin_mark_review
from melorin.modules.orders.service.refund import _refund, refund, auto_refund

__all__ = [
    "S",
    "transition",
    "ResellerDebtLimitReached",
    "create_order",
    "pay_with_wallet",
    "notify_debt_reached",
    "create_test_order",
    "cancel",
    "admin_retry",
    "admin_mark_review",
    "_refund",
    "refund",
    "auto_refund",
    "count_by_status",
]
