"""Identity and privacy jobs: auto-link, reseller verification, Telegram login GC, retention."""

import functools
import datetime as dt
import logging
from typing import Any, cast

from sqlalchemy import delete
from sqlalchemy.engine import CursorResult

from melorin.core import settings_store
from melorin.core.db import session_factory, utcnow
from melorin.kernel.models.identity import VerificationCode
from melorin.modules.panel_integrations.adapters.lifecycle import close_adapter
from melorin.worker import retention
from melorin.worker.wrap import tracked_job

_close_strict = functools.partial(close_adapter, strict=True)  # worker jobs keep raising on close failure
log = logging.getLogger("melorin.jobs")




@tracked_job
async def identity_auto_link_job(ctx=None):
    """Safety net for identity-link conflicts (docs/23): settle every open review that became safe to merge by itself
    (an empty shell stayed empty). Two accounts that both hold records are left for an admin."""
    from melorin.modules.identity import auto_link

    async with session_factory()() as s:
        settled = await auto_link.sweep(s)
        if settled:
            log.info("identity conflicts settled automatically=%s", settled)
        return settled



@tracked_job
async def reseller_auto_verify_job(ctx=None):
    """Reseller applications verify themselves (docs/23): re-check the bot and the domain proof of every pending
    application whose retry is due. Back-off lives on the row, so a restart or a second worker never double-runs it."""
    from melorin.modules.reseller import auto_verify

    async with session_factory()() as s:
        done = await auto_verify.sweep(s)
        if done:
            log.info("reseller applications auto-verified rounds=%s", done)
        return done



@tracked_job
async def reseller_identity_recheck_job(ctx=None):
    """Approved resellers keep proving who they are (docs/23): re-check domain proof and bot token of every store whose
    check is due; repeated failure alerts admins (and suspends the store when RESELLER_RECHECK_SUSPEND is on)."""
    from melorin.modules.reseller import recheck

    async with session_factory()() as s:
        done = await recheck.sweep(s)
        if done:
            log.info("reseller identities re-checked=%s", done)
        return done



@tracked_job
async def telegram_login_gc_job(ctx=None):
    """Drop finished website-login sessions (Telegram bot approval) one day after they expired."""
    from melorin.channels.telegram import web as telegram_web

    async with session_factory()() as s:
        removed = await telegram_web.purge_old(s)
        log.info("telegram web login sessions removed=%s", removed)
        return removed



@tracked_job
async def privacy_retention_job(ctx=None):
    """Remove expired authentication codes and finished outbox/webhook rows (T51) while preserving financial/audit data."""
    async with session_factory()() as s:
        days = int(await settings_store.get(s, "privacy.verification_code_retention_days") or 7)
        cutoff = utcnow() - dt.timedelta(days=max(1, days))
        result = cast(
            "CursorResult[Any]",
            await s.execute(
                delete(VerificationCode)
                .where(
                    VerificationCode.created_at < cutoff,
                    VerificationCode.expires_at < cutoff,
                )
                .execution_options(synchronize_session=False)
            ),
        )
        await s.commit()
        removed = await retention.purge_finished(s)  # T51: finished outbox events / webhook deliveries
        log.info(
            "privacy retention removed verification_codes=%s outbox_events=%s webhook_deliveries=%s",
            result.rowcount or 0,
            removed["outbox_events"],
            removed["webhook_deliveries"],
        )
        return int(result.rowcount or 0)


