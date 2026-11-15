"""Bulk panel operations, execution side: claim one confirmed operation, run it in bounded time, resume after a crash.

The lifecycle (preview, confirm, cancel, resume, reporting) stays in :mod:`melorin.modules.panelops.bulk`; this module is what the worker runs.
"""

from __future__ import annotations

import datetime as dt
import logging
import uuid

from sqlalchemy import func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from melorin.core import audit
from melorin.core.db import utcnow
from melorin.core.errors import AppError
from melorin.domain.order_state import VpnSource, VpnStatus, set_vpn_status
from melorin.kernel.models.vpn import BulkOperation, BulkOperationItem, Panel, VpnAccount
from melorin.modules.vpn_accounts import sync
from melorin.modules.panel_integrations.adapters.base import ErrorKind, PanelError, supports
from melorin.modules.panel_integrations.adapters.registry import build_adapter

from melorin.modules.panelops.bulk import (
    CAPABILITY,
    CHUNK,
    LEASE,
    MAX_ATTEMPTS,
    OPEN,
    PANEL_ACTIONS,
    PER_ACCOUNT_BATCH,
    SKEW,
    _counts,
    expire_stale_previews,
    get,
)

log = logging.getLogger("melorin.panelops.bulk_runner")


async def claim_next(session: AsyncSession, now: dt.datetime | None = None) -> uuid.UUID | None:
    """Pick one runnable operation and take its lease atomically. ``None`` when there is nothing to do."""
    now = now or utcnow()
    candidates = (
        await session.scalars(
            select(BulkOperation.id)
            .where(BulkOperation.status.in_(OPEN), or_(BulkOperation.lease_until.is_(None), BulkOperation.lease_until < now))
            .order_by(BulkOperation.created_at)
            .limit(5)
        )
    ).all()
    for op_id in candidates:
        panel_id = await session.scalar(select(BulkOperation.panel_id).where(BulkOperation.id == op_id))
        other = await session.scalar(
            select(func.count())
            .select_from(BulkOperation)
            .where(BulkOperation.panel_id == panel_id, BulkOperation.id != op_id, BulkOperation.lease_until >= now)
        )
        if other:  # one runner per panel: another operation holds a live lease there
            continue
        res = await session.execute(
            update(BulkOperation)
            .where(
                BulkOperation.id == op_id,
                BulkOperation.status.in_(OPEN),
                or_(BulkOperation.lease_until.is_(None), BulkOperation.lease_until < now),
            )
            .values(lease_until=now + LEASE, status="running")
        )
        await session.commit()
        if res.rowcount:
            return op_id
    return None


async def _pending(session: AsyncSession, op: BulkOperation, limit: int) -> list[BulkOperationItem]:
    return list(
        (
            await session.scalars(
                select(BulkOperationItem)
                .where(BulkOperationItem.operation_id == op.id, BulkOperationItem.status == "pending")
                .order_by(BulkOperationItem.created_at, BulkOperationItem.id)
                .limit(limit)
            )
        ).all()
    )


def _mark(item: BulkOperationItem, status: str, error: str | None = None) -> None:
    item.status, item.error = status, (error[:300] if error else None)
    if status != "pending":
        item.done_at = utcnow()


def _mirror_panel_action(kind: str, account: VpnAccount) -> None:
    """Reflect an idempotent panel action on the account right away; ``last_synced_at=None`` puts it first in line for reconcile v2."""
    if kind == "disable":
        set_vpn_status(account, VpnStatus.SUSPENDED, source=VpnSource.BULK)
    elif kind == "enable":
        set_vpn_status(account, VpnStatus.ACTIVE, source=VpnSource.BULK)
    elif kind == "reset_usage" and account.status == VpnStatus.LIMITED:  # usage itself is the panel's: only the status bucket moves
        set_vpn_status(account, VpnStatus.ACTIVE, source=VpnSource.BULK)
    account.last_synced_at = None


async def _run_panel_action(session: AsyncSession, op: BulkOperation, adapter, budget_end: float, clock) -> bool:
    """Chunked idempotent action. Returns False when the run should stop (transient/unknown error: retried next tick)."""
    while clock() < budget_end:
        batch = await _pending(session, op, CHUNK)
        if not batch:
            return True
        await session.refresh(op)
        if op.status == "cancelled":
            return False
        refs = [i.panel_ref for i in batch if i.panel_ref]
        try:
            if refs:
                await adapter.bulk_users_action(refs, op.kind)
        except PanelError as exc:
            for i in batch:
                i.attempts = int(i.attempts or 0) + 1
                if exc.kind == ErrorKind.PERMANENT or i.attempts >= MAX_ATTEMPTS:
                    _mark(i, "failed", exc.message)
            op.error = exc.message[:300]
            await session.commit()
            if exc.kind == ErrorKind.PERMANENT:
                continue  # these items are failed (resumable); carry on with the next chunk
            return False  # transient/unknown: stop now, the same chunk is safe to resend later
        accounts = {
            a.id: a for a in (await session.scalars(select(VpnAccount).where(VpnAccount.id.in_([i.vpn_account_id for i in batch])))).all()
        }
        for i in batch:
            _mark(i, "done" if i.panel_ref else "failed", None if i.panel_ref else "no panel reference")
            account = accounts.get(i.vpn_account_id)
            if account and i.panel_ref:
                _mirror_panel_action(op.kind, account)
        op.lease_until = utcnow() + LEASE
        await session.commit()
    return True


def _expire_matches(a: dt.datetime | None, b: dt.datetime | None) -> bool:
    return a is not None and b is not None and abs(a - b) <= SKEW


async def _apply_relative(session: AsyncSession, op: BulkOperation, item: BulkOperationItem, account: VpnAccount, adapter) -> str:
    """One account of extend_days / add_traffic. Returns ``done | skipped | pending`` (pending = transient, retry later)."""
    target = item.target or {}
    try:
        remote = await adapter.get_account(account.username)
        if remote is None:
            _mark(item, "failed", "missing on panel")
            return "failed"
        if op.kind == "extend_days":
            want, base = dt.datetime.fromisoformat(target["expire_at"]), dt.datetime.fromisoformat(target["base_expire_at"])
            have = sync.aware(remote.expire_at)
            if _expire_matches(have, want):
                _mark(item, "done")  # an earlier attempt already landed (e.g. the answer was lost): never add twice
                await sync.apply_remote(session, account, remote, notify=False)
                sync.record_sale(account, remote.expire_at, remote.traffic_limit_bytes)
                return "done"
            if not _expire_matches(have, base):
                _mark(item, "skipped", "changed on the panel since the preview")
                return "skipped"
            pa = await adapter.extend_account(account.username, expire_at=want, traffic_bytes=int(remote.traffic_limit_bytes or 0))
        else:
            want_t, base_t = int(target["traffic_bytes"]), int(target["base_traffic_bytes"])
            have_t = int(remote.traffic_limit_bytes or 0)
            if have_t == want_t:
                _mark(item, "done")
                await sync.apply_remote(session, account, remote, notify=False)
                sync.record_sale(account, remote.expire_at, remote.traffic_limit_bytes)
                return "done"
            if have_t != base_t:
                _mark(item, "skipped", "changed on the panel since the preview")
                return "skipped"
            pa = await adapter.extend_account(account.username, expire_at=sync.aware(remote.expire_at), traffic_bytes=want_t)
    except PanelError as exc:
        item.attempts = int(item.attempts or 0) + 1
        item.error = exc.message[:300]
        if exc.kind == ErrorKind.PERMANENT or item.attempts >= MAX_ATTEMPTS:
            _mark(item, "failed", exc.message)
            return "failed"
        return "pending"
    await sync.apply_remote(session, account, pa, notify=False)
    sync.record_sale(account, pa.expire_at, pa.traffic_limit_bytes)  # R10: the entitlement is what the act applied
    _mark(item, "done")
    return "done"


async def _run_relative(session: AsyncSession, op: BulkOperation, adapter, budget_end: float, clock) -> bool:
    while clock() < budget_end:
        batch = await _pending(session, op, PER_ACCOUNT_BATCH)
        if not batch:
            return True
        await session.refresh(op)
        if op.status == "cancelled":
            return False
        accounts = {
            a.id: a for a in (await session.scalars(select(VpnAccount).where(VpnAccount.id.in_([i.vpn_account_id for i in batch])))).all()
        }
        stop = False
        for item in batch:
            account = accounts.get(item.vpn_account_id)
            if account is None:
                _mark(item, "failed", "account is gone")
                continue
            outcome = await _apply_relative(session, op, item, account, adapter)
            if outcome == "pending":
                stop = True  # the panel is struggling: stop this tick, items stay pending
                break
        op.lease_until = utcnow() + LEASE
        await session.commit()
        if stop:
            return False
    return True


async def execute(session: AsyncSession, op_id: uuid.UUID, *, budget_seconds: float = 45.0, clock=None) -> BulkOperation:
    """Run one claimed operation for up to ``budget_seconds`` (the worker calls this every tick until it is finished)."""
    import time

    clock = clock or time.monotonic
    budget_end = clock() + budget_seconds
    op = await get(session, op_id)
    if op.status not in OPEN:
        return op
    op.status = "running"
    op.started_at = op.started_at or utcnow()
    panel = await session.get(Panel, op.panel_id)
    adapter = None
    try:
        adapter = build_adapter(panel)
        needed = CAPABILITY[op.kind]
        if not supports(adapter, needed):
            raise PanelError(ErrorKind.PERMANENT, f"panel capability '{needed}' is not available for this connection")
        if op.kind in PANEL_ACTIONS:
            await _run_panel_action(session, op, adapter, budget_end, clock)
        else:
            await _run_relative(session, op, adapter, budget_end, clock)
    except PanelError as exc:
        op.error = exc.message[:300]
        if exc.kind == ErrorKind.PERMANENT:
            await session.execute(
                update(BulkOperationItem)
                .where(BulkOperationItem.operation_id == op.id, BulkOperationItem.status == "pending")
                .values(status="failed", error=exc.message[:300])
            )
    except AppError as exc:  # e.g. TLS policy: nothing was sent
        op.error = exc.message[:300]
        await session.execute(
            update(BulkOperationItem)
            .where(BulkOperationItem.operation_id == op.id, BulkOperationItem.status == "pending")
            .values(status="failed", error=exc.message[:300])
        )
    finally:
        if adapter is not None:
            close = getattr(adapter, "close", None)
            if callable(close):
                try:
                    res = close()
                    if hasattr(res, "__await__"):
                        await res
                except Exception:
                    log.warning("bulk: adapter close failed op=%s", op.id, exc_info=True)
    await session.refresh(op)
    if op.status == "cancelled":
        await session.commit()
        return op
    counts = await _counts(session, op)
    op.succeeded, op.failed = counts.get("done", 0), counts.get("failed", 0)
    pre_skipped = sum(((op.selection or {}).get("skipped") or {}).values())
    op.skipped = pre_skipped + counts.get("skipped", 0)
    if counts.get("pending", 0) == 0:
        op.status = "done" if op.failed == 0 else ("failed" if op.succeeded == 0 and counts.get("skipped", 0) == 0 else "partial")
        op.finished_at, op.lease_until = utcnow(), None
        audit.record(
            session,
            "bulk.finished",
            actor_type="system",
            entity_type="bulk_operation",
            entity_id=op.id,
            store_id=op.store_id,
            data={"kind": op.kind, "status": op.status, "succeeded": op.succeeded, "failed": op.failed, "skipped": op.skipped},
        )
    else:
        op.lease_until = None
        op.status = "confirmed"  # time budget used up or the panel struggled: the next tick picks it up again
    await session.commit()
    return op


async def run_next(session_factory, *, budget_seconds: float = 45.0) -> BulkOperation | None:
    """Worker entry point: expire stale previews, claim one runnable operation, run it for a bounded time."""
    async with session_factory() as s:
        await expire_stale_previews(s)
        op_id = await claim_next(s)
        if op_id is None:
            return None
        return await execute(s, op_id, budget_seconds=budget_seconds)


__all__ = ["claim_next", "execute", "run_next"]
