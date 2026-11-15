"""Headline numbers for the Admin dashboard: successful sales per currency, orders by status, open tickets.

Owned by Reports so the Overview route only composes it (audit 4.3: no duplicate statistics queries in Overview).
"""

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from melorin.kernel.models.payments import Payment
from melorin.kernel.models.tickets import Ticket
from melorin.modules.orders import service as order_service


async def build_summary(session: AsyncSession) -> dict:
    """Only successful payments count as sales, grouped by currency."""
    rows = (
        await session.execute(
            select(Payment.currency, func.count(Payment.id), func.sum(Payment.amount))
            .where(Payment.status == "succeeded")
            .group_by(Payment.currency)
        )
    ).all()
    return {
        "payments": [{"currency": c, "count": n, "amount": total or 0} for c, n, total in rows],
        "orders": [{"status": k, "count": v} for k, v in (await order_service.count_by_status(session)).items()],
        "open_tickets": await session.scalar(select(func.count()).select_from(Ticket).where(Ticket.status == "open")) or 0,
        "currency_safe": True,
    }
