"""Data retention for the append-only operational tables that otherwise grow forever (audit T51).

Only *finished* rows go: an outbox event that was processed, a webhook delivery that was delivered or finally failed.
Anything still pending/processing/delivering is never touched, and financial/audit tables (orders, ledger, audit log)
are out of scope on purpose. Panel events have their own purge (``vpn.panel_events.purge``).
"""

from __future__ import annotations

import datetime as dt
from typing import Any, cast

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from melorin.core import settings_store
from melorin.core.db import utcnow
from melorin.kernel.models.system import OutboxEvent
from melorin.kernel.models.webhooks import WebhookDelivery

OUTBOX_DONE = ("processed",)
WEBHOOK_DONE = ("delivered", "failed")


async def _days(session: AsyncSession, key: str) -> int:
    try:
        return max(1, int(cast(Any, await settings_store.get(session, key))))
    except (TypeError, ValueError):
        return int(cast(Any, settings_store.DEFAULTS[key]))  # a mistyped admin value must not disable or break the purge


async def purge_finished(session: AsyncSession, *, now: dt.datetime | None = None) -> dict[str, int]:
    """Delete finished outbox events and webhook deliveries past their retention window; returns rows removed per table."""
    now = now or utcnow()
    outbox_cutoff = now - dt.timedelta(days=await _days(session, "privacy.outbox_retention_days"))
    webhook_cutoff = now - dt.timedelta(days=await _days(session, "privacy.webhook_delivery_retention_days"))
    outbox = await session.execute(
        delete(OutboxEvent).where(
            OutboxEvent.status.in_(OUTBOX_DONE),
            OutboxEvent.processed_at.is_not(None),
            OutboxEvent.processed_at < outbox_cutoff,
        )
    )
    webhooks = await session.execute(
        delete(WebhookDelivery).where(WebhookDelivery.status.in_(WEBHOOK_DONE), WebhookDelivery.updated_at < webhook_cutoff)
    )
    await session.commit()
    return {"outbox_events": int(outbox.rowcount or 0), "webhook_deliveries": int(webhooks.rowcount or 0)}
