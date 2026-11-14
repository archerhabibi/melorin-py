"""Event Center notices about panels (health, nodes, settings drift, sell-guard/capacity).

They describe panel state, so they live with the panel domain (``panelops``) and only *emit* an Event Center message
(topic ``errors``); how and where it is delivered stays the Event Center's business. All are best-effort: a failure here can never
fail the health, drift or capacity check that calls them.
"""

from __future__ import annotations

import logging

from melorin.core import events
from melorin.modules.eventcenter import topics

log = logging.getLogger("melorin.panelops.notices")


async def notify_panel_health(session, panel, previous: str | None) -> None:
    """Tell the admin's errors topic when a panel turns unhealthy (and when it recovers).

    Called by the health job and the manual health check with the status the panel had *before* this check, so a panel
    that stays unhealthy does not repeat the message every 5 minutes. ``degraded`` (some node failing, panel still serving) is
    announced by :func:`notify_panel_nodes`, which names the nodes and the fix. Best-effort: it can never fail the health check.
    """
    now = panel.health_status
    if now == previous:
        return
    if now == "unhealthy":
        error = str(panel.last_health_error or "نامشخص")[:250]
        text = f"🔴 پنل «{panel.name}» ناسالم شد\nخطا: {error}"
    elif now == "healthy" and previous == "unhealthy":
        text = f"🟢 پنل «{panel.name}» دوباره سالم شد"
    elif now == "degraded" and previous == "unhealthy":
        text = f"🟠 پنل «{panel.name}» پاسخ می‌دهد ولی بعضی نودها خطا دارند"
    else:
        return
    try:
        async with session.begin_nested():
            await events.emit(session, events.EVENT_CENTER, {"store_id": None, "topic": topics.ERRORS, "text": text})
    except Exception:
        log.exception("panel notice: panel health notice failed panel=%s", panel.id)


async def notify_settings_drift(session, panel, before: int, after: int) -> None:
    """Announce (once) that a panel's settings started to differ from what Melorin needs, and when that is fixed (PG-15).

    Only the change 0 -> N and N -> 0 is announced, so an unfixed drift does not repeat every hour. Findings are named by key; no value
    read from the panel's settings is ever put in the message. Best-effort: it can never fail the drift check."""
    if (before > 0) == (after > 0):
        return
    keys = ", ".join(f["key"] for f in (panel.settings_drift or {}).get("findings", []) if f.get("state") == "drift")
    text = (
        f"🟠 تنظیمات پنل «{panel.name}» با نیاز ملورین هم‌خوان نیست ({keys})؛ بخش «رانش تنظیمات» پنل را ببینید."
        if after > 0
        else f"🟢 تنظیمات پنل «{panel.name}» دوباره با ملورین هم‌خوان شد"
    )
    try:
        async with session.begin_nested():
            await events.emit(session, events.EVENT_CENTER, {"store_id": None, "topic": topics.ERRORS, "text": text})
    except Exception:
        log.exception("panel notice: settings drift notice failed panel=%s", panel.id)


def panel_nodes_text(panel_name: str, changes: list[dict]) -> str | None:
    """One message per panel and check for every node that started or stopped failing (a 4-node outage is ONE notice)."""
    failed = [c for c in changes if c["to"] in ("error", "limited", "unknown")]
    recovered = [c for c in changes if c["from"] in ("error", "limited", "unknown") and c["to"] not in ("error", "limited", "unknown")]
    lines: list[str] = []
    if failed:
        lines.append(f"🟠 نود(های) پنل «{panel_name}» خطا دارند:")
        for c in failed[:8]:
            msg = str(c.get("message") or "").strip()[:120]
            lines.append(f"• {c['name']}" + (f" — {msg}" if msg else ""))
        if len(failed) > 8:
            lines.append(f"… و {len(failed) - 8} نود دیگر")
    if recovered:
        lines.append(f"🟢 نود(های) پنل «{panel_name}» دوباره سالم شدند: " + "، ".join(c["name"] for c in recovered[:8]))
    return "\n".join(lines) or None


async def notify_panel_nodes(session, panel, changes: list[dict]) -> None:
    """Event Center notice for node status transitions found by the health job (PG-01). Best-effort."""
    text = panel_nodes_text(panel.name, changes)
    if not text:
        return
    try:
        async with session.begin_nested():
            await events.emit(session, events.EVENT_CENTER, {"store_id": None, "topic": topics.ERRORS, "text": text})
    except Exception:
        log.exception("panel notice: panel node notice failed panel=%s", panel.id)


def server_capacity_text(panel_name: str, changes: list) -> str | None:
    """One message per panel and check: destinations that stopped/started being sellable and capacity thresholds crossed (PG-08)."""
    lines: list[str] = []
    blocked = [c for c in changes if c.kind == "sellable" and c.new == "blocked"]
    back = [c for c in changes if c.kind == "sellable" and c.new == "sellable"]
    if blocked:
        lines.append(f"🔴 مقصدهای پنل «{panel_name}» از فروش خارج شدند (اکانت‌های موجود تغییری نمی‌کنند):")
        for c in blocked[:8]:
            lines.append(f"• {c.server}" + (f" — {str(c.detail)[:140]}" if c.detail else ""))
    if back:
        lines.append(f"🟢 مقصدهای پنل «{panel_name}» دوباره قابل فروش شدند: " + "، ".join(c.server for c in back[:8]))
    labels = {"80": "🟡 بیش از ۸۰٪ پر شد", "95": "🟠 بیش از ۹۵٪ پر شد", "100": "🔴 ظرفیت پر شد"}
    for c in changes:
        if c.kind == "capacity" and c.new in labels:
            lines.append(f"{labels[c.new]}: {c.server} (پنل «{panel_name}»)")
    return "\n".join(lines) or None


async def notify_server_capacity(session, panel, changes: list) -> None:
    """Event Center notice for sell-guard flips and capacity thresholds (PG-08). Best-effort."""
    text = server_capacity_text(panel.name, changes)
    if not text:
        return
    try:
        async with session.begin_nested():
            await events.emit(session, events.EVENT_CENTER, {"store_id": None, "topic": topics.ERRORS, "text": text})
    except Exception:
        log.exception("panel notice: server capacity notice failed panel=%s", panel.id)
