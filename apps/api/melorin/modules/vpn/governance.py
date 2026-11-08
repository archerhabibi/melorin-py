"""Store-admin governance (PG-12): per-store traffic cap, panel-side status, usage and the "panel stays quiet" switch.

Every store has its own PasarGuard Operator admin (``panel_admins``). This module reads how much that admin's users consumed, lets the
Melorin admin set an absolute traffic ceiling for the store, and blocks/unblocks the store at the panel itself when it is suspended
(an admin that is ``disabled`` on the panel can no longer create users there).

Absolute values only: ``data_limit`` bytes (``0`` = unlimited, which PasarGuard stores as "no limit"), ``status`` active|disabled.
A store whose cap is reached becomes ``limited`` on the panel and can no longer create accounts - hence the usage ratio, the warning
levels and ``sell_blocked`` here, so the admin sees it BEFORE customers do."""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from melorin.core import audit
from melorin.core.db import utcnow
from melorin.core.errors import AppError, NotFound
from melorin.kernel.models.stores import Store
from melorin.kernel.models.vpn import Panel, PanelAdmin
from melorin.modules.vpn.adapters.base import PanelError, supports
from melorin.modules.vpn.adapters.registry import build_adapter

log = logging.getLogger("melorin.vpn.governance")

GIB = 1024**3
MAX_CAP_GB = 1024 * 1024  # 1 PB: a typo guard, not a business rule
WARN_LEVELS = (80, 95)
STATUSES = ("active", "disabled")


def snap(row: PanelAdmin) -> dict:
    """R7: the panel's last-reported numbers for this admin (a dated snapshot; the age is ``row.usage_checked_at``)."""
    return dict(row.usage_snapshot or {})


def set_snap(row: PanelAdmin, **values) -> None:
    row.usage_snapshot = {**snap(row), **values}  # a NEW dict: SQLAlchemy does not see in-place JSON changes


def usage_ratio(row: PanelAdmin) -> float | None:
    """Used / cap in 0..1+, ``None`` when there is no cap or no reading yet."""
    cap, used = row.data_limit_bytes, snap(row).get("used_traffic_bytes")
    if not cap or cap <= 0 or used is None:
        return None
    return used / cap


def warning_level(row: PanelAdmin) -> int:
    ratio = usage_ratio(row)
    if ratio is None:
        return 0
    return max([lvl for lvl in WARN_LEVELS if ratio * 100 >= lvl] or [0])


def sell_blocked(row: PanelAdmin) -> str | None:
    """Why this store cannot create accounts on the panel right now (``None`` = it can)."""
    status = snap(row).get("status")
    if status == "disabled":
        return "ادمین فروشگاه روی پنل غیرفعال است."
    if status == "limited":
        return "سقف حجم ادمین فروشگاه روی پنل پر شده است."
    ratio = usage_ratio(row)
    if ratio is not None and ratio >= 1:
        return "مصرف از سقف حجم فروشگاه گذشته است."
    return None


def row_out(row: PanelAdmin, store: Store | None = None, panel: Panel | None = None) -> dict:
    ratio = usage_ratio(row)
    return {
        "id": row.id,
        "panel_id": row.panel_id,
        "panel_name": panel.name if panel else None,
        "store_id": row.store_id,
        "store_name": store.name if store else None,
        "store_status": store.status if store else None,
        "suspend_policy": store.suspend_policy if store else None,
        "username": row.username,
        "remote_id": row.remote_id,
        "remote_status": snap(row).get("status"),
        "data_limit_bytes": row.data_limit_bytes,
        "used_traffic_bytes": snap(row).get("used_traffic_bytes"),
        "total_users": snap(row).get("total_users"),
        "usage_ratio": round(ratio, 4) if ratio is not None else None,
        "warning_level": warning_level(row),
        "sell_blocked": sell_blocked(row),
        "usage_checked_at": row.usage_checked_at,
        "last_known": True,  # R7: used_traffic_bytes / total_users are a dated snapshot of the panel, never a live number
        "as_of": row.usage_checked_at,
        "error": row.governance_error,
    }


@dataclass
class SyncStats:
    checked: int = 0
    updated: int = 0
    errors: int = 0


async def _adapter_for(panel: Panel, capability: str):
    adapter = build_adapter(panel)
    if not supports(adapter, capability):
        close = getattr(adapter, "close", None)
        if callable(close):
            res = close()
            if hasattr(res, "__await__"):
                await res
        raise AppError(
            "CAPABILITY_MISSING", "اتصال این پنل دسترسی لازم برای مدیریت ادمین فروشگاه را ندارد.", 409, {"capability": capability}
        )
    return adapter


async def _close(adapter) -> None:
    close = getattr(adapter, "close", None)
    if callable(close):
        try:
            res = close()
            if hasattr(res, "__await__"):
                await res
        except Exception:
            log.warning("governance: adapter close failed", exc_info=True)


async def sync_usage(session: AsyncSession, panel: Panel, adapter=None) -> SyncStats:
    """Read every store admin of ``panel`` (usage, user count, status, the cap the panel really holds). One failing admin never stops the rest."""
    stats = SyncStats()
    rows = (
        await session.scalars(
            select(PanelAdmin).where(PanelAdmin.panel_id == panel.id, PanelAdmin.status == "active", PanelAdmin.remote_id.is_not(None))
        )
    ).all()
    if not rows:
        return stats
    owned = adapter is None
    try:
        adapter = adapter or build_adapter(panel)
    except Exception as exc:
        log.warning("governance: no adapter panel=%s: %s", panel.id, exc)
        return stats
    try:
        if not supports(adapter, "admin_governance"):
            return stats
        now = utcnow()
        for row in rows:
            stats.checked += 1
            try:
                detail = await adapter.get_admin_detail(int(row.remote_id))
            except PanelError as exc:
                row.governance_error = exc.message[:300]
                stats.errors += 1
                continue
            if detail is None:
                row.governance_error = "ادمین روی پنل پیدا نشد."
                stats.errors += 1
                continue
            set_snap(
                row,
                used_traffic_bytes=int(detail.get("used_traffic") or 0),
                total_users=int(detail.get("total_users") or 0),
                status=str(detail.get("status") or "") or None,
            )
            panel_cap = detail.get("data_limit")
            if row.data_limit_bytes is None and panel_cap:  # adopt a cap someone already set on the panel; never overwrite one Melorin set
                row.data_limit_bytes = int(panel_cap)
            row.usage_checked_at, row.governance_error = now, None
            stats.updated += 1
    finally:
        if owned:
            await _close(adapter)
    return stats


async def set_limits(
    session: AsyncSession,
    row: PanelAdmin,
    *,
    actor_id: uuid.UUID | None,
    data_limit_gb: float | None = None,
    clear_limit: bool = False,
    status: str | None = None,
    notifications_off: bool | None = None,
    reason: str | None = None,
) -> PanelAdmin:
    """Apply absolute governance values to one store admin on the panel, then mirror and audit them."""
    if data_limit_gb is None and not clear_limit and status is None and notifications_off is None:
        raise AppError("NOTHING_TO_CHANGE", "هیچ تغییری مشخص نشده است.", 400)
    if status is not None and status not in STATUSES:
        raise AppError("BAD_ADMIN_STATUS", "وضعیت ادمین باید active یا disabled باشد.", 400)
    cap_bytes: int | None = None
    if clear_limit:
        cap_bytes = 0
    elif data_limit_gb is not None:
        if not 0 < float(data_limit_gb) <= MAX_CAP_GB:
            raise AppError("BAD_DATA_LIMIT", "سقف حجم باید عددی مثبت (به گیگابایت) باشد؛ برای حذف سقف گزینهٔ «بدون سقف» را بزنید.", 400)
        cap_bytes = int(float(data_limit_gb) * GIB)
    if not row.remote_id:
        raise AppError("ADMIN_NOT_SYNCED", "ادمین این فروشگاه هنوز روی پنل ساخته نشده است.", 409)
    panel = await session.get(Panel, row.panel_id)
    if not panel:
        raise NotFound("پنل")
    store = await session.get(Store, row.store_id)
    adapter = await _adapter_for(panel, "admin_governance")
    try:
        detail = await adapter.update_admin_limits(
            int(row.remote_id), data_limit=cap_bytes, status=status, notifications_off=notifications_off
        )
    except PanelError as exc:
        raise AppError("PANEL_ERROR", f"پنل درخواست را نپذیرفت: {exc.message[:200]}", 502) from exc
    finally:
        await _close(adapter)
    before = {"data_limit_bytes": row.data_limit_bytes, "remote_status": snap(row).get("status")}
    if cap_bytes is not None:
        row.data_limit_bytes = cap_bytes or None
    if status is not None:
        set_snap(row, status=status)
    if isinstance(detail, dict) and detail.get("status"):
        set_snap(row, status=str(detail["status"]))
    row.governance_error = None
    audit.record(
        session,
        "panel_admin.governance",
        actor_id=actor_id,
        actor_type="admin",
        entity_type="panel_admin",
        entity_id=row.id,
        store_id=row.store_id,
        data={
            "store": store.name if store else None,
            "before": before,
            "after": {"data_limit_bytes": row.data_limit_bytes, "remote_status": snap(row).get("status")},
            "notifications_off": notifications_off,
            "reason": (reason or "")[:300],
        },
    )
    await session.commit()
    return row


async def apply_store_status(session: AsyncSession, store: Store, *, suspended: bool, actor_id: uuid.UUID | None) -> list[dict]:
    """A suspended store also stops at the panel: its admin becomes ``disabled`` (no new accounts there); reactivation sets it back to
    ``active``. Runs only for stores with ``suspend_policy='disable_accounts'``; best effort per panel, every outcome reported."""
    if store.suspend_policy != "disable_accounts":
        return []
    rows = (await session.scalars(select(PanelAdmin).where(PanelAdmin.store_id == store.id, PanelAdmin.remote_id.is_not(None)))).all()
    report: list[dict] = []
    for row in rows:
        panel = await session.get(Panel, row.panel_id)
        if not panel or panel.kind != "pasarguard":
            continue
        try:
            await set_limits(
                session, row, actor_id=actor_id, status="disabled" if suspended else "active",
                reason="تعلیق فروشگاه" if suspended else "فعال‌سازی مجدد فروشگاه",
            )  # fmt: skip
            report.append({"panel": panel.name, "ok": True})
        except AppError as exc:
            row.governance_error = exc.message[:300]
            await session.commit()
            report.append({"panel": panel.name, "ok": False, "error": exc.message})
    return report
