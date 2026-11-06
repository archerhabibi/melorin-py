"""Admin API - panel operations (PasarGuard roadmap Phase 1): node health, reconciliation issues, discovered panel users.

Read endpoints are plain lists. Every write is an explicit admin decision, audited, and limited to the issue's own kind:
``ignore`` / ``resolve`` (any kind), ``fix_owner`` (owner_mismatch), ``archive_account`` (missing_on_panel), ``resync`` (re-check now).
Nothing here deletes anything on a panel, and orphans are only ever listed or ignored.
"""

import datetime as dt
import logging
import uuid

from fastapi import APIRouter
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from melorin.core import audit
from melorin.core.db import utcnow
from melorin.core.deps import AdminUser, Session
from melorin.core.errors import AppError, NotFound
from melorin.domain.order_state import VpnStatus
from melorin.kernel.models.stores import Store
from melorin.kernel.models.vpn import Panel, PanelNode, PanelOrphan, ReconciliationIssue, VpnAccount
from melorin.modules.vpn import issues as issue_svc
from melorin.modules.vpn import notices, reconcile
from melorin.modules.vpn.adapters.base import PanelError, supports
from melorin.modules.vpn.adapters.registry import build_adapter, seed_adapter

router = APIRouter(prefix="/admin", tags=["admin"])
log = logging.getLogger("melorin.admin.panel_ops")

ACTIONS = ("ignore", "resolve", "fix_owner", "archive_account", "resync")


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
    action: str = Field(pattern="^(ignore|resolve|fix_owner|archive_account|resync)$")
    reason: str | None = Field(default=None, max_length=300)


class OrphanOut(BaseModel):
    id: uuid.UUID
    panel_id: uuid.UUID
    panel_name: str | None = None
    username: str
    remote_status: str | None = None
    owner_username: str | None = None
    expire_at: dt.datetime | None = None
    traffic_limit_bytes: int = 0
    traffic_used_bytes: int = 0
    status: str
    note: str | None = None
    first_seen_at: dt.datetime | None = None
    last_seen_at: dt.datetime | None = None


class OrphanIgnoreIn(BaseModel):
    note: str | None = Field(default=None, max_length=300)


def allowed_actions(kind: str, status: str) -> list[str]:
    """What an admin may do with an issue. Closed issues take no action."""
    if status != issue_svc.OPEN:
        return []
    extra = {issue_svc.OWNER_MISMATCH: ["fix_owner"], issue_svc.MISSING: ["archive_account"]}.get(kind, [])
    return ["resync", *extra, "resolve", "ignore"]


# ------------------------------------------------------------------------------------------------------------------ nodes
@router.get("/panels/{panel_id}/nodes", response_model=PanelNodesOut)
async def panel_nodes(panel_id: uuid.UUID, _: AdminUser, session: Session):
    from melorin.modules.vpn.health import node_error_hint

    panel = await session.get(Panel, panel_id)
    if not panel:
        raise NotFound("پنل")
    rows = (
        await session.scalars(select(PanelNode).where(PanelNode.panel_id == panel_id, PanelNode.removed_at.is_(None)).order_by(PanelNode.name))
    ).all()
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
    q = (
        select(ReconciliationIssue, VpnAccount, Store, Panel)
        .join(VpnAccount, VpnAccount.id == ReconciliationIssue.vpn_account_id)
        .outerjoin(Store, Store.id == VpnAccount.store_id)
        .outerjoin(Panel, Panel.id == VpnAccount.panel_id)
    )
    if status:
        q = q.where(ReconciliationIssue.status == status)
    if kind:
        q = q.where(ReconciliationIssue.kind == kind)
    if panel_id:
        q = q.where(VpnAccount.panel_id == panel_id)
    total = await session.scalar(select(func.count()).select_from(q.subquery())) or 0
    rows = (await session.execute(q.order_by(ReconciliationIssue.last_seen_at.desc().nulls_last(), ReconciliationIssue.created_at.desc()).limit(limit).offset(offset))).all()
    return total, rows


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
        session, status=None if status in (None, "all") else status, kind=kind, panel_id=panel_id, limit=max(1, min(limit, 200)), offset=max(0, offset)
    )
    return {"total": total, "items": [_issue_out(i, a, s, p) for i, a, s, p in rows]}


@router.get("/reconciliation/summary")
async def reconciliation_summary(_: AdminUser, session: Session):
    by_kind = dict(
        (
            await session.execute(
                select(ReconciliationIssue.kind, func.count()).where(ReconciliationIssue.status == issue_svc.OPEN).group_by(ReconciliationIssue.kind)
            )
        ).all()
    )
    orphans = await session.scalar(select(func.count()).select_from(PanelOrphan).where(PanelOrphan.status == "open")) or 0
    oldest = await session.scalar(select(func.min(VpnAccount.last_synced_at)).where(VpnAccount.status.in_(("active", "suspended", "limited"))))
    return {"open": {k: int(by_kind.get(k, 0)) for k in issue_svc.KINDS}, "open_total": int(sum(by_kind.values())), "orphans_open": int(orphans), "oldest_sync_at": oldest}


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
    if body.action == "ignore":
        if not reason:
            raise AppError("REASON_REQUIRED", "برای نادیده گرفتن، دلیل را بنویسید.", 422)
        issue.status, issue.resolution, issue.resolved_at = issue_svc.IGNORED, f"ignored: {reason}"[:300], now
    elif body.action == "resolve":
        issue.status, issue.resolution, issue.resolved_at = issue_svc.RESOLVED, f"admin: {reason or 'resolved'}"[:300], now
    elif body.action == "archive_account":
        account.status, account.archived_at = VpnStatus.ARCHIVED, now
        issue.status, issue.resolution, issue.resolved_at = issue_svc.RESOLVED, f"archived: {reason or 'missing on panel'}"[:300], now
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
            if adapter is not None:
                try:
                    await adapter.close()
                except Exception:
                    log.warning("panel adapter close failed panel=%s", panel.id, exc_info=True)
        issue.status, issue.resolution, issue.resolved_at = issue_svc.RESOLVED, f"owner set to {expected}", now
    elif body.action == "resync":
        outcome = await reconcile.reconcile_account(session, account.id)
        await session.refresh(issue)
        audit.record(
            session, "reconciliation.resync", actor_id=admin.id, actor_type="admin", entity_type="vpn_account", entity_id=account.id,
            store_id=account.store_id, data={"issue": str(issue.id), "outcome": outcome},
        )
        await session.commit()
        store, panel = await session.get(Store, account.store_id), (await session.get(Panel, account.panel_id) if account.panel_id else None)
        return _issue_out(issue, account, store, panel)
    audit.record(
        session,
        f"reconciliation.{body.action}",
        actor_id=admin.id,
        actor_type="admin",
        entity_type="vpn_account",
        entity_id=account.id,
        store_id=account.store_id,
        data={"issue": str(issue.id), "kind": issue.kind, "reason": reason},
    )
    await session.commit()
    store, panel = await session.get(Store, account.store_id), (await session.get(Panel, account.panel_id) if account.panel_id else None)
    return _issue_out(issue, account, store, panel)


# ------------------------------------------------------------------------------------------------------------------ orphans
@router.get("/panel-orphans")
async def panel_orphans(_: AdminUser, session: Session, status: str | None = "open", panel_id: uuid.UUID | None = None, limit: int = 100, offset: int = 0):
    q = select(PanelOrphan, Panel.name).join(Panel, Panel.id == PanelOrphan.panel_id)
    if status and status != "all":
        q = q.where(PanelOrphan.status == status)
    if panel_id:
        q = q.where(PanelOrphan.panel_id == panel_id)
    total = await session.scalar(select(func.count()).select_from(q.subquery())) or 0
    rows = (await session.execute(q.order_by(PanelOrphan.last_seen_at.desc().nulls_last()).limit(max(1, min(limit, 500))).offset(max(0, offset)))).all()
    return {
        "total": total,
        "items": [
            OrphanOut(
                id=o.id, panel_id=o.panel_id, panel_name=name, username=o.username, remote_status=o.remote_status, owner_username=o.owner_username,
                expire_at=o.expire_at, traffic_limit_bytes=int(o.traffic_limit_bytes or 0), traffic_used_bytes=int(o.traffic_used_bytes or 0),
                status=o.status, note=o.note, first_seen_at=o.first_seen_at, last_seen_at=o.last_seen_at,
            )
            for o, name in rows
        ],
    }


@router.post("/panel-orphans/{orphan_id}/ignore", response_model=OrphanOut)
async def ignore_orphan(orphan_id: uuid.UUID, body: OrphanIgnoreIn, admin: AdminUser, session: Session):
    """\"This panel user is not ours and that is fine\" (a manual account, a test). It is kept, only hidden from the open list."""
    o = await session.get(PanelOrphan, orphan_id)
    if not o:
        raise NotFound("کاربر پنل")
    o.status, o.note = "ignored", (body.note or "").strip() or None
    audit.record(session, "panel_orphan.ignored", actor_id=admin.id, actor_type="admin", entity_type="panel_orphan", entity_id=o.id, data={"username": o.username, "panel_id": str(o.panel_id)})
    await session.commit()
    return OrphanOut(
        id=o.id, panel_id=o.panel_id, username=o.username, remote_status=o.remote_status, owner_username=o.owner_username, expire_at=o.expire_at,
        traffic_limit_bytes=int(o.traffic_limit_bytes or 0), traffic_used_bytes=int(o.traffic_used_bytes or 0), status=o.status, note=o.note,
        first_seen_at=o.first_seen_at, last_seen_at=o.last_seen_at,
    )


# ------------------------------------------------------------------------------------------- per-store notice settings (PG-06)
class NoticeSettingsIn(BaseModel):
    traffic_low_levels: list[int] = Field(max_length=notices.MAX_LEVELS, description="percents (1-99) at which the customer is warned; [] = no warnings")


class NoticeSettingsOut(BaseModel):
    store_id: uuid.UUID
    traffic_low_levels: list[int]
    is_default: bool
    default_levels: list[int] = list(notices.TRAFFIC_LOW_LEVELS)


def _notice_out(store: Store) -> NoticeSettingsOut:
    custom = bool(store.vpn_notice_settings) and "traffic_low_levels" in store.vpn_notice_settings
    return NoticeSettingsOut(store_id=store.id, traffic_low_levels=list(notices.levels_for_store(store.vpn_notice_settings)), is_default=not custom)


@router.get("/stores/{store_id}/vpn-notices", response_model=NoticeSettingsOut)
async def get_store_vpn_notices(store_id: uuid.UUID, _: AdminUser, session: Session):
    store = await session.get(Store, store_id)
    if not store:
        raise NotFound("فروشگاه")
    return _notice_out(store)


@router.put("/stores/{store_id}/vpn-notices", response_model=NoticeSettingsOut)
async def put_store_vpn_notices(store_id: uuid.UUID, body: NoticeSettingsIn, admin: AdminUser, session: Session):
    """Set when THIS store's customers are warned about low traffic. Takes effect at the next sync; a level already warned stays warned."""
    store = await session.get(Store, store_id)
    if not store:
        raise NotFound("فروشگاه")
    try:
        levels = notices.normalize_levels(body.traffic_low_levels)
    except ValueError as exc:
        raise AppError("INVALID_NOTICE_LEVELS", "آستانه‌های هشدار حجم نامعتبر است", status=422, details={"reason": str(exc)}) from exc
    before = list(notices.levels_for_store(store.vpn_notice_settings))
    store.vpn_notice_settings = {**(store.vpn_notice_settings or {}), "traffic_low_levels": list(levels)}
    audit.record(
        session, "store.vpn_notices.updated", actor_id=admin.id, actor_type="admin", entity_type="store", entity_id=store.id,
        store_id=store.id, data={"before": before, "after": list(levels)},
    )
    await session.commit()
    return _notice_out(store)


@router.delete("/stores/{store_id}/vpn-notices", response_model=NoticeSettingsOut)
async def reset_store_vpn_notices(store_id: uuid.UUID, admin: AdminUser, session: Session):
    """Back to the platform defaults."""
    store = await session.get(Store, store_id)
    if not store:
        raise NotFound("فروشگاه")
    store.vpn_notice_settings = None
    audit.record(session, "store.vpn_notices.reset", actor_id=admin.id, actor_type="admin", entity_type="store", entity_id=store.id, store_id=store.id, data={})
    await session.commit()
    return _notice_out(store)
