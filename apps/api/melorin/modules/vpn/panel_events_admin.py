"""Admin side of PasarGuard events (PG-03): switch the webhook on/off at the panel, rotate its secret, read the state.

Melorin writes exactly one panel setting - its own webhook target (see ``adapters/pasarguard/events.py``) - and only when an admin
asks for it. The shared secret is generated here, stored encrypted, and sent to the panel once; it is never returned by any API.

Order matters for safety: the new secret is stored FIRST (so the first delivery after the panel accepts it already verifies), and
the old one is restored when the panel refuses the write, so a failed connect never leaves Melorin and the panel disagreeing.
"""

from __future__ import annotations

import datetime as dt
import logging
import secrets
import uuid

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from melorin.core.config import get_settings
from melorin.core.crypto import encrypt
from melorin.core.db import utcnow
from melorin.core.errors import AppError
from melorin.core.health import WEBHOOK_SILENT_AFTER
from melorin.kernel.models.vpn import Panel, PanelEvent
from melorin.modules.vpn import panel_events
from melorin.modules.vpn.adapters.base import PanelError, supports
from melorin.modules.vpn.adapters.registry import build_adapter

log = logging.getLogger("melorin.vpn.panel_events_admin")

SILENT_AFTER = WEBHOOK_SILENT_AFTER  # single source of truth lives in core.health (core must not import modules)


def webhook_url(panel: Panel) -> str:
    base = (get_settings().public_api_url or "").rstrip("/")
    if not base:
        raise AppError("PUBLIC_URL_MISSING", "MELORIN_PUBLIC_API_URL تنظیم نشده است؛ آدرس دریافت رویداد مشخص نیست.", 409)
    return f"{base}/api/v1/webhooks/pasarguard/{panel.id}"


def _require_pasarguard(panel: Panel) -> None:
    if panel.kind != "pasarguard":
        raise AppError("NOT_PASARGUARD", "رویداد زنده فقط برای پنل پاسارگارد پشتیبانی می‌شود.", 409)


def _is_connected(panel: Panel) -> bool:
    return bool(panel.webhook_secret_enc) and panel.webhook_connected_at is not None


async def _close(adapter) -> None:
    close = getattr(adapter, "close", None)
    if callable(close):
        try:
            await close()
        except Exception:
            log.debug("adapter close failed", exc_info=True)


async def counts(session: AsyncSession, panel_id: uuid.UUID, *, now: dt.datetime | None = None) -> dict:
    now = now or utcnow()
    by_status = dict(
        (
            await session.execute(
                select(PanelEvent.status, func.count()).where(PanelEvent.panel_id == panel_id).group_by(PanelEvent.status)
            )
        ).all()
    )
    day = await session.scalar(
        select(func.count())
        .select_from(PanelEvent)
        .where(PanelEvent.panel_id == panel_id, PanelEvent.received_at >= now - dt.timedelta(hours=24))
    )
    return {k: int(by_status.get(k, 0)) for k in ("pending", "processing", "processed", "ignored", "failed")} | {"last_24h": int(day or 0)}


async def status(session: AsyncSession, panel: Panel, *, live: bool = False, now: dt.datetime | None = None) -> dict:
    """Secret-free state for the admin UI. ``live`` also reads the panel's own webhook settings (one extra panel call)."""
    now = now or utcnow()
    out: dict = {
        "panel_id": str(panel.id),
        "supported": panel.kind == "pasarguard",
        "connected": _is_connected(panel),
        "connected_at": panel.webhook_connected_at,
        "last_event_at": panel.webhook_last_at,
        "silent_for_seconds": None,
        "url": None,
        "counts": await counts(session, panel.id, now=now),
        "panel_side": None,
        "warnings": [],
    }
    if panel.kind != "pasarguard":
        return out
    try:
        out["url"] = webhook_url(panel)
    except AppError as exc:
        out["warnings"].append(exc.message)
    if out["connected"]:
        ref = panel.webhook_last_at or panel.webhook_connected_at
        if ref is not None:
            ref = ref if ref.tzinfo else ref.replace(tzinfo=dt.UTC)
            out["silent_for_seconds"] = max(0, int((now - ref).total_seconds()))
    if live and out["connected"] and out["url"]:
        adapter = None
        try:
            adapter = build_adapter(panel)
            if supports(adapter, "event_source"):
                out["panel_side"] = await adapter.get_webhook_config(out["url"])
                if not out["panel_side"]["melorin_registered"]:
                    out["warnings"].append(
                        "پنل دیگر Melorin را به‌عنوان مقصد رویداد ندارد (کسی آن را از پنل پاک کرده است). دوباره وصل کنید."
                    )
                elif not out["panel_side"]["enabled"]:
                    out["warnings"].append("وب‌هوک در خود پنل غیرفعال است.")
            else:
                out["warnings"].append("نقش فعلی Melorin روی پنل اجازهٔ تنظیم رویداد (settings.update) را ندارد.")
        except PanelError as exc:
            out["warnings"].append(f"خواندن تنظیمات پنل ناموفق بود: {exc.message[:160]}")
        finally:
            if adapter is not None:
                await _close(adapter)
    return out


async def connect(session: AsyncSession, panel: Panel, *, rotate: bool = False) -> dict:
    """Register Melorin as the panel's webhook target. Idempotent; ``rotate`` forces a fresh secret even when already connected.

    Returns the secret-free :func:`status` plus ``warnings`` from the panel write. Raises ``AppError`` with an admin-readable reason.
    """
    _require_pasarguard(panel)
    url = webhook_url(panel)
    adapter = build_adapter(panel)
    previous = (panel.webhook_secret_enc, panel.webhook_connected_at)
    try:
        if not supports(adapter, "event_source"):
            raise AppError("CAPABILITY_MISSING", "این اتصال اجازهٔ نوشتن تنظیمات پنل (settings.update) را ندارد.", 409)
        reuse = _is_connected(panel) and not rotate and panel_events.secret_for(panel)
        secret = reuse or secrets.token_urlsafe(32)
        panel.webhook_secret_enc = encrypt(secret)
        await session.flush()
        try:
            result = await adapter.connect_webhook(url, secret)
        except PanelError as exc:
            panel.webhook_secret_enc, panel.webhook_connected_at = previous
            await session.flush()
            raise AppError("PANEL_ERROR", f"پنل تنظیمات رویداد را نپذیرفت: {exc.message[:200]}", 502) from exc
        panel.webhook_connected_at = utcnow()
        await session.flush()
    finally:
        await _close(adapter)
    state = await status(session, panel)
    state["warnings"] = list(result.get("warnings", [])) + state["warnings"]
    state["panel_side"] = {k: v for k, v in result.items() if k != "warnings"}
    return state


async def disconnect(session: AsyncSession, panel: Panel) -> dict:
    """Remove Melorin's target from the panel and forget the secret. Events already stored are still processed."""
    _require_pasarguard(panel)
    url = webhook_url(panel)
    warnings: list[str] = []
    if _is_connected(panel):
        adapter = build_adapter(panel)
        try:
            if supports(adapter, "event_source"):
                result = await adapter.disconnect_webhook(url)
                warnings = list(result.get("warnings", []))
            else:
                warnings.append("نقش فعلی اجازهٔ تغییر تنظیمات پنل را نداشت؛ مقصد را خودتان از پنل حذف کنید.")
        except PanelError as exc:
            raise AppError("PANEL_ERROR", f"پنل تنظیمات رویداد را نپذیرفت: {exc.message[:200]}", 502) from exc
        finally:
            await _close(adapter)
    panel.webhook_secret_enc, panel.webhook_connected_at = None, None
    await session.flush()
    state = await status(session, panel)
    state["warnings"] = warnings + state["warnings"]
    return state


async def retry_failed(session: AsyncSession, panel_id: uuid.UUID, *, event_id: uuid.UUID | None = None) -> int:
    """Put ``failed`` events back in the queue (one, or all of the panel's)."""
    now = utcnow()
    q = update(PanelEvent).where(PanelEvent.panel_id == panel_id, PanelEvent.status == panel_events.FAILED)
    if event_id is not None:
        q = q.where(PanelEvent.id == event_id)
    result = await session.execute(
        q.values(status=panel_events.PENDING, attempts=0, available_at=now, processed_at=None, outcome="retry (admin)")
    )
    return int(result.rowcount or 0)
