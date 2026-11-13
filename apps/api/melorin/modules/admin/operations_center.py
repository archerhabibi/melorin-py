"""Operations Center: ONE read-only roll-up of everything that waits for an admin.

It is an aggregate, not an engine: every queue is counted from the table its owning module writes, and every item names the
screen (``section`` slug) where the owner resolves it. No remediation logic lives here.
"""

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from melorin.domain.order_state import OrderStatus
from melorin.kernel.models.identity import IdentityLinkReview
from melorin.kernel.models.orders import Order
from melorin.kernel.models.payments import Payment
from melorin.kernel.models.stores import ResellerApplication
from melorin.kernel.models.tickets import Ticket
from melorin.kernel.models.vpn import BulkOperation, PanelEvent, PanelOrphan, ReconciliationIssue

# queue key -> (domain group, admin section slug that owns the remedy)
QUEUES: dict[str, tuple[str, str]] = {
    "provisioning_failures": ("panel", "orders"),
    "account_discrepancies": ("panel", "vpn"),
    "panel_orphans": ("panel", "vpn"),
    "failed_panel_events": ("panel", "panel-ops"),
    "failed_bulk_operations": ("panel", "bulk-operations"),
    "receipt_reviews": ("finance", "payments"),
    "refunds_pending": ("finance", "orders"),
    "identity_conflicts": ("identity", "identity"),
    "reseller_applications": ("stores", "reseller-applications"),
    "open_tickets": ("support", "tickets"),
}


async def _count(session: AsyncSession, column, *where) -> int:
    return int(await session.scalar(select(func.count(column)).where(*where)) or 0)


async def attention(session: AsyncSession) -> dict:
    """``{"total": n, "items": [{key, group, section, count}]}``; zero-count queues are kept so the screen layout is stable."""
    counts = {
        "provisioning_failures": await _count(
            session, Order.id, Order.status.in_((OrderStatus.PROVISIONING_FAILED.value, OrderStatus.MANUAL_REVIEW.value))
        ),
        "account_discrepancies": await _count(session, ReconciliationIssue.id, ReconciliationIssue.status == "open"),
        "panel_orphans": await _count(session, PanelOrphan.id, PanelOrphan.status == "open"),
        "failed_panel_events": await _count(session, PanelEvent.id, PanelEvent.status == "failed"),
        "failed_bulk_operations": await _count(session, BulkOperation.id, BulkOperation.status.in_(("failed", "partial"))),
        "receipt_reviews": await _count(session, Payment.id, Payment.status == "awaiting_review"),
        "refunds_pending": await _count(session, Order.id, Order.status == OrderStatus.REFUND_PENDING.value),
        "identity_conflicts": await _count(session, IdentityLinkReview.id, IdentityLinkReview.status == "open"),
        "reseller_applications": await _count(
            session, ResellerApplication.id, ResellerApplication.status.in_(("pending", "awaiting_details"))
        ),
        "open_tickets": await _count(session, Ticket.id, Ticket.status == "open"),
    }
    items = [{"key": key, "group": QUEUES[key][0], "section": QUEUES[key][1], "count": counts[key]} for key in QUEUES]
    return {"total": sum(counts.values()), "items": items}
