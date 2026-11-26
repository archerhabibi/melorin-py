"""Admin notices about panels (health, nodes, settings drift, sell-guard/capacity).

They describe panel state, so they live with the panel domain (``panelops``) and only *emit* an admin notice of a given kind
(``events.emit_admin_notice``, Topic ``panels``); where it is delivered is ``domain.messaging_policy``'s business: a panel that turns
unhealthy and nodes that start failing also reach the admin's bot DM, everything else (recovery, degraded, drift, capacity) only the
group. All are best-effort: a failure here can never fail the health, drift or capacity check that calls them.
"""

from __future__ import annotations

import logging

from melorin.core import events

log = logging.getLogger("melorin.panelops.notices")


async def notify_panel_health(session, panel, previous: str | None) -> None:
    """Tell the admin when a panel turns unhealthy (bot DM + panels topic) and when it recovers (panels topic only).

    Called by the health job and the manual health check with the status the panel had *before* this check, so a panel
    that stays unhealthy does not repeat the message every 5 minutes. ``degraded`` (some node failing, panel still serving) is
    announced by :func:`notify_panel_nodes`, which names the nodes and the fix. Best-effort: it can never fail the health check.
    """
    now = panel.health_status
    if now == previous:
        return
    if now == "unhealthy":
        error = str(panel.last_health_error or "نامشخص")[:250]
        kind, text = "panel_unhealthy", f"🔴 پنل «{panel.name}» ناسالم شد\nخطا: {error}"
    elif now == "healthy" and previous == "unhealthy":
        kind, text = "panel_recovered", f"🟢 پنل «{panel.name}» دوباره سالم شد"
    elif now == "degraded" and previous == "unhealthy":
        kind, text = "panel_degraded", f"🟠 پنل «{panel.name}» پاسخ می‌دهد ولی بعضی نودها خطا دارند"
    else:
        return
    try:
        async with session.begin_nested():
            await events.emit_admin_notice(session, kind, text)
    except Exception:
        log.exception("panel notice: panel health notice failed panel=%s", panel.id)


async def notify_settings_drift(session, panel, before: int, after: int) -> None:
    """Announce (once) that a panel's settings started to differ from what Melorin needs, and when that is fixed (PG-15).

    Only the change 0 -> N and N -> 0 is announced, so an unfixed drift does not repeat every hour. Findings are named by key; no value
    read from the panel's settings is ever put in the message. Best-effort: it can never fail the drift check."""
    if (before > 0) == (after > 0):
        return
    keys = ", ".join(f["key"] for f in (panel.settings_drift or {}).get("findings", []) if f.get("state") == "drift")
    kind, text = (
        ("panel_settings_drift", f"🟠 تنظیمات پنل «{panel.name}» با نیاز ملورین هم‌خوان نیست ({keys})؛ بخش «رانش تنظیمات» پنل را ببینید.")
        if after > 0
        else ("panel_settings_fixed", f"🟢 تنظیمات پنل «{panel.name}» دوباره با ملورین هم‌خوان شد")
    )
    try:
        async with session.begin_nested():
            await events.emit_admin_notice(session, kind, text)
    except Exception:
        log.exception("panel notice: settings drift notice failed panel=%s", panel.id)


def node_failed_text(panel_name: str, changes: list[dict]) -> str | None:
    """One message per panel and check for every node that started failing (a 4-node outage is ONE notice)."""
    failed = [c for c in changes if c["to"] in ("error", "limited", "unknown")]
    if not failed:
        return None
    lines = [f"🟠 نود(های) پنل «{panel_name}» خطا دارند:"]
    for c in failed[:8]:
        msg = str(c.get("message") or "").strip()[:120]
        lines.append(f"• {c['name']}" + (f" — {msg}" if msg else ""))
    if len(failed) > 8:
        lines.append(f"… و {len(failed) - 8} نود دیگر")
    return "\n".join(lines)


def node_recovered_text(panel_name: str, changes: list[dict]) -> str | None:
    """One message per panel and check for the nodes that are healthy again."""
    recovered = [c for c in changes if c["from"] in ("error", "limited", "unknown") and c["to"] not in ("error", "limited", "unknown")]
    if not recovered:
        return None
    return f"🟢 نود(های) پنل «{panel_name}» دوباره سالم شدند: " + "، ".join(c["name"] for c in recovered[:8])


async def notify_panel_nodes(session, panel, changes: list[dict]) -> None:
    """Admin notices for node status transitions found by the health job (PG-01): failures (bot DM + panels topic) and recoveries
    (panels topic only) are separate notices because only the failure is worth a DM. Best-effort."""
    for kind, text in (
        ("node_failed", node_failed_text(panel.name, changes)),
        ("node_recovered", node_recovered_text(panel.name, changes)),
    ):
        if not text:
            continue
        try:
            async with session.begin_nested():
                await events.emit_admin_notice(session, kind, text)
        except Exception:
            log.exception("panel notice: %s notice failed panel=%s", kind, panel.id)


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
    """Group notice (panels topic, no DM) for sell-guard flips and capacity thresholds (PG-08). Best-effort."""
    text = server_capacity_text(panel.name, changes)
    if not text:
        return
    try:
        async with session.begin_nested():
            await events.emit_admin_notice(session, "panel_capacity", text)
    except Exception:
        log.exception("panel notice: server capacity notice failed panel=%s", panel.id)
