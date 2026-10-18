"""M7.6: business-level metrics derived from the database at scrape time.

The API and the ARQ worker are separate processes and Prometheus scrapes only the API, so in-process counters
cannot see provisioning or payment outcomes that happen in the worker. These gauges are computed from the source
of truth (PostgreSQL) on every ``/metrics`` scrape instead, which also keeps them correct across restarts.
"""

from __future__ import annotations

import datetime as dt

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from melorin.core.metrics import set_alert, set_gauge
from melorin.modules.orders.models import Order
from melorin.modules.payments.models import Payment
from melorin.modules.reseller.bots import effective_state
from melorin.modules.stores.models import Store
from melorin.modules.system.models import BackupRun

WINDOW = dt.timedelta(minutes=15)
PROVISIONING_WINDOW = dt.timedelta(hours=1)
PAYMENT_FAILURE_RATIO = 0.5  # more than half of the recent payment attempts failed
PAYMENT_MIN_SAMPLE = 5  # ... and there were enough of them to mean something
BACKUP_MAX_AGE = dt.timedelta(hours=36)
UNHEALTHY_BOT_STATES = frozenset({"error", "offline"})


async def collect(session: AsyncSession, now: dt.datetime | None = None) -> dict[str, float]:
    """Refresh the business gauges + alerts and return the values (handy for tests)."""
    now = now or dt.datetime.now(dt.UTC)
    values: dict[str, float] = {}

    since = now - WINDOW
    rows = (await session.execute(select(Payment.status, func.count()).where(Payment.created_at >= since).group_by(Payment.status))).all()
    by_status = {status: count for status, count in rows}
    total = sum(by_status.values())
    failed = by_status.get("failed", 0)
    values["melorin_payments_recent_total"] = float(total)
    values["melorin_payments_recent_failed"] = float(failed)
    values["melorin_payments_recent_failure_ratio"] = failed / total if total else 0.0

    prov_since = now - PROVISIONING_WINDOW
    prov_failed = (
        await session.scalar(
            select(func.count()).select_from(Order).where(Order.status == "provisioning_failed", Order.updated_at >= prov_since)
        )
        or 0
    )
    needs_review = await session.scalar(select(func.count()).select_from(Order).where(Order.needs_review.is_(True))) or 0
    values["melorin_orders_provisioning_failed_recent"] = float(prov_failed)
    values["melorin_orders_needs_review"] = float(needs_review)

    stores = (await session.scalars(select(Store).where(Store.kind == "reseller"))).all()
    unhealthy_bots = sum(1 for st in stores if effective_state(st, now) in UNHEALTHY_BOT_STATES)
    values["melorin_reseller_bots_unhealthy"] = float(unhealthy_bots)

    last_ok = await session.scalar(select(func.max(BackupRun.created_at)).where(BackupRun.status == "succeeded"))
    if last_ok is None:
        age = float("inf")
    else:
        last_ok = last_ok if last_ok.tzinfo else last_ok.replace(tzinfo=dt.UTC)
        age = max((now - last_ok).total_seconds(), 0.0)
    # +Inf is a valid Prometheus sample, but a huge finite number is friendlier to dashboards.
    values["melorin_backup_age_seconds"] = age if age != float("inf") else 10**9

    for name, value in values.items():
        set_gauge(name, value)

    set_alert(
        "MelorinPaymentFailureRateHigh",
        total >= PAYMENT_MIN_SAMPLE and values["melorin_payments_recent_failure_ratio"] > PAYMENT_FAILURE_RATIO,
        summary="Most recent payments are failing",
        severity="critical",
        details=f"{failed}/{total}",
    )
    set_alert(
        "MelorinProvisioningFailures",
        prov_failed > 0,
        summary="Orders failed to provision in the last hour",
        severity="critical",
        details=str(prov_failed),
    )
    set_alert(
        "MelorinResellerBotUnhealthy",
        unhealthy_bots > 0,
        summary="One or more reseller Telegram bots are offline or in error",
        severity="warning",
        details=str(unhealthy_bots),
    )
    set_alert(
        "MelorinBackupStale",
        values["melorin_backup_age_seconds"] > BACKUP_MAX_AGE.total_seconds(),
        summary="No successful backup within 36 hours",
        severity="critical",
        details="never" if last_ok is None else f"{int(age)}s",
    )
    return values
