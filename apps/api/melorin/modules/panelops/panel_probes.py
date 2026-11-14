"""Live probes of one panel that admin screens ask for: what it offers, how its groups are doing, a health check now.

The admin routers used to build a provider adapter themselves (``admin/capacity.py``, ``admin/targets.py``, ``admin/panels.py``).
That put provider calls, session lifetime and failure translation in the top layer, where import-linter cannot see them. Every
function here owns the adapter for the duration of ONE call and always closes it; a router only validates, authorizes, audits
and shapes the HTTP response. The read-only functions never raise: a panel that cannot answer yields ``None``.
"""

from __future__ import annotations

import logging

from sqlalchemy.ext.asyncio import AsyncSession

from melorin.core.errors import AppError
from melorin.kernel.models.vpn import Panel
from melorin.modules.panel_integrations import capabilities as panel_caps
from melorin.modules.panel_integrations import capacity, health
from melorin.modules.panel_integrations.adapters import providers
from melorin.modules.panel_integrations.adapters.base import PanelError, supports
from melorin.modules.panel_integrations.adapters.registry import build_adapter
from melorin.modules.panel_integrations.session import close_adapter
from melorin.modules.panelops import panel_notices

log = logging.getLogger("melorin.panelops.panel_probes")


async def live_group_health(panel: Panel) -> dict[int, dict] | None:
    """``{group_id: assessment dict}`` from the live panel, or ``None`` when it cannot be asked (never raises)."""
    if not providers.supports(panel.kind, "panel_ops") or not panel_caps.capabilities_of(panel).has("capacity_ops"):
        return None
    adapter = None
    try:
        adapter = build_adapter(panel)
        if not supports(adapter, "capacity_ops"):
            return None
        groups, _templates = await capacity.fetch_assessments(adapter)
        return {gid: a.to_dict() for gid, a in groups.items()}
    except Exception:
        log.info("live group health failed panel=%s", panel.id, exc_info=True)
        return None
    finally:
        await close_adapter(adapter)


async def fetch_listing(panel: Panel) -> dict | None:
    """What the panel offers right now, or None when it cannot be asked (down, wrong credentials, kind without a listing)."""
    adapter = None
    try:
        adapter = build_adapter(panel)
        lister = getattr(adapter, "list_targets", None)
        return await lister() if callable(lister) else None
    except Exception:
        log.info("panel target listing failed panel=%s", panel.id, exc_info=True)
        return None
    finally:
        await close_adapter(adapter)


async def refresh_panel_capacity(session: AsyncSession, panel: Panel) -> list:
    """Run the check the health job runs, now, and store the verdicts. Raises ``AppError`` when the panel cannot do it or is down."""
    if not providers.supports(panel.kind, "panel_ops"):
        raise AppError("CAPABILITY_UNAVAILABLE", "بررسی ظرفیت واقعی فقط برای پنل پاسارگارد است.", 409)
    adapter = None
    try:
        adapter = build_adapter(panel)
        return await capacity.refresh_panel(session, panel, adapter)
    except PanelError as exc:
        raise AppError("PANEL_UNREACHABLE", f"پنل پاسخ نداد: {exc.message[:200]}", 502) from exc
    finally:
        await close_adapter(adapter)


async def check_health_now(session: AsyncSession, panel: Panel) -> health.HealthResult:
    """Explicit health check (panel answers AND its nodes), applied to the panel row and announced; the caller commits."""
    adapter = None
    try:
        adapter = build_adapter(panel)
        result = await health.check_panel(session, panel, adapter)
    except Exception as exc:
        result = health.HealthResult(
            health.UNHEALTHY, (getattr(exc, "message", None) or str(exc) or exc.__class__.__name__)[:300], {"layer": 1, "sellable": False}
        )
    finally:
        await close_adapter(adapter)
    if result.error == "health check returned false":
        result.error = "پنل پاسخ سالم نداد."
    previous = health.apply(panel, result)
    await panel_notices.notify_panel_health(session, panel, previous)
    await panel_notices.notify_panel_nodes(session, panel, result.node_changes)
    return result
