"""Account <-> panel status and usage sync (PG-02). The panel is the source of truth for state; Melorin keeps a normalised copy.

``status_from_remote`` is the ONE two-way mapping table; ``apply_remote`` copies everything the panel reports onto the account and
returns which transitions happened so the caller can notify. Pure of network: it only reads the :class:`PanelAccount` it is given.
"""

import datetime as dt

from melorin.core.db import utcnow
from melorin.domain.order_state import VpnStatus
from melorin.modules.vpn import notices

# Melorin statuses the panel may overwrite. pending / provisioning / revoked / archived are Melorin-only lifecycle states.
SYNCABLE = (VpnStatus.ACTIVE, VpnStatus.SUSPENDED, VpnStatus.EXPIRED, VpnStatus.LIMITED)
# Panel status (raw) -> Melorin status. ``on_hold`` (waiting for first connection) is usable, so it is ``active``; the raw value is
# kept in ``VpnAccount.remote_status`` and shown to the customer as "starts at first connection".
REMOTE_TO_LOCAL = {
    "active": VpnStatus.ACTIVE,
    "on_hold": VpnStatus.ACTIVE,
    "limited": VpnStatus.LIMITED,
    "expired": VpnStatus.EXPIRED,
    "disabled": VpnStatus.SUSPENDED,
}
# A panel read younger than this is trusted by ``expiry_job`` (it does not second-guess the panel with Melorin's own clock).
FRESH_FOR = dt.timedelta(minutes=30)
# Differences below these are noise (clock rounding), not a manual edit on the panel.
EXPIRY_TOLERANCE = dt.timedelta(hours=1)


def _g(obj, name: str, default=None):
    """Panel adapters of other kinds (and test doubles) may not report every field: a missing one means \"not reported\"."""
    return getattr(obj, name, default)


def aware(value: dt.datetime | None) -> dt.datetime | None:
    return value if value is None or value.tzinfo else value.replace(tzinfo=dt.UTC)


def status_from_remote(local: str, remote) -> str:
    """The Melorin status the account should have, given what the panel reports. Unknown panel values and Melorin-only states
    leave the status alone."""
    if local not in SYNCABLE:
        return local
    raw = (getattr(remote, "remote_status", None) or getattr(remote, "status", None) or "").lower()
    return REMOTE_TO_LOCAL.get(raw, local)


def is_fresh(account, now: dt.datetime | None = None) -> bool:
    synced = aware(account.last_synced_at)
    return synced is not None and (now or utcnow()) - synced <= FRESH_FOR


def limits_drift(account, remote) -> dict | None:
    """Did someone change expiry/volume on the panel behind Melorin's back? Needs a baseline (a previous sync) and ignores the
    legitimate first-connection start of an ``on_hold`` account."""
    if account.last_synced_at is None or account.remote_status == "on_hold":
        return None
    diff: dict = {}
    if not hasattr(remote, "traffic_limit_bytes"):
        return None
    mine, theirs = aware(account.expires_at), aware(_g(remote, "expire_at"))
    if mine is not None and theirs is not None and abs(mine - theirs) > EXPIRY_TOLERANCE:
        diff["expires_at"] = {"melorin": mine.isoformat(), "panel": theirs.isoformat()}
    elif (mine is None) != (theirs is None):
        diff["expires_at"] = {"melorin": mine.isoformat() if mine else None, "panel": theirs.isoformat() if theirs else None}
    if int(account.traffic_limit_bytes or 0) != int(remote.traffic_limit_bytes or 0):
        diff["traffic_limit_bytes"] = {"melorin": int(account.traffic_limit_bytes or 0), "panel": int(remote.traffic_limit_bytes or 0)}
    return diff or None


async def apply_remote(
    session, account, remote, *, now: dt.datetime | None = None, notify: bool = True, levels: tuple[int, ...] | None = None
) -> list[str]:
    """Copy the panel's state onto ``account``. Returns the list of status transitions (``"active->limited"``).

    Notices (all idempotent through their dedup keys): quota exhausted, disabled on the panel, expired on the panel, and the
    traffic warnings (the store's own ``levels``, default 80% / 90%). The caller commits.
    """
    now = now or utcnow()
    previous = account.status
    new_status = status_from_remote(previous, remote)
    changes: list[str] = []
    if new_status != previous:
        account.status = new_status
        changes.append(f"{previous}->{new_status}")

    remote_status = _g(remote, "remote_status")
    on_hold = (remote_status or "") == "on_hold"
    account.traffic_used_bytes = int(_g(remote, "traffic_used_bytes", 0) or 0)
    if hasattr(remote, "traffic_limit_bytes"):
        account.traffic_limit_bytes = int(remote.traffic_limit_bytes or 0)
    if not on_hold and _g(remote, "expire_at") is not None:  # on_hold: no expiry yet, keep the package length Melorin sold
        account.expires_at = remote.expire_at
    elif not on_hold and hasattr(remote, "traffic_limit_bytes"):
        account.expires_at = None  # a full PanelAccount without expiry = the panel shows unlimited time
    account.subscription_url, account.links = _g(remote, "subscription_url"), _g(remote, "links")
    account.remote_status = remote_status
    # R7: ``online_at`` / ``lifetime_used_traffic`` are no longer copied; "last seen" is read live (account_tools.presence).
    account.last_synced_at, account.sync_error_count = now, 0
    if account.queued_plan:  # PG-09: a prepaid package that the panel no longer reports as queued has started
        from melorin.modules.vpn import plans  # local import: plans builds on this module

        await plans.settle_from_remote(session, account, remote, now=now, notify=notify)

    if notify and account.status in SYNCABLE:
        if changes and new_status == VpnStatus.LIMITED:
            await notices.traffic_exhausted(session, account)
        elif changes and new_status == VpnStatus.SUSPENDED and previous == VpnStatus.ACTIVE:
            await notices.disabled_by_panel(session, account)
        elif changes and new_status == VpnStatus.EXPIRED:
            await notices.expired(session, account)
        if account.status == VpnStatus.ACTIVE:
            # R4: the warning level is read off the panel's own numbers in ``remote``, not off the stored copy just written above.
            percent = notices.percent_of(
                _g(remote, "traffic_limit_bytes", account.traffic_limit_bytes), _g(remote, "traffic_used_bytes", 0)
            )
            level = notices.traffic_level(percent, notices.TRAFFIC_LOW_LEVELS if levels is None else levels)
            if level > int(account.traffic_notified_level or 0):
                await notices.traffic_low(session, account, level)
                account.traffic_notified_level = level
            elif level == 0 and percent is not None and int(account.traffic_notified_level or 0):
                account.traffic_notified_level = 0  # usage went back down (reset on the panel): warn again next time
    return changes
