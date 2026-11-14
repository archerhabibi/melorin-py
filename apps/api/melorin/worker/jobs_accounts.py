"""Account lifecycle jobs: expiry and near-expiry against the panels."""

import functools
import datetime as dt
import logging

from sqlalchemy import and_, or_, select

from melorin.domain.order_state import VpnSource, VpnStatus, set_vpn_status
from melorin.core import settings_store
from melorin.core.db import session_factory, utcnow
from melorin.modules.vpn_accounts import live, notices, reconcile, sync
from melorin.kernel.models.vpn import VpnAccount
from melorin.modules.panel_integrations.adapters.lifecycle import close_adapter
from melorin.worker.wrap import item_failed, tracked_job

_close_strict = functools.partial(close_adapter, strict=True)  # worker jobs keep raising on close failure
log = logging.getLogger("melorin.jobs")


@tracked_job
async def expiry_job(ctx=None):
    """Overdue accounts. Mediator rule: the PANEL decides ``expired``, not Melorin's clock.

    * an account on a panel is only a *candidate* once its SOLD expiry has passed; it is re-read live from the panel and the
      panel's answer (status, current expiry) is applied. A panel that is down, or an account that is missing there, changes
      nothing (the reconcile job records the issue); a renewal done on the panel simply moves the expiry forward;
    * an account without a panel (manual / legacy) has no other source, so the local clock still applies to it;
    * ``on_hold`` accounts (waiting for their first connection) have no running clock: the live read says so, the status stays
      ``active``, and a read younger than ``sync.FRESH_FOR`` is not repeated.
    """
    async with session_factory()() as s:
        now = utcnow()
        overdue = and_(
            VpnAccount.status == "active",
            VpnAccount.sold_expires_at.is_not(None),
            VpnAccount.sold_expires_at <= now,
        )
        not_just_read = or_(VpnAccount.last_synced_at.is_(None), VpnAccount.last_synced_at < now - sync.FRESH_FOR)
        # accounts without a panel: the only clock there is
        for a in (await s.scalars(select(VpnAccount).where(overdue, VpnAccount.panel_id.is_(None)))).all():
            set_vpn_status(a, VpnStatus.EXPIRED, source=VpnSource.EXPIRY_JOB)
            await notices.expired(s, a)
        await s.commit()
        # accounts on a panel: ask the panel (oldest read first, bounded per run)
        candidates = (
            await s.scalars(
                select(VpnAccount.id)
                .where(overdue, VpnAccount.panel_id.is_not(None), not_just_read)
                .order_by(VpnAccount.last_synced_at.asc().nulls_first())
                .limit(EXPIRY_LIVE_BATCH)
            )
        ).all()
        for account_id in candidates:
            try:
                await reconcile.reconcile_account(s, account_id)  # applies the panel's status; notices fire from sync.apply_remote
            except Exception:
                await s.rollback()
                item_failed("expiry_job")
                log.warning("expiry: live read failed account=%s", account_id, exc_info=True)
        return len(candidates)


@tracked_job
async def near_expiry_job(ctx=None):
    """Warn customers whose subscription is about to end.

    Mediator rule: the SOLD expiry only nominates candidates. For an account on a panel the warning is sent only after a live read
    says the panel agrees: not ``on_hold`` (its clock has not started), and the panel's own expiry is inside the window (a renewal
    done on the panel pushes it out). A panel that does not answer sends nothing and leaves the flag unset, so the next run tries
    again. An account without a panel has no other source, so its sold expiry is used as before.
    """
    async with session_factory()() as s:
        hours = int(await settings_store.get(s, "vpn.near_expiry_hours") or 48)
        now, end = utcnow(), utcnow() + dt.timedelta(hours=hours)
        accounts = (
            await s.scalars(
                select(VpnAccount)
                .where(
                    VpnAccount.status == "active",
                    VpnAccount.near_expiry_notified.is_(False),
                    VpnAccount.sold_expires_at > now,
                    VpnAccount.sold_expires_at <= end,
                )
                .order_by(VpnAccount.sold_expires_at.asc(), VpnAccount.id)  # T23: the soonest-ending accounts are asked first
            )
        ).all()
        on_panel = [a for a in accounts if a.panel_id]
        readings: dict = {}
        # T23: read in pages (one live.read never takes more than MAX_ACCOUNTS) instead of silently dropping everything after the first page
        for start in range(0, min(len(on_panel), NEAR_EXPIRY_MAX_PAGES * live.MAX_ACCOUNTS), live.MAX_ACCOUNTS):
            readings.update(await live.read(s, on_panel[start : start + live.MAX_ACCOUNTS]))
        for a in accounts:
            if a.panel_id:
                reading = readings.get(a.id)
                if reading is None or reading.remote_status == "on_hold":
                    continue  # no verdict (panel silent / clock not started): ask again next run, flag untouched
                panel_expiry = reading.expires_at
                if panel_expiry is not None:
                    if panel_expiry.tzinfo is None:
                        panel_expiry = panel_expiry.replace(tzinfo=dt.UTC)
                    if not (now < panel_expiry <= end):
                        continue  # renewed (or already over) on the panel: this warning would be wrong
            a.near_expiry_notified = True  # reset by a renewal (notices.reset_for_renewal), so the NEXT period warns again
            await notices.near_expiry(s, a)
        await s.commit()


EXPIRY_LIVE_BATCH = 200  # overdue panel accounts re-read per run (the rest wait for the next run)


NEAR_EXPIRY_MAX_PAGES = 5  # bounds one run: at most 5 x live.MAX_ACCOUNTS panel reads
