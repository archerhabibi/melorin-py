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

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from melorin.modules.panel_integrations.adapters import providers
from melorin.core import audit
from melorin.core.db import utcnow
from melorin.core.errors import AppError, NotFound
from melorin.domain.order_state import VpnStatus
from melorin.kernel.models.stores import Store
from melorin.kernel.models.vpn import BulkOperation, BulkOperationItem, Panel, VpnAccount
from melorin.modules.vpn_accounts import sync

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
        if base is None:
            return None
        new = max(base, now) + dt.timedelta(days=params["days"])
        return {"base_expire_at": base.isoformat(), "expire_at": new.isoformat()}
    if kind == "add_traffic":
        base_bytes = int(account.sold_traffic_bytes or 0)
        return {"base_traffic_bytes": base_bytes, "traffic_bytes": base_bytes + params["gb"] * GIB}
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
    op.selection = {**(op.selection or {}), "skipped": skipped}
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
        sel = Selection(panel_id=panel.id, store_id=store.id)
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
    "plan_store_state",
    "items_page",
    "item_out",
]
