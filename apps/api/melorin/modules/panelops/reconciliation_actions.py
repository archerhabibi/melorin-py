"""Reconciliation issue actions: the ONE place that turns an admin decision on a reconciliation issue into state changes.

Arch review 2026-11-13 §4.2: this used to live inside the ``admin`` router, which built a panel adapter itself (``fix_owner``) and
coordinated several models. The router now only validates input, authorizes and loads the rows; every multi-step mutation, the panel
call, the audit record and the commit happen here, so a job or a bot could call the same code without re-implementing it.

Orphan -> account linking (``link_existing``) is the same operation as ``vpn.manual_assign``'s orphan assignment from the admin's point of
view; both keep writing through the shared ``queries.username_in_use`` guard so a panel user can never belong to two accounts.
"""

from __future__ import annotations

import uuid

from melorin.core import audit
from melorin.core.db import utcnow
from melorin.core.errors import AppError, NotFound
from melorin.core.uow import unit_of_work
from melorin.domain.order_state import VpnStatus, set_vpn_status
from melorin.kernel.models.vpn import Panel, PanelOrphan, ReconciliationIssue, VpnAccount
from melorin.modules.panelops import queries, recreate
from melorin.modules.vpn import issues as issue_svc
from melorin.modules.vpn import reconcile
from melorin.modules.vpn.adapters.base import PanelError, supports
from melorin.modules.vpn.adapters.registry import build_adapter, seed_adapter
from melorin.modules.vpn.panel_session import close_adapter

ACTIONS = ("ignore", "resolve", "fix_owner", "archive_account", "link_existing", "recreate_on_panel", "resync", "accept_panel")
_NEEDS_REASON = {
    "ignore": "برای نادیده گرفتن، دلیل را بنویسید.",
    "recreate_on_panel": "برای ساخت دوباره روی پنل، دلیل را بنویسید.",
    "accept_panel": "برای پذیرفتن مقادیر پنل، دلیل را بنویسید.",
}


def allowed_actions(kind: str, status: str) -> list[str]:
    """What an admin may do with an issue. Closed issues take no action."""
    if status != issue_svc.OPEN:
        return []
    extra = {
        issue_svc.OWNER_MISMATCH: ["fix_owner"],
        issue_svc.MISSING: ["link_existing", "recreate_on_panel", "archive_account"],
        issue_svc.LIMITS_MISMATCH: ["accept_panel"],
    }.get(kind, [])
    return ["resync", *extra, "resolve", "ignore"]


def _finish(issue: ReconciliationIssue, status: str, resolution: str, now) -> None:
    issue.status, issue.resolution, issue.resolved_at = status, resolution[:300], now


async def _fix_owner(session, issue: ReconciliationIssue, account: VpnAccount) -> str:
    expected = (issue.details or {}).get("expected")
    panel = await session.get(Panel, account.panel_id) if account.panel_id else None
    if not (expected and panel and account.panel_ref):
        raise AppError("CANNOT_FIX_OWNER", "مالک مورد انتظار یا شناسهٔ کاربر روی پنل مشخص نیست.", 409)
    adapter = None
    try:
        adapter = seed_adapter(build_adapter(panel), account)
        if not supports(adapter, "bulk_ops"):
            raise AppError("CAPABILITY_MISSING", "این اتصال اجازهٔ تغییر مالک را ندارد.", 409)
        await adapter.bulk_set_owner([str(account.panel_ref)], str(expected))
    except PanelError as exc:
        raise AppError("PANEL_ERROR", f"پنل خطا داد: {exc.message[:200]}", 502) from exc
    finally:
        await close_adapter(adapter)
    return f"owner set to {expected}"


async def _link_existing(session, account: VpnAccount, orphan_id: uuid.UUID | None) -> tuple[PanelOrphan, str]:
    if orphan_id is None:
        raise AppError("ORPHAN_REQUIRED", "کاربر موجود روی پنل را انتخاب کنید.", 422)
    orphan = await session.get(PanelOrphan, orphan_id)
    if not orphan or orphan.panel_id != account.panel_id or orphan.status == "gone":
        raise NotFound("کاربر پنل")
    if len(orphan.username) > 64 or await queries.username_in_use(session, orphan.username, except_account_id=account.id):
        raise AppError("USERNAME_TAKEN", "این کاربر پنل قبلاً به اکانت دیگری وصل است یا نامش معتبر نیست.", 409)
    account.username = orphan.username
    account.panel_ref = str(orphan.remote_id) if orphan.remote_id is not None else None
    account.sync_error_count = 0
    orphan.status, orphan.note = "gone", f"linked to account {account.id}"[:300]
    return orphan, f"linked to panel user {orphan.username}"


async def apply_action(
    session,
    issue: ReconciliationIssue,
    account: VpnAccount,
    *,
    action: str,
    reason: str | None,
    orphan_id: uuid.UUID | None,
    actor_id: uuid.UUID,
) -> None:
    """Apply one admin action to one issue, audit it and commit. Raises ``AppError`` for a refused action; the caller reloads the rows."""
    if action not in allowed_actions(issue.kind, issue.status):
        raise AppError("ACTION_NOT_ALLOWED", "این اقدام برای این مغایرت مجاز نیست.", 409)
    reason = (reason or "").strip() or None
    if action in _NEEDS_REASON and not reason:
        raise AppError("REASON_REQUIRED", _NEEDS_REASON[action], 422)
    now = utcnow()
    extra_audit: dict = {}

    if action == "ignore":
        _finish(issue, issue_svc.IGNORED, f"ignored: {reason}", now)
    elif action == "resolve":
        _finish(issue, issue_svc.RESOLVED, f"admin: {reason or 'resolved'}", now)
    elif action == "archive_account":
        set_vpn_status(account, VpnStatus.ARCHIVED)
        account.archived_at = now
        _finish(issue, issue_svc.RESOLVED, f"archived: {reason or 'missing on panel'}", now)
    elif action == "link_existing":
        _, why = await _link_existing(session, account, orphan_id)
        _finish(issue, issue_svc.RESOLVED, why, now)
    elif action == "recreate_on_panel":
        new_ref = await recreate.recreate_on_panel(session, account)
        _finish(issue, issue_svc.RESOLVED, f"re-created on panel (ref {new_ref}): {reason}", now)
    elif action == "accept_panel":
        extra_audit = await reconcile.accept_panel(session, account)
        _finish(issue, issue_svc.RESOLVED, f"accepted panel values: {reason}", now)
    elif action == "fix_owner":
        _finish(issue, issue_svc.RESOLVED, await _fix_owner(session, issue, account), now)
    elif action == "resync":
        outcome = await reconcile.reconcile_account(session, account.id)
        await session.refresh(issue)
        async with unit_of_work(session):
            _audit(session, "reconciliation.resync", actor_id, account, {"issue": str(issue.id), "outcome": outcome})
        return

    async with unit_of_work(session):
        _audit(
            session,
            f"reconciliation.{action}",
            actor_id,
            account,
            {"issue": str(issue.id), "kind": issue.kind, "reason": reason, **extra_audit},
        )
    if action in ("link_existing", "recreate_on_panel"):
        await reconcile.reconcile_account(session, account.id)  # verify the link against the panel right away
        await session.refresh(issue)


def _audit(session, event: str, actor_id: uuid.UUID, account: VpnAccount, data: dict) -> None:
    audit.record(
        session,
        event,
        actor_id=actor_id,
        actor_type="admin",
        entity_type="vpn_account",
        entity_id=account.id,
        store_id=account.store_id,
        data=data,
    )
