"""ARQ + Redis worker entrypoint.

The DB outbox remains the source of truth. ARQ provides distributed scheduling,
retry isolation and horizontal workers; each claimed outbox/delivery row remains
idempotent, so a crash is safe.
"""

import asyncio
import time

from arq import cron
from arq.connections import RedisSettings

from melorin.core.config import get_settings
from melorin.core.db import session_factory
from melorin.worker.runner import claim_batch, claim_webhook_batch, process_event, process_webhook
from melorin.worker.jobs import (
    backup_job,
    bank_sms_reconcile_job,
    receipt_grace_job,
    daily_report_job,
    expiry_job,
    near_expiry_job,
    panel_health_job,
    privacy_retention_job,
    reconciliation_job,
    telegram_login_gc_job,
    identity_auto_link_job,
    reseller_auto_verify_job,
    reseller_identity_recheck_job,
)
from melorin.core.metrics import set_gauge


async def poll_tick(ctx):
    async with session_factory()() as session:
        events = await claim_batch(session)
        deliveries = await claim_webhook_batch(session)
    if events or deliveries:
        await asyncio.gather(*(process_event(e) for e in events), *(process_webhook(d) for d in deliveries))
    await ctx["redis"].set("melorin:worker:last_tick", str(time.time()), ex=15)
    set_gauge("melorin_worker_last_tick", __import__("time").time())
    return {"events": len(events), "deliveries": len(deliveries)}


async def startup(ctx):
    # Polling is scheduled by ARQ cron below. Do not enqueue a chained job
    # from inside the running job: a fixed job id can stall the chain.
    return None


async def shutdown(ctx):
    pass


class WorkerSettings:
    functions = [
        poll_tick,
        backup_job,
        daily_report_job,
        panel_health_job,
        expiry_job,
        near_expiry_job,
        reconciliation_job,
        privacy_retention_job,
        bank_sms_reconcile_job,
        receipt_grace_job,
        identity_auto_link_job,
        reseller_auto_verify_job,
        reseller_identity_recheck_job,
        telegram_login_gc_job,
    ]
    cron_jobs = [
        cron(poll_tick, second=set(range(0, 60, 2)), unique=True),
        cron(backup_job, hour=2, minute=0, unique=True, timeout=900),
        # 20:30 UTC = 00:00 Tehran: the nightly Event Center report of the day that just ended.
        cron(daily_report_job, hour=20, minute=30, unique=True),
        cron(panel_health_job, minute=set(range(0, 60, 5)), unique=True),
        cron(expiry_job, minute=set(range(0, 60, 5)), unique=True),
        cron(near_expiry_job, minute=set(range(0, 60, 15)), unique=True),
        cron(reconciliation_job, minute=10, unique=True),
        cron(privacy_retention_job, hour=3, minute=0, unique=True),
        cron(telegram_login_gc_job, minute=set(range(5, 60, 30)), unique=True),
        cron(identity_auto_link_job, minute=set(range(2, 60, 10)), unique=True),
        cron(reseller_auto_verify_job, minute=set(range(0, 60, 2)), unique=True),
        cron(reseller_identity_recheck_job, minute=set(range(7, 60, 30)), unique=True),
        cron(bank_sms_reconcile_job, second={30}, unique=True),
        cron(receipt_grace_job, second={10}, unique=True),
    ]
    on_startup = startup
    on_shutdown = shutdown
    redis_settings = RedisSettings.from_dsn(get_settings().redis_url or "redis://localhost:6379/0")
    max_jobs = 20
    # Keep the default short for ordinary jobs; backup_job has its own
    # 15-minute cron timeout above.
    job_timeout = 120
    max_tries = 1
