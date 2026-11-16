"""reports: analytics_queries (see ``analytics.py`` for the facade)."""

from __future__ import annotations

import datetime as dt
import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from melorin.domain.order_kinds import not_manual
from melorin.domain.panel_snapshot import snapshot_of
from melorin.kernel.models.catalog import Product
from melorin.kernel.models.identity import User
from melorin.kernel.models.orders import Order
from melorin.kernel.models.payments import Payment
from melorin.kernel.models.stores import Store
from melorin.kernel.models.tickets import Ticket
from melorin.kernel.models.vpn import Panel, VpnAccount
from melorin.modules.reports.analytics_compute import OrderRow, PayRow

MAX_ROWS = 200_000  # per table and per request; ``truncated`` tells the UI when a window was cut


async def _load(session: AsyncSession, since: dt.datetime, store_id: uuid.UUID | None):
    """Bounded row loads for [since, now]. The padding (1 day) keeps zone edges correct; the pure core filters exactly."""
    pad = since - dt.timedelta(days=1)
    q_o = (
        select(
            Order.created_at,
            Order.paid_at,
            Order.status,
            Order.total,
            Order.currency,
            Order.store_id,
            Order.product_id,
            Order.payment_method,
            Order.channel,
            Order.kind,
            Order.reseller_cost,
        )  # fmt: skip
        .where(((Order.created_at >= pad) | (Order.paid_at >= pad)), not_manual(Order.kind))
        .order_by(Order.created_at.desc())
        .limit(MAX_ROWS + 1)
    )
    sale_at = func.coalesce(Payment.reviewed_at, Payment.created_at)
    q_p = (
        select(
            Payment.created_at,
            Payment.reviewed_at,
            Payment.status,
            Payment.amount,
            Payment.currency,
            Payment.provider,
            Payment.purpose,
            Payment.store_id,
        )  # fmt: skip
        .where(sale_at >= pad)
        .order_by(Payment.created_at.desc())
        .limit(MAX_ROWS + 1)
    )
    q_u = select(User.created_at).where(User.created_at >= pad, User.is_guest.is_(False)).limit(MAX_ROWS + 1)
    if store_id:
        q_o, q_p = q_o.where(Order.store_id == store_id), q_p.where(Payment.store_id == store_id)
    o_rows = (await session.execute(q_o)).all()
    p_rows = (await session.execute(q_p)).all()
    u_rows = (await session.scalars(q_u)).all()
    truncated = max(len(o_rows), len(p_rows), len(u_rows)) > MAX_ROWS
    orders = [OrderRow(r[0], r[1], r[2], int(r[3] or 0), r[4], str(r[5]), str(r[6]), r[7], r[8], r[9], r[10]) for r in o_rows[:MAX_ROWS]]
    pays = [PayRow(r[0], r[1], r[2], int(r[3] or 0), r[4], r[5], r[6], str(r[7])) for r in p_rows[:MAX_ROWS]]
    return orders, pays, list(u_rows[:MAX_ROWS]), truncated


async def _panel_aggregates(session: AsyncSession) -> list[dict]:
    """Per enabled panel: the numbers the panel itself reported in its latest monitoring snapshot (never recomputed by Melorin)."""
    out: list[dict] = []
    for p in (await session.scalars(select(Panel).where(Panel.is_enabled.is_(True)).order_by(Panel.name))).all():
        snap = snapshot_of(p)
        out.append(
            {
                "panel_id": str(p.id),
                "name": p.name,
                "up": snap.up,
                "users_total": snap.users_total,
                "online_users": snap.online_users,
                "taken_at": snap.taken_at.isoformat() if snap.taken_at else None,
            }
        )
    return out


async def _snapshot(session: AsyncSession, now: dt.datetime) -> dict:
    """Point-in-time operational numbers (not period based): VPN fleet, tickets, users."""
    vpn_status: dict[str, int] = {
        r[0]: r[1] for r in (await session.execute(select(VpnAccount.status, func.count(VpnAccount.id)).group_by(VpnAccount.status))).all()
    }
    soon = now + dt.timedelta(days=7)
    expiring = (
        await session.scalar(
            select(func.count(VpnAccount.id)).where(
                VpnAccount.status == "active",
                VpnAccount.sold_expires_at.is_not(None),
                VpnAccount.sold_expires_at >= now,
                VpnAccount.sold_expires_at <= soon,
            )
        )
        or 0
    )
    sold = await session.scalar(select(func.coalesce(func.sum(VpnAccount.sold_traffic_bytes), 0)).where(VpnAccount.status == "active")) or 0
    panels = await _panel_aggregates(session)
    tickets: dict[str, int] = {
        r[0]: r[1] for r in (await session.execute(select(Ticket.status, func.count(Ticket.id)).group_by(Ticket.status))).all()
    }
    users_total = await session.scalar(select(func.count(User.id)).where(User.is_active.is_(True), User.is_guest.is_(False))) or 0
    return {
        "vpn": {
            "by_status": [{"status": k, "count": int(v)} for k, v in sorted(vpn_status.items(), key=lambda kv: -kv[1])],
            "active": int(vpn_status.get("active", 0)),
            "expiring_7d": int(expiring),
            # R5/R9: Melorin owns no usage. The volume sum is what was SOLD for active accounts; real usage and the user/online
            # counts are each panel's own (``panels`` below, from its monitoring snapshot, with the age of the reading).
            "traffic_used_bytes": None,
            "traffic_limit_bytes": int(sold),
            "traffic_source": "sold",
            "traffic_as_of": None,
            "panels": panels,  # what each PANEL reports about itself (its own users / online counts), with the reading's age
        },
        "tickets": {"by_status": [{"status": k, "count": int(v)} for k, v in tickets.items()], "open": int(tickets.get("open", 0))},
        "users_total": int(users_total),
    }


async def _names(session: AsyncSession, payload: dict) -> None:
    pids = {uuid.UUID(r["product_id"]) for r in payload["top_products"]}
    sids = {uuid.UUID(r["store_id"]) for r in payload["top_stores"]}
    products = {p.id: p.name for p in (await session.scalars(select(Product).where(Product.id.in_(pids)))).all()} if pids else {}
    stores = {s.id: s for s in (await session.scalars(select(Store).where(Store.id.in_(sids)))).all()} if sids else {}
    for r in payload["top_products"]:
        r["name"] = products.get(uuid.UUID(r["product_id"])) or "محصول حذف‌شده"
    for r in payload["top_stores"]:
        s = stores.get(uuid.UUID(r["store_id"]))
        r["name"], r["kind"] = (s.name, s.kind) if s else ("فروشگاه حذف‌شده", "unknown")
