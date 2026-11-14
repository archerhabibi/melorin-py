"""Reconciliation issues (PG-04): open / bump / auto-close with exactly ONE open row per (account, kind).

The partial unique index ``uq_reconciliation_issue_open`` enforces that in the database; this module is the only writer, so a repeat
only raises ``occurrences`` and refreshes ``last_seen_at`` instead of piling up duplicates, and a condition that clears closes the row.
"""

import datetime as dt
import uuid

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from melorin.core.db import utcnow
from melorin.kernel.models.vpn import ReconciliationIssue

MISSING = "missing_on_panel"
UNREACHABLE = "panel_unreachable"
OWNER_MISMATCH = "owner_mismatch"
LIMITS_MISMATCH = "limits_mismatch"
KINDS = (MISSING, UNREACHABLE, OWNER_MISMATCH, LIMITS_MISMATCH)
# Closed by the system when the condition clears. R9: ``limits_mismatch`` compares the panel with what Melorin SOLD; Melorin no longer
# copies the panel's values over the entitlement, so the drift stays visible until the panel and the entitlement agree again (or an
# admin runs ``accept_panel`` / ``ignore``).
AUTO_CLOSE = (MISSING, UNREACHABLE, OWNER_MISMATCH, LIMITS_MISMATCH)
OPEN, RESOLVED, IGNORED = "open", "resolved", "ignored"


async def open_issue(
    session: AsyncSession, account_id: uuid.UUID, kind: str, details: dict | None = None, *, now: dt.datetime | None = None
) -> ReconciliationIssue:
    """Record that ``kind`` is (still) true for the account: create the open row or bump the existing one."""
    now = now or utcnow()
    row = await session.scalar(
        select(ReconciliationIssue).where(
            ReconciliationIssue.vpn_account_id == account_id, ReconciliationIssue.kind == kind, ReconciliationIssue.status == OPEN
        )
    )
    if row is not None:
        row.occurrences, row.last_seen_at = int(row.occurrences or 1) + 1, now
        if details is not None:
            row.details = details
        return row
    row = ReconciliationIssue(vpn_account_id=account_id, kind=kind, details=details, status=OPEN, occurrences=1, last_seen_at=now)
    try:
        async with session.begin_nested():  # a concurrent writer may win the unique index: then bump theirs
            session.add(row)
            await session.flush()
    except IntegrityError:
        existing = await session.scalar(
            select(ReconciliationIssue).where(
                ReconciliationIssue.vpn_account_id == account_id, ReconciliationIssue.kind == kind, ReconciliationIssue.status == OPEN
            )
        )
        if existing is None:
            raise
        existing.occurrences, existing.last_seen_at = int(existing.occurrences or 1) + 1, now
        return existing
    return row


async def ignored_identical(session: AsyncSession, account_id: uuid.UUID, kind: str, details: dict | None) -> bool:
    """Did an admin already ``ignore`` exactly this finding? An ignored drift is not re-opened while it is unchanged."""
    last = await session.scalar(
        select(ReconciliationIssue)
        .where(ReconciliationIssue.vpn_account_id == account_id, ReconciliationIssue.kind == kind, ReconciliationIssue.status == IGNORED)
        .order_by(ReconciliationIssue.resolved_at.desc().nulls_last())
        .limit(1)
    )
    return last is not None and (last.details or None) == (details or None)


async def close_issues(
    session: AsyncSession, account_ids: list[uuid.UUID], kinds: tuple[str, ...] | list[str], *, resolution: str = "auto", now=None
) -> int:
    """Close every OPEN issue of ``kinds`` for ``account_ids`` (the condition no longer holds)."""
    if not account_ids or not kinds:
        return 0
    result = await session.execute(
        update(ReconciliationIssue)
        .where(ReconciliationIssue.vpn_account_id.in_(account_ids), ReconciliationIssue.kind.in_(kinds), ReconciliationIssue.status == OPEN)
        .values(status=RESOLVED, resolution=resolution, resolved_at=now or utcnow())
    )
    return int(result.rowcount or 0)


async def close_for_inactive(session: AsyncSession, panel_id: uuid.UUID, *, now=None) -> int:
    """Close the open issues of accounts that were archived or revoked on purpose (their panel user is gone by design).

    Reconcile only looks at live accounts, so without this an issue such as ``missing_on_panel`` on an archived account could
    never close itself and would stay in the admin list for ever.
    """
    from melorin.domain.order_state import VpnStatus
    from melorin.kernel.models.vpn import VpnAccount

    inactive = select(VpnAccount.id).where(
        VpnAccount.panel_id == panel_id,
        (VpnAccount.archived_at.is_not(None)) | (VpnAccount.status.in_((VpnStatus.ARCHIVED, VpnStatus.REVOKED))),
    )
    result = await session.execute(
        update(ReconciliationIssue)
        .where(ReconciliationIssue.vpn_account_id.in_(inactive), ReconciliationIssue.status == OPEN)
        .values(status=RESOLVED, resolution="account_inactive", resolved_at=now or utcnow())
        .execution_options(synchronize_session=False)
    )
    return int(result.rowcount or 0)
