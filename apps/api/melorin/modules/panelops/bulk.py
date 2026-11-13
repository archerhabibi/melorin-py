"""Bulk operations and outage compensation (PG-11).

Flow: ``preview`` (freeze the selection into per-account items, nothing is sent) -> ``confirm`` (the admin types the exact count) ->
``execute`` (the worker runs it in chunks under a lease) -> report, ``resume`` after a partial run, ``cancel`` any time before the end.

Why it is safe to repeat:

* ``disable | enable | reset_usage | rotate_links`` use the panel's bulk endpoints over panel user ids: each is idempotent
  (disabling a disabled user changes nothing), so a timeout (``ErrorKind.UNKNOWN``) is simply retried.
* ``extend_days | add_traffic`` never use the panel's RELATIVE bulk endpoints (a repeat would add twice). Each item carries an
  ABSOLUTE target computed once at preview time. At run time the panel is read first: already at the target = done, still at the
  preview value = write the target, anything else = the account changed meanwhile, so it is skipped instead of overwritten.
* One runner per panel at a time (``lease_until``); a crashed runner's lease simply expires.

Nothing here deletes anything. Accounts are only ever disabled/enabled, reset, re-linked or extended.
"""

from __future__ import annotations

import datetime as dt
import logging
import uuid
from dataclasses import dataclass, field

from sqlalchemy import func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from melorin.modules.vpn.adapters import providers
from melorin.core import audit
from melorin.core.db import utcnow
from melorin.core.errors import AppError, NotFound
from melorin.domain.order_state import VpnStatus
from melorin.kernel.models.stores import Store
from melorin.kernel.models.vpn import BulkOperation, BulkOperationItem, Panel, VpnAccount
from melorin.modules.vpn import sync
from melorin.modules.vpn.adapters.base import ErrorKind, PanelError, supports
from melorin.modules.vpn.adapters.registry import build_adapter

log = logging.getLogger("melorin.panelops.bulk")

GIB = 1024**3
MAX_ITEMS = 5000  # one operation never touches more accounts than this
PREVIEW_TTL = dt.timedelta(minutes=15)
LEASE = dt.timedelta(minutes=5)
CHUNK = 200  # panel bulk endpoints (same cap as ``bulk_set_owner``)
PER_ACCOUNT_BATCH = 20  # extend/add_traffic: one panel read + write per account, committed every 20
MAX_ATTEMPTS = 5
MAX_DAYS = 90
MAX_GB = 512
SAMPLE = 10
SKEW = dt.timedelta(seconds=2)  # panel clocks round to the second

PANEL_ACTIONS = ("disable", "enable", "reset_usage", "rotate_links")
RELATIVE_KINDS = ("extend_days", "add_traffic")
KINDS = PANEL_ACTIONS + RELATIVE_KINDS
KIND_LABELS = {
    "disable": "غیرفعال‌سازی گروهی",
    "enable": "فعال‌سازی گروهی",
    "reset_usage": "ریست ترافیک",
    "rotate_links": "چرخش لینک اشتراک",
    "extend_days": "جبران زمان (افزودن روز)",
    "add_traffic": "جبران حجم (افزودن گیگابایت)",
}
# kind -> Melorin statuses it applies to
ELIGIBLE = {
    "disable": (VpnStatus.ACTIVE,),
    "enable": (VpnStatus.SUSPENDED,),
    "reset_usage": (VpnStatus.ACTIVE, VpnStatus.LIMITED),
    "rotate_links": (VpnStatus.ACTIVE, VpnStatus.SUSPENDED, VpnStatus.LIMITED),
    "extend_days": (VpnStatus.ACTIVE, VpnStatus.SUSPENDED, VpnStatus.LIMITED),
    "add_traffic": (VpnStatus.ACTIVE, VpnStatus.SUSPENDED, VpnStatus.LIMITED),
}
OPEN = ("confirmed", "running")
FINAL = ("done", "partial", "failed", "cancelled", "expired")
# the capability that must be live on the panel connection for each kind
CAPABILITY = {k: "bulk_actions" for k in PANEL_ACTIONS} | {"extend_days": "extend", "add_traffic": "extend"}


@dataclass
class Selection:
    """Which accounts. ``panel_id`` is required: an operation never spans two panels."""

    panel_id: uuid.UUID
    store_id: uuid.UUID | None = None
    server_id: uuid.UUID | None = None
    statuses: list[str] = field(default_factory=list)  # narrows ELIGIBLE (never widens it)
    expiring_within_days: int | None = None
    usernames: list[str] = field(default_factory=list)

    def to_json(self) -> dict:
        return {
            "panel_id": str(self.panel_id),
            "store_id": str(self.store_id) if self.store_id else None,
            "server_id": str(self.server_id) if self.server_id else None,
            "statuses": list(self.statuses),
            "expiring_within_days": self.expiring_within_days,
            "usernames": list(self.usernames)[:50],
            "usernames_count": len(self.usernames),
        }


# ------------------------------------------------------------------------------------------------------------------ planning
def validate_params(kind: str, params: dict | None) -> dict:
    if kind not in KINDS:
        raise AppError("BAD_BULK_KIND", "نوع عملیات نامعتبر است.", 400)
    params = dict(params or {})
    if kind == "extend_days":
        days = int(params.get("days") or 0)
        if not 1 <= days <= MAX_DAYS:
            raise AppError("BAD_BULK_PARAMS", f"تعداد روز باید بین ۱ تا {MAX_DAYS} باشد.", 400)
        return {"days": days}
    if kind == "add_traffic":
        gb = int(params.get("gb") or 0)
        if not 1 <= gb <= MAX_GB:
            raise AppError("BAD_BULK_PARAMS", f"حجم باید بین ۱ تا {MAX_GB} گیگابایت باشد.", 400)
        return {"gb": gb}
    return {}


def _skip_reason(kind: str, account: VpnAccount, params: dict, now: dt.datetime) -> str | None:
    """Why this (status-eligible) account cannot take the operation; ``None`` = it can."""
    expires = sync.aware(account.sold_expires_at)
    if kind == "enable" and expires is not None and expires <= now:
        return "expired"
    if kind == "extend_days" and expires is None:
        return "unlimited_time"
    if kind == "add_traffic" and int(account.sold_traffic_bytes or 0) == 0:
        return "unlimited_traffic"
    return None


def _target(kind: str, account: VpnAccount, params: dict, now: dt.datetime) -> dict | None:
    """The ABSOLUTE value to write for a relative kind, from the SOLD entitlement; ``base`` is what must still be on the panel (else the item is skipped)."""
    if kind == "extend_days":
        base = sync.aware(account.sold_expires_at)
        new = max(base, now) + dt.timedelta(days=params["days"])
        return {"base_expire_at": base.isoformat(), "expire_at": new.isoformat()}
    if kind == "add_traffic":
        base = int(account.sold_traffic_bytes or 0)
        return {"base_traffic_bytes": base, "traffic_bytes": base + params["gb"] * GIB}
    return None


async def _candidates(session: AsyncSession, kind: str, sel: Selection, now: dt.datetime) -> list[VpnAccount]:
    allowed = [s.value for s in ELIGIBLE[kind]]
    if sel.statuses:
        allowed = [s for s in allowed if s in set(sel.statuses)]
    q = select(VpnAccount).where(
        VpnAccount.panel_id == sel.panel_id,
        VpnAccount.archived_at.is_(None),
        VpnAccount.panel_ref.is_not(None),
        VpnAccount.status.in_(allowed or ["-"]),
    )
    if sel.store_id:
        q = q.where(VpnAccount.store_id == sel.store_id)
    if sel.server_id:
        q = q.where(VpnAccount.server_id == sel.server_id)
    if sel.usernames:
        q = q.where(VpnAccount.username.in_(sel.usernames[:MAX_ITEMS]))
    if sel.expiring_within_days is not None:
        q = q.where(
            VpnAccount.sold_expires_at.is_not(None), VpnAccount.sold_expires_at <= now + dt.timedelta(days=int(sel.expiring_within_days))
        )
    q = q.order_by(VpnAccount.created_at, VpnAccount.id).limit(MAX_ITEMS + 1)
    return list((await session.scalars(q)).all())


async def preview(
    session: AsyncSession,
    *,
    kind: str,
    selection: Selection,
    params: dict | None = None,
    reason: str,
    actor_id: uuid.UUID | None,
    origin: str = "admin",
    auto_confirm: bool = False,
) -> BulkOperation:
    """Freeze the selection into items and return the operation (status ``previewed``). Sends nothing to any panel."""
    reason = (reason or "").strip()
    if len(reason) < 3 and origin == "admin":
        raise AppError("REASON_REQUIRED", "برای عملیات گروهی دلیل را بنویسید.", 400)
    params = validate_params(kind, params)
    panel = await session.get(Panel, selection.panel_id)
    if not panel:
        raise NotFound("پنل")
    if not providers.supports(panel.kind, "panel_ops"):
        raise AppError("BULK_NOT_SUPPORTED", "عملیات گروهی فعلاً فقط برای پنل پاسارگارد است.", 409)
    now = utcnow()
    accounts = await _candidates(session, kind, selection, now)
    if len(accounts) > MAX_ITEMS:
        raise AppError("BULK_TOO_MANY", f"حداکثر {MAX_ITEMS} اکانت در هر عملیات؛ انتخاب را محدودتر کنید.", 409)
    skipped: dict[str, int] = {}
    items: list[BulkOperationItem] = []
    op = BulkOperation(
        panel_id=panel.id,
        store_id=selection.store_id,
        kind=kind,
        params=params,
        selection=selection.to_json(),
        reason=reason[:300] or None,
        origin=origin,
        status="previewed",
        created_by=actor_id,
        expires_at=now + PREVIEW_TTL,
    )
    session.add(op)
    await session.flush()
    for a in accounts:
        why = _skip_reason(kind, a, params, now)
        if why:
            skipped[why] = skipped.get(why, 0) + 1
            continue
        items.append(
            BulkOperationItem(
                operation_id=op.id, vpn_account_id=a.id, username=a.username, panel_ref=a.panel_ref, target=_target(kind, a, params, now)
            )
        )
    if not items:
        await session.rollback()
        raise AppError("BULK_EMPTY", "هیچ اکانتِ مناسبی برای این عملیات پیدا نشد.", 409, {"skipped": skipped})
    session.add_all(items)
    op.total = len(items)
    op.skipped = sum(skipped.values())
    op.sample = [i.username for i in items[:SAMPLE]]
    op.selection = {**op.selection, "skipped": skipped}
    audit.record(
        session,
        "bulk.previewed",
        actor_id=actor_id,
        entity_type="bulk_operation",
        entity_id=op.id,
        store_id=selection.store_id,
        data={"kind": kind, "params": params, "total": op.total, "skipped": skipped, "reason": op.reason, "origin": origin},
    )
    if auto_confirm:
        _mark_confirmed(op, now)
    await session.commit()
    return op


# ------------------------------------------------------------------------------------------------------------------ lifecycle
def _mark_confirmed(op: BulkOperation, now: dt.datetime) -> None:
    op.status, op.confirmed_at, op.expires_at = "confirmed", now, None


async def get(session: AsyncSession, op_id: uuid.UUID) -> BulkOperation:
    op = await session.get(BulkOperation, op_id)
    if not op:
        raise NotFound("عملیات گروهی")
    return op


async def confirm(session: AsyncSession, op_id: uuid.UUID, *, count: int, actor_id: uuid.UUID | None) -> BulkOperation:
    """The admin types the exact number of accounts; a wrong number (or a stale preview) confirms nothing."""
    op = await get(session, op_id)
    now = utcnow()
    if op.status != "previewed":
        raise AppError("BULK_NOT_PREVIEWED", "این عملیات قبلاً تأیید یا لغو شده است.", 409)
    if op.expires_at and sync.aware(op.expires_at) <= now:
        op.status = "expired"
        await session.commit()
        raise AppError("BULK_PREVIEW_EXPIRED", "پیش‌نمایش منقضی شده؛ دوباره پیش‌نمایش بگیرید.", 409)
    if int(count) != int(op.total):
        raise AppError("BULK_COUNT_MISMATCH", f"تعداد تأییدشده با تعداد اکانت‌ها ({op.total}) یکی نیست.", 409)
    busy = await session.scalar(
        select(func.count()).select_from(BulkOperation).where(BulkOperation.panel_id == op.panel_id, BulkOperation.status.in_(OPEN))
    )
    if busy:
        raise AppError("BULK_BUSY", "عملیات گروهی دیگری روی این پنل در حال اجراست؛ صبر کنید.", 409)
    _mark_confirmed(op, now)
    audit.record(
        session,
        "bulk.confirmed",
        actor_id=actor_id,
        entity_type="bulk_operation",
        entity_id=op.id,
        store_id=op.store_id,
        data={"kind": op.kind, "total": op.total},
    )
    await session.commit()
    return op


async def cancel(session: AsyncSession, op_id: uuid.UUID, *, actor_id: uuid.UUID | None) -> BulkOperation:
    op = await get(session, op_id)
    if op.status in FINAL:
        raise AppError("BULK_FINISHED", "این عملیات تمام شده است.", 409)
    op.status, op.finished_at, op.lease_until = "cancelled", utcnow(), None
    audit.record(
        session,
        "bulk.cancelled",
        actor_id=actor_id,
        entity_type="bulk_operation",
        entity_id=op.id,
        store_id=op.store_id,
        data={"kind": op.kind, "done": op.succeeded},
    )
    await session.commit()
    return op


async def resume(session: AsyncSession, op_id: uuid.UUID, *, actor_id: uuid.UUID | None) -> BulkOperation:
    """Retry what is left after a ``partial`` run: failed items go back to pending (attempts reset); done items are never repeated."""
    op = await get(session, op_id)
    if op.status not in ("partial", "failed"):
        raise AppError("BULK_NOT_RESUMABLE", "فقط عملیات ناقص یا ناموفق قابل ازسرگیری است.", 409)
    await session.execute(
        update(BulkOperationItem)
        .where(BulkOperationItem.operation_id == op.id, BulkOperationItem.status == "failed")
        .values(status="pending", attempts=0, error=None)
    )
    op.status, op.error, op.finished_at = "confirmed", None, None
    audit.record(
        session,
        "bulk.resumed",
        actor_id=actor_id,
        entity_type="bulk_operation",
        entity_id=op.id,
        store_id=op.store_id,
        data={"kind": op.kind},
    )
    await session.commit()
    return op


async def expire_stale_previews(session: AsyncSession, now: dt.datetime | None = None) -> int:
    now = now or utcnow()
    res = await session.execute(
        update(BulkOperation).where(BulkOperation.status == "previewed", BulkOperation.expires_at < now).values(status="expired")
    )
    await session.commit()
    return res.rowcount or 0


# ------------------------------------------------------------------------------------------------------------------ execution
async def _counts(session: AsyncSession, op: BulkOperation) -> dict[str, int]:
    rows = (
        await session.execute(
            select(BulkOperationItem.status, func.count()).where(BulkOperationItem.operation_id == op.id).group_by(BulkOperationItem.status)
        )
    ).all()
    return {status: n for status, n in rows}


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
        account.status = VpnStatus.SUSPENDED
    elif kind == "enable":
        account.status = VpnStatus.ACTIVE
    elif kind == "reset_usage" and account.status == VpnStatus.LIMITED:  # usage itself is the panel's: only the status bucket moves
        account.status = VpnStatus.ACTIVE
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
            want, base_t = int(target["traffic_bytes"]), int(target["base_traffic_bytes"])
            have_t = int(remote.traffic_limit_bytes or 0)
            if have_t == want:
                _mark(item, "done")
                await sync.apply_remote(session, account, remote, notify=False)
                sync.record_sale(account, remote.expire_at, remote.traffic_limit_bytes)
                return "done"
            if have_t != base_t:
                _mark(item, "skipped", "changed on the panel since the preview")
                return "skipped"
            pa = await adapter.extend_account(account.username, expire_at=sync.aware(remote.expire_at), traffic_bytes=want)
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


# ------------------------------------------------------------------------------------------------------------------ reporting
def item_out(i: BulkOperationItem) -> dict:
    return {"username": i.username, "status": i.status, "attempts": i.attempts, "error": i.error, "done_at": i.done_at}


async def items_page(session: AsyncSession, op_id: uuid.UUID, *, status: str | None, limit: int, offset: int) -> list[BulkOperationItem]:
    q = select(BulkOperationItem).where(BulkOperationItem.operation_id == op_id)
    if status:
        q = q.where(BulkOperationItem.status == status)
    return list((await session.scalars(q.order_by(BulkOperationItem.created_at, BulkOperationItem.id).limit(limit).offset(offset))).all())


# ------------------------------------------------------------------------------------------------------------------ store state (PG-11 x PG-12)
async def plan_store_state(session: AsyncSession, store: Store, *, suspend: bool, actor_id: uuid.UUID | None) -> list[BulkOperation]:
    """Suspending a store with ``suspend_policy='disable_accounts'`` disables exactly its ACTIVE accounts, panel by panel (auto-confirmed,
    reason recorded). Reactivating re-enables ONLY the accounts that suspension disabled and that are still suspended: an account its owner
    suspended earlier is never switched back on by a store reactivation."""
    if store.suspend_policy != "disable_accounts":
        return []
    panel_ids = (
        await session.scalars(
            select(VpnAccount.panel_id).where(VpnAccount.store_id == store.id, VpnAccount.panel_id.is_not(None)).distinct()
        )
    ).all()
    made: list[BulkOperation] = []
    for panel_id in panel_ids:
        panel = await session.get(Panel, panel_id)
        if not panel or not providers.supports(panel.kind, "panel_ops"):
            continue
        sel = Selection(panel_id=panel_id, store_id=store.id)
        if not suspend:
            prior = await session.scalar(
                select(BulkOperation)
                .where(
                    BulkOperation.panel_id == panel_id,
                    BulkOperation.store_id == store.id,
                    BulkOperation.origin == "store_state",
                    BulkOperation.kind == "disable",
                    BulkOperation.status.in_(("done", "partial")),
                )
                .order_by(BulkOperation.created_at.desc())
                .limit(1)
            )
            if prior is None:
                continue
            names = (
                await session.scalars(
                    select(BulkOperationItem.username).where(BulkOperationItem.operation_id == prior.id, BulkOperationItem.status == "done")
                )
            ).all()
            if not names:
                continue
            sel.usernames = list(names)
        try:
            op = await preview(
                session,
                kind="disable" if suspend else "enable",
                selection=sel,
                reason="تعلیق فروشگاه" if suspend else "فعال‌سازی مجدد فروشگاه",
                actor_id=actor_id,
                origin="store_state",
                auto_confirm=True,
            )
        except AppError as exc:
            if exc.code == "BULK_EMPTY":
                continue
            raise
        made.append(op)
    return made


__all__ = [
    "KINDS",
    "KIND_LABELS",
    "Selection",
    "preview",
    "confirm",
    "cancel",
    "resume",
    "execute",
    "run_next",
    "claim_next",
    "plan_store_state",
    "items_page",
    "item_out",
]
