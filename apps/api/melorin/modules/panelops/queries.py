"""Read queries behind the admin panel screens (audit T11): the routers ask, this module selects.

Moved out of ``modules/admin/panel_*.py`` unchanged so those routers hold no SQL (``tests/test_router_sql_guard.py``). Reads only; every
write stays with the service that owns the rule.
"""

from __future__ import annotations

import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from melorin.kernel.models.stores import Store
from melorin.kernel.models.vpn import BulkOperation, Panel, PanelAdmin, PanelEvent, PanelNode, PanelOrphan, ReconciliationIssue, VpnAccount


async def live_nodes(session: AsyncSession, panel_id: uuid.UUID) -> list[PanelNode]:
    """The panel's nodes that still exist there, by name."""
    return list(
        (
            await session.scalars(
                select(PanelNode).where(PanelNode.panel_id == panel_id, PanelNode.removed_at.is_(None)).order_by(PanelNode.name)
            )
        ).all()
    )


async def node_status_counts(session: AsyncSession, panel_id: uuid.UUID) -> list[tuple[str, int]]:
    return list(
        (
            await session.execute(
                select(PanelNode.status, func.count())
                .where(PanelNode.panel_id == panel_id, PanelNode.removed_at.is_(None))
                .group_by(PanelNode.status)
            )
        ).all()
    )


async def issue_rows(session: AsyncSession, *, status, kind, panel_id, limit, offset):
    """``(total, [(issue, account, store, panel), ...])``, newest activity first."""
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
    rows = (
        await session.execute(
            q.order_by(ReconciliationIssue.last_seen_at.desc().nulls_last(), ReconciliationIssue.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
    ).all()
    return total, rows


async def reconciliation_counts(session: AsyncSession, open_status: str) -> tuple[dict, int, int, object]:
    """``(open issues by kind, open orphans, manual orphans, oldest last_synced_at of a live account)``."""
    by_kind = dict(
        (
            await session.execute(
                select(ReconciliationIssue.kind, func.count())
                .where(ReconciliationIssue.status == open_status)
                .group_by(ReconciliationIssue.kind)
            )
        ).all()
    )
    orphans = await session.scalar(select(func.count()).select_from(PanelOrphan).where(PanelOrphan.status == "open")) or 0
    manual = await session.scalar(select(func.count()).select_from(PanelOrphan).where(PanelOrphan.status == "manual")) or 0
    oldest = await session.scalar(
        select(func.min(VpnAccount.last_synced_at)).where(VpnAccount.status.in_(("active", "suspended", "limited")))
    )
    return by_kind, int(orphans), int(manual), oldest


async def username_in_use(session: AsyncSession, username: str, *, except_account_id: uuid.UUID) -> bool:
    return bool(await session.scalar(select(VpnAccount.id).where(VpnAccount.username == username, VpnAccount.id != except_account_id)))


async def orphan_rows(session: AsyncSession, *, status: str | None, panel_id: uuid.UUID | None, limit: int, offset: int):
    """``(total, [(orphan, panel_name), ...])``; ``status`` ``None`` / ``"all"`` means every status."""
    q = select(PanelOrphan, Panel.name).join(Panel, Panel.id == PanelOrphan.panel_id)
    if status and status != "all":
        q = q.where(PanelOrphan.status == status)
    if panel_id:
        q = q.where(PanelOrphan.panel_id == panel_id)
    total = await session.scalar(select(func.count()).select_from(q.subquery())) or 0
    rows = (await session.execute(q.order_by(PanelOrphan.last_seen_at.desc().nulls_last()).limit(limit).offset(offset))).all()
    return total, rows


async def event_rows(session: AsyncSession, panel_id: uuid.UUID, *, status, action, username, limit: int, offset: int):
    q = select(PanelEvent).where(PanelEvent.panel_id == panel_id)
    if status:
        q = q.where(PanelEvent.status == status)
    if action:
        q = q.where(PanelEvent.action == action)
    if username:
        q = q.where(PanelEvent.username == username.strip())
    total = await session.scalar(select(func.count()).select_from(q.subquery())) or 0
    rows = (await session.scalars(q.order_by(PanelEvent.received_at.desc()).limit(limit).offset(offset))).all()
    return total, rows


async def bulk_operation_rows(session: AsyncSession, *, status, panel_id, limit: int, offset: int):
    q = select(BulkOperation)
    if status:
        q = q.where(BulkOperation.status == status)
    if panel_id:
        q = q.where(BulkOperation.panel_id == panel_id)
    total = await session.scalar(select(func.count()).select_from(q.subquery()))
    rows = (await session.scalars(q.order_by(BulkOperation.created_at.desc()).limit(limit).offset(offset))).all()
    return total or 0, rows


async def store_admin_rows(session: AsyncSession, panel_id: uuid.UUID | None):
    q = select(PanelAdmin, Store, Panel).join(Store, Store.id == PanelAdmin.store_id).join(Panel, Panel.id == PanelAdmin.panel_id)
    if panel_id:
        q = q.where(PanelAdmin.panel_id == panel_id)
    return (await session.execute(q.order_by(Store.name))).all()


async def pasarguard_panels(session: AsyncSession, panel_id: uuid.UUID | None) -> list[Panel]:
    q = select(Panel).where(Panel.kind == "pasarguard", Panel.is_enabled.is_(True))
    if panel_id:
        q = q.where(Panel.id == panel_id)
    return list((await session.scalars(q)).all())
