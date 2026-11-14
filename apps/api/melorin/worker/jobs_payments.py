"""Payment jobs: bank-SMS reconcile and receipt grace."""

import functools
import logging

from sqlalchemy import select

from melorin.core.db import session_factory
from melorin.modules.panel_integrations.adapters.lifecycle import close_adapter
from melorin.worker.wrap import item_failed, tracked_job

_close_strict = functools.partial(close_adapter, strict=True)  # worker jobs keep raising on close failure
log = logging.getLogger("melorin.jobs")


@tracked_job
async def bank_sms_reconcile_job(ctx=None):
    """Safety net for card-to-card auto verification: pair open deposit SMS with receipts uploaded later or whose
    inline match failed. Idempotent; the wallet credit is protected by the ledger idempotency key."""
    from melorin.kernel.models.payments import BankSmsSource
    from melorin.kernel.models.stores import Store
    from melorin.modules.payments import bank_sms

    total = 0
    async with session_factory()() as s:
        ids = (
            await s.scalars(select(BankSmsSource.store_id).where(BankSmsSource.is_enabled.is_(True), BankSmsSource.auto_verify.is_(True)))
        ).all()
        for store_id in ids:
            try:
                store = await s.get(Store, store_id)
                if store:
                    total += (await bank_sms.reconcile_store(s, store))["matched"]
            except Exception:
                await s.rollback()
                item_failed("bank_sms_reconcile_job")
                log.warning("bank sms reconcile failed store=%s", store_id, exc_info=True)
    return total


@tracked_job
async def receipt_grace_job(ctx=None):
    """Time-boxed manual review: credit provisionally (and flag for fast review) every card-to-card receipt that
    waited longer than the store's grace minutes. Runs every minute; idempotent."""
    from melorin.modules.payments import provisional

    async with session_factory()() as s:
        try:
            n = await provisional.sweep(s)
        except Exception:
            await s.rollback()
            item_failed("receipt_grace_job")
            log.warning("receipt grace sweep failed", exc_info=True)
            return 0
        if n:
            log.info("receipt grace: provisional credits=%s", n)
        return n
