"""Reporting jobs: Event Center daily report and store digest."""

import functools
import logging


from melorin.core.db import session_factory
from melorin.modules.eventcenter import report as event_center_report
from melorin.modules.panel_integrations.adapters.lifecycle import close_adapter
from melorin.worker.wrap import tracked_job

_close_strict = functools.partial(close_adapter, strict=True)  # worker jobs keep raising on close failure
log = logging.getLogger("melorin.jobs")


@tracked_job
async def daily_report_job(ctx=None):
    """Queue the Event Center nightly summary (one per group). Safe to run twice: the report is deduplicated per Tehran day."""
    async with session_factory()() as session:
        queued = await event_center_report.run(session)
        await session.commit()
    return queued


@tracked_job
async def store_digest_job(ctx=None):
    """Daily: the opt-in digest for store owners (PG-06). Says only what Melorin owns (notices sent, open discrepancies, sell blocks)."""
    from melorin.modules.panelops import digest

    async with session_factory()() as session:
        queued = await digest.run(session)
        await session.commit()
    return queued
