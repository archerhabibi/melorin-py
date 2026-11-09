"""Admin API - panel reconciliation: node health, reconciliation issues and their actions (PasarGuard roadmap Phase 1).

Read endpoints are plain lists. Every write is an explicit admin decision, audited, and limited to the issue's own kind:
``ignore`` / ``resolve`` (any kind), ``fix_owner`` (owner_mismatch), ``archive_account`` / ``link_existing`` / ``recreate_on_panel`` (missing_on_panel),
``resync`` (re-check now). Nothing here deletes anything on a panel. Orphans live in ``panel_orphans``.
"""

import datetime as dt
import logging
import uuid

from fastapi import APIRouter
from pydantic import BaseModel, Field

from melorin.core import audit
from melorin.core.db import utcnow
from melorin.core.deps import AdminUser, Session
from melorin.core.errors import AppError, NotFound
from melorin.domain.order_state import VpnStatus
from melorin.kernel.models.stores import Store
from melorin.kernel.models.vpn import Panel, PanelOrphan, ReconciliationIssue, VpnAccount
from melorin.modules.vpn.panel_session import close_adapter
from melorin.modules.vpn import issues as issue_svc
from melorin.modules.vpn import reconcile, recreate
from melorin.modules.vpn.adapters.base import PanelError, supports
from melorin.modules.vpn.adapters.registry import build_adapter, seed_adapter

from melorin.modules.panelops import queries

router = APIRouter(prefix="/admin", tags=["admin"])
log = logging.getLogger("melorin.admin.panel_reconciliation")

ACTIONS = ("ignore", "resolve", "fix_owner", "archive_account", "link_existing", "recreate_on_panel", "resync", "accept_panel")


class NodeOut(BaseModel):
    remote_id: int
    name: str
    status: str
    message: str | None = None
    hint: str | None = None
    xray_version: str | None = None
    usage_coefficient: float | None = None
    last_seen_at: dt.datetime | None = None
    status_changed_at: dt.datetime | None = None


class PanelNodesOut(BaseModel):
    panel_id: uuid.UUID
    health_status: str
    last_health_at: dt.datetime | None
    last_health_error: str | None = None
    detail: dict | None = None
    nodes: list[NodeOut]


class IssueOut(BaseModel):
    id: uuid.UUID
    kind: str
    status: str
    occurrences: int
    details: dict | None = None
    created_at: dt.datetime
    last_seen_at: dt.datetime | None = None
    resolved_at: dt.datetime | None = None
    resolution: str | None = None
    vpn_account_id: uuid.UUID
    username: str | None = None
    store_id: uuid.UUID | None = None
    store_name: str | None = None
    panel_id: uuid.UUID | None = None
    panel_name: str | None = None
    allowed_actions: list[str] = []


class IssueActionIn(BaseModel):
    action: str = Field(pattern="^(ignore|resolve|fix_owner|archive_account|link_existing|recreate_on_panel|resync|accept_panel)$")
    reason: str | None = Field(default=None, max_length=300)
    orphan_id: uuid.UUID | None = None  # link_existing: the panel user (orphan of the SAME panel) this account really is


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


# ------------------------------------------------------------------------------------------------------------------ nodes
@router.get("/panels/{panel_id}/nodes", response_model=PanelNodesOut)
async def panel_nodes(panel_id: uuid.UUID, _: AdminUser, session: Session):
    from melorin.modules.vpn.health import node_error_hint

    panel = await session.get(Panel, panel_id)
    if not panel:
        raise NotFound("پنل")
    rows = await queries.live_nodes(session, panel_id)
    nodes = [
        NodeOut(
            remote_id=r.remote_id,
            name=r.name,
            status=r.status,
            message=r.message,
            hint=node_error_hint(r.message) if r.status in ("error", "limited", "unknown") else None,
            xray_version=r.xray_version,
            usage_coefficient=r.usage_coefficient,
            last_seen_at=r.last_seen_at,
            status_changed_at=r.status_changed_at,
        )
        for r in rows
    ]
    return PanelNodesOut(
        panel_id=panel.id,
        health_status=panel.health_status,
        last_health_at=panel.last_health_at,
        last_health_error=panel.last_health_error,
        detail=panel.health_detail,
        nodes=nodes,
    )


@router.post("/panels/{panel_id}/reconcile")
async def reconcile_panel_now(panel_id: uuid.UUID, admin: AdminUser, session: Session):
    """Run reconcile v2 for one panel right now (the hourly job does the same)."""
    panel = await session.get(Panel, panel_id)
    if not panel:
        raise NotFound("پنل")
    result = await reconcile.reconcile_panel(session, panel)
    audit.record(
        session,
        "panel.reconcile",
        actor_id=admin.id,
        actor_type="admin",
        entity_type="panel",
        entity_id=panel.id,
        data={"checked": result.checked, "missing": result.missing, "orphans": result.orphans, "unreachable": result.unreachable},
    )
    await session.commit()
    return {
        "checked": result.checked,
        "updated": result.updated,
        "missing": result.missing,
        "owner_mismatch": result.owner_mismatch,
        "limits_mismatch": result.limits_mismatch,
        "orphans": result.orphans,
        "unreachable": result.unreachable,
        "complete": result.complete,
        "errors": result.errors,
    }


# ------------------------------------------------------------------------------------------------------------------ issues
async def _issue_rows(session, *, status, kind, panel_id, limit, offset):
    return await queries.issue_rows(session, status=status, kind=kind, panel_id=panel_id, limit=limit, offset=offset)


def _issue_out(i: ReconciliationIssue, a: VpnAccount, store: Store | None, panel: Panel | None) -> IssueOut:
    return IssueOut(
        id=i.id,
        kind=i.kind,
        status=i.status,
        occurrences=int(i.occurrences or 1),
        details=i.details,
        created_at=i.created_at,
        last_seen_at=i.last_seen_at,
        resolved_at=i.resolved_at,
        resolution=i.resolution,
        vpn_account_id=a.id,
        username=a.username,
        store_id=a.store_id,
        store_name=getattr(store, "name", None),
        panel_id=a.panel_id,
        panel_name=getattr(panel, "name", None),
        allowed_actions=allowed_actions(i.kind, i.status),
    )


@router.get("/reconciliation/issues")
async def reconciliation_issues(
    _: AdminUser,
    session: Session,
    status: str | None = "open",
    kind: str | None = None,
    panel_id: uuid.UUID | None = None,
    limit: int = 50,
    offset: int = 0,
):
    if status not in (None, "all", "open", "resolved", "ignored"):
        raise AppError("BAD_STATUS", "وضعیت نامعتبر است.", 422)
    if kind and kind not in issue_svc.KINDS:
        raise AppError("BAD_KIND", "نوع مغایرت نامعتبر است.", 422)
    total, rows = await _issue_rows(
        session,
        status=None if status in (None, "all") else status,
        kind=kind,
        panel_id=panel_id,
        limit=max(1, min(limit, 200)),
        offset=max(0, offset),
    )
    return {"total": total, "items": [_issue_out(i, a, s, p) for i, a, s, p in rows]}


@router.get("/reconciliation/summary")
async def reconciliation_summary(_: AdminUser, session: Session):
    by_kind, orphans, manual, oldest = await queries.reconciliation_counts(session, issue_svc.OPEN)
    return {
        "open": {k: int(by_kind.get(k, 0)) for k in issue_svc.KINDS},
        "open_total": int(sum(by_kind.values())),
        "orphans_open": int(orphans),
        "orphans_manual": int(manual),
        "oldest_sync_at": oldest,
    }


@router.post("/reconciliation/issues/{issue_id}/action", response_model=IssueOut)
async def issue_action(issue_id: uuid.UUID, body: IssueActionIn, admin: AdminUser, session: Session):
    issue = await session.get(ReconciliationIssue, issue_id)
    if not issue:
        raise NotFound("مغایرت")
    if body.action not in allowed_actions(issue.kind, issue.status):
        raise AppError("ACTION_NOT_ALLOWED", "این اقدام برای این مغایرت مجاز نیست.", 409)
    account = await session.get(VpnAccount, issue.vpn_account_id)
    now = utcnow()
    reason = (body.reason or "").strip() or None
    extra_audit: dict = {}
    if body.action == "ignore":
        if not reason:
            raise AppError("REASON_REQUIRED", "برای نادیده گرفتن، دلیل را بنویسید.", 422)
        issue.status, issue.resolution, issue.resolved_at = issue_svc.IGNORED, f"ignored: {reason}"[:300], now
    elif body.action == "resolve":
        issue.status, issue.resolution, issue.resolved_at = issue_svc.RESOLVED, f"admin: {reason or 'resolved'}"[:300], now
    elif body.action == "archive_account":
        account.status, account.archived_at = VpnStatus.ARCHIVED, now
        issue.status, issue.resolution, issue.resolved_at = issue_svc.RESOLVED, f"archived: {reason or 'missing on panel'}"[:300], now
    elif body.action == "link_existing":
        if body.orphan_id is None:
            raise AppError("ORPHAN_REQUIRED", "کاربر موجود روی پنل را انتخاب کنید.", 422)
        orphan = await session.get(PanelOrphan, body.orphan_id)
        if not orphan or orphan.panel_id != account.panel_id or orphan.status == "gone":
            raise NotFound("کاربر پنل")
        if len(orphan.username) > 64 or await queries.username_in_use(session, orphan.username, except_account_id=account.id):
            raise AppError("USERNAME_TAKEN", "این کاربر پنل قبلاً به اکانت دیگری وصل است یا نامش معتبر نیست.", 409)
        account.username = orphan.username
        account.panel_ref = str(orphan.remote_id) if orphan.remote_id is not None else None
        account.sync_error_count = 0
        orphan.status, orphan.note = "gone", f"linked to account {account.id}"[:300]
        issue.status, issue.resolution, issue.resolved_at = issue_svc.RESOLVED, f"linked to panel user {orphan.username}"[:300], now
    elif body.action == "recreate_on_panel":
        if not reason:
            raise AppError("REASON_REQUIRED", "برای ساخت دوباره روی پنل، دلیل را بنویسید.", 422)
        new_ref = await recreate.recreate_on_panel(session, account)
        issue.status, issue.resolution, issue.resolved_at = issue_svc.RESOLVED, f"re-created on panel (ref {new_ref}): {reason}"[:300], now
    elif body.action == "accept_panel":
        if not reason:
            raise AppError("REASON_REQUIRED", "برای پذیرفتن مقادیر پنل، دلیل را بنویسید.", 422)
        change = await reconcile.accept_panel(session, account)
        issue.status, issue.resolution, issue.resolved_at = issue_svc.RESOLVED, f"accepted panel values: {reason}"[:300], now
        extra_audit = change
    elif body.action == "fix_owner":
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
        issue.status, issue.resolution, issue.resolved_at = issue_svc.RESOLVED, f"owner set to {expected}", now
    elif body.action == "resync":
        outcome = await reconcile.reconcile_account(session, account.id)
        await session.refresh(issue)
        audit.record(
            session,
            "reconciliation.resync",
            actor_id=admin.id,
            actor_type="admin",
            entity_type="vpn_account",
            entity_id=account.id,
            store_id=account.store_id,
            data={"issue": str(issue.id), "outcome": outcome},
        )
        await session.commit()
        store, panel = (
            await session.get(Store, account.store_id),
            (await session.get(Panel, account.panel_id) if account.panel_id else None),
        )
        return _issue_out(issue, account, store, panel)
    audit.record(
        session,
        f"reconciliation.{body.action}",
        actor_id=admin.id,
        actor_type="admin",
        entity_type="vpn_account",
        entity_id=account.id,
        store_id=account.store_id,
        data={"issue": str(issue.id), "kind": issue.kind, "reason": reason, **(extra_audit if body.action == "accept_panel" else {})},
    )
    await session.commit()
    if body.action in ("link_existing", "recreate_on_panel"):
        await reconcile.reconcile_account(session, account.id)  # verify the link against the panel right away
        await session.refresh(issue)
    store, panel = await session.get(Store, account.store_id), (await session.get(Panel, account.panel_id) if account.panel_id else None)
    return _issue_out(issue, account, store, panel)
