"""Account <-> panel status sync (PG-02). The panel is the source of truth for state; Melorin keeps only the derived ``status`` bucket.

``status_from_remote`` is the ONE two-way mapping table; ``apply_remote`` derives the status from what the panel reports and returns
which transitions happened so the caller can notify. It never copies used traffic, limit, expiry or link onto the account (R9/R10):
those are read live (``live.py``). ``record_sale`` is the single writer of the sold entitlement. Pure of network.
"""

import datetime as dt

from melorin.core.db import utcnow
from melorin.domain.order_state import VpnSource, VpnStatus, set_vpn_status
from melorin.domain.timeutil import aware  # noqa: F401  (re-exported: callers use sync.aware)
from melorin.modules.vpn_accounts import freshness, notices

# Melorin statuses the panel may overwrite. pending / provisioning / revoked / archived are Melorin-only lifecycle states.
SYNCABLE = (VpnStatus.ACTIVE, VpnStatus.SUSPENDED, VpnStatus.EXPIRED, VpnStatus.LIMITED)
# Panel status (raw) -> Melorin status. ``on_hold`` (waiting for first connection) is usable, so it is ``active``; the raw value is
# read live (``live.LiveReading.remote_status``) and shown to the customer as "starts at first connection".
REMOTE_TO_LOCAL = {
    "active": VpnStatus.ACTIVE,
    "on_hold": VpnStatus.ACTIVE,
    "limited": VpnStatus.LIMITED,
    "expired": VpnStatus.EXPIRED,
    "disabled": VpnStatus.SUSPENDED,
}
# A panel read younger than this is trusted by ``expiry_job`` (it does not second-guess the panel with Melorin's own clock).
FRESH_FOR = freshness.STORED_FOR  # kept as an alias; the policy lives in ``freshness``
# Differences below these are noise (clock rounding), not a manual edit on the panel.
EXPIRY_TOLERANCE = dt.timedelta(hours=1)


def _g(obj, name: str, default=None):
    """Panel adapters of other kinds (and test doubles) may not report every field: a missing one means \"not reported\"."""
    return getattr(obj, name, default)


def status_from_remote(local: str, remote) -> str:
    """The Melorin status the account should have, given what the panel reports. Unknown panel values and Melorin-only states
    leave the status alone."""
    if local not in SYNCABLE:
        return local
    raw = (getattr(remote, "remote_status", None) or getattr(remote, "status", None) or "").lower()
    return REMOTE_TO_LOCAL.get(raw, local)


def is_fresh(account, now: dt.datetime | None = None) -> bool:
    synced = aware(account.last_synced_at)
    return freshness.is_stored_copy_fresh(synced, now or utcnow())


def limits_drift(account, remote) -> dict | None:
    """Did someone change expiry/volume on the panel behind Melorin's back? Compares the panel with the SOLD entitlement. Needs a
    baseline (a previous sync) and ignores the legitimate first-connection start of an ``on_hold`` account (the panel has no
    expiry yet; the package length Melorin sold applies from the first connection)."""
    if account.last_synced_at is None or (_g(remote, "remote_status") or "") == "on_hold":
        return None
    diff: dict = {}
    if not hasattr(remote, "traffic_limit_bytes"):
        return None
    mine, theirs = aware(account.sold_expires_at), aware(_g(remote, "expire_at"))
    if mine is not None and theirs is not None and abs(mine - theirs) > EXPIRY_TOLERANCE:
        diff["expires_at"] = {"melorin": mine.isoformat(), "panel": theirs.isoformat()}
    elif (mine is None) != (theirs is None):
        diff["expires_at"] = {"melorin": mine.isoformat() if mine else None, "panel": theirs.isoformat() if theirs else None}
    if int(account.sold_traffic_bytes or 0) != int(remote.traffic_limit_bytes or 0):
        diff["traffic_limit_bytes"] = {"melorin": int(account.sold_traffic_bytes or 0), "panel": int(remote.traffic_limit_bytes or 0)}
    return diff or None


def record_sale(account, expires_at: dt.datetime | None, traffic_bytes: int) -> None:
    """R10: the ONE writer of the sold entitlement. Every Melorin act (purchase, renewal, plan change, compensation, bulk extend,
    re-create, "accept panel") calls it with the absolute values it just applied on the panel. A sync never calls it."""
    account.sold_expires_at = expires_at
    account.sold_traffic_bytes = int(traffic_bytes or 0)


def delivery_snapshot(remote, *, now: dt.datetime | None = None) -> dict:
    """What the customer is handed (link + links) at delivery. A fallback for QR/delivery text, never a reader of truth."""
    links = _g(remote, "links")
    return {
        "subscription_url": _g(remote, "subscription_url"),
        "links": list(links) if links else None,
        "taken_at": (now or utcnow()).isoformat(),
    }


async def apply_remote(
    session, account, remote, *, now: dt.datetime | None = None, notify: bool = True, levels: tuple[int, ...] | None = None
) -> list[str]:
    """Derive ``account.status`` from the panel's reading. Returns the list of status transitions (``"active->limited"``).

    Notices (all idempotent through their dedup keys): quota exhausted, disabled on the panel, expired on the panel, and the
    traffic warnings (the store's own ``levels``, default 80% / 90%). The caller commits.
    """
    now = now or utcnow()
    previous = account.status
    new_status = status_from_remote(previous, remote)
    changes: list[str] = []
    if new_status != previous:
        set_vpn_status(account, VpnStatus(new_status), source=VpnSource.PANEL_SYNC)
        changes.append(f"{previous}->{new_status}")

    # R9/R10: nothing of the panel's numbers is copied. Used traffic, limit, expiry, link and last seen are read live (live.py).
    account.last_synced_at, account.sync_error_count = now, 0
    if account.queued_plan:  # PG-09: a prepaid package that the panel no longer reports as queued has started
        from melorin.modules.vpn_accounts import plans  # local import: plans builds on this module

        await plans.settle_from_remote(session, account, remote, now=now, notify=notify)

    if notify and account.status in SYNCABLE:
        if changes and new_status == VpnStatus.LIMITED:
            await notices.traffic_exhausted(session, account)
        elif changes and new_status == VpnStatus.SUSPENDED and previous == VpnStatus.ACTIVE:
            await notices.disabled_by_panel(session, account)
        elif changes and new_status == VpnStatus.EXPIRED:
            await notices.expired(session, account)
        if account.status == VpnStatus.ACTIVE:
            # R4: the warning level is read off the panel's own numbers in ``remote``; there is no stored copy to read.
            percent = notices.percent_of(_g(remote, "traffic_limit_bytes", account.sold_traffic_bytes), _g(remote, "traffic_used_bytes", 0))
            level = notices.traffic_level(percent, notices.TRAFFIC_LOW_LEVELS if levels is None else levels)
            if level > int(account.traffic_notified_level or 0):
                await notices.traffic_low(session, account, level)
                account.traffic_notified_level = level
            elif level == 0 and percent is not None and int(account.traffic_notified_level or 0):
                account.traffic_notified_level = 0  # usage went back down (reset on the panel): warn again next time
    return changes
