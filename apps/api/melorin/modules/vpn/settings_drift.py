"""Panel-settings drift control and expired-user lifecycle policy (PG-15). READ-ONLY by design.

PasarGuard keeps settings Melorin silently depends on: where it pushes events, the subscription address, and above all the
``cleanup`` block that can DELETE expired users on a schedule. Melorin sees a deleted user as ``missing_on_panel`` and a customer inside the
renewal grace period (``renewal.GRACE_DAYS``) loses the account they were allowed to renew. This module reads ``GET /api/settings``,
compares it with what Melorin needs, stores a secret-free verdict on the panel row and raises an alert. It NEVER writes a setting: the
only panel setting Melorin ever writes is the webhook, through the existing "connect events" action (PG-03), with an admin's confirmation.

Per-panel lifecycle policy (``panels.expired_cleanup_policy``):

* ``keep``     (default) the panel must NOT auto-delete expired users: retention off (0 / empty).
* ``aligned``  the panel MAY auto-delete, but only after at least ``GRACE_DAYS`` so a renewal is never lost.

Findings are ``ok | drift | info | unknown``; only ``drift`` counts and alerts. Panel notification settings are reported by flag only: no
token, chat id or URL from the panel is ever stored or returned."""

from __future__ import annotations

import logging
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from melorin.core import audit
from melorin.core.db import utcnow
from melorin.core.errors import AppError, NotFound
from melorin.kernel.models.vpn import Panel
from melorin.modules.vpn import capabilities as panel_caps
from melorin.modules.vpn.adapters.base import PanelError, supports
from melorin.modules.vpn.adapters.pasarguard.events import describe_webhook
from melorin.modules.vpn.renewal import GRACE_DAYS
from melorin.modules.vpn.subscription_check import _origin

log = logging.getLogger("melorin.vpn.settings_drift")

POLICIES = ("keep", "aligned")
POLICY_LABELS = {
    "keep": "حذف خودکار کاربران منقضی در پنل خاموش بماند",
    "aligned": f"حذف خودکار مجاز است، ولی نه زودتر از مهلت تمدید ({GRACE_DAYS} روز)",
}


def finding(key: str, state: str, message: str, **extra) -> dict:
    return {"key": key, "state": state, "message": message, **extra}


def _positive_int(value) -> int:
    """``expired_users_retention_days``: a positive integer = auto-delete after that many days; anything else (0, null, junk) = off."""
    if isinstance(value, bool):
        return 0
    try:
        n = int(value)
    except (TypeError, ValueError):
        return 0
    return n if n > 0 else 0


def evaluate_cleanup(cleanup: dict | None, policy: str, grace_days: int = GRACE_DAYS) -> dict:
    """The lifecycle verdict from the panel's ``cleanup`` block. Pure."""
    if not isinstance(cleanup, dict):
        return finding("expired_cleanup", "unknown", "تنظیم حذف خودکار منقضی‌ها (cleanup) از پنل خوانده نشد.")
    days = _positive_int(cleanup.get("expired_users_retention_days"))
    includes_limited = bool(cleanup.get("include_limited_users"))
    facts = {"retention_days": days or None, "include_limited": includes_limited, "policy": policy, "grace_days": grace_days}
    if days == 0:
        return finding("expired_cleanup", "ok", "حذف خودکار کاربران منقضی در پنل خاموش است.", **facts)
    scope = " (کاربران محدودشده‌ی بی‌حجم هم شامل می‌شوند)" if includes_limited else ""
    if policy == "aligned":
        if days >= grace_days:
            return finding(
                "expired_cleanup", "ok", f"پنل منقضی‌ها را پس از {days} روز حذف می‌کند؛ از مهلت تمدید ({grace_days} روز) کمتر نیست.", **facts
            )
        return finding(
            "expired_cleanup", "drift",
            f"پنل منقضی‌ها را پس از {days} روز حذف می‌کند{scope} ولی مهلت تمدید {grace_days} روز است؛ مشتری قبل از پایان مهلت اکانت خود را از دست می‌دهد.",
            **facts,
        )  # fmt: skip
    return finding(
        "expired_cleanup", "drift",
        f"پنل کاربران منقضی را پس از {days} روز خودکار حذف می‌کند{scope}؛ ملورین آن‌ها را «missing_on_panel» می‌بیند و مهلت تمدید از بین می‌رود. "
        "حذف خودکار را در پنل خاموش کنید، یا سیاست این پنل را روی «هماهنگ با مهلت تمدید» بگذارید.",
        **facts,
    )  # fmt: skip


def evaluate_webhook(webhook: dict | None, *, connected: bool, url: str | None) -> dict:
    """Events: if an admin connected them in Melorin the panel must still push to Melorin. Pure; ``webhook`` is the panel's block."""
    if url is None and connected:
        return finding("webhook", "unknown", "آدرس عمومی API تنظیم نشده است؛ مقصد رویدادها قابل مقایسه نیست.")
    info = describe_webhook({"webhook": webhook or {}}, url)
    facts = {"enabled": info["enabled"], "melorin_registered": info["melorin_registered"], "other_targets": info["other_targets"]}
    if connected:
        if info["enabled"] and info["melorin_registered"]:
            return finding("webhook", "ok", "پنل رویدادها را به ملورین می‌فرستد.", **facts)
        why = "رویداد در پنل خاموش شده است" if not info["enabled"] else "آدرس ملورین از فهرست مقصدهای پنل حذف شده است"
        return finding(
            "webhook", "drift", f"رویداد زنده در ملورین وصل است ولی {why}؛ تا اتصال دوباره فقط reconcile ساعتی همگام می‌کند.", **facts
        )
    if info["enabled"] and info["melorin_registered"]:
        return finding("webhook", "ok", "آدرس ملورین در پنل ثبت شده است؛ اتصال زنده در ملورین فعال نیست ولی ناسازگاری وجود ندارد.", **facts)
    if info["enabled"] and info["targets"]:
        return finding(
            "webhook", "info", "پنل رویدادها را جای دیگری می‌فرستد و رویداد زنده ملورین وصل نیست (reconcile ساعتی کار می‌کند).", **facts
        )
    return finding("webhook", "ok", "رویداد زنده فعال نیست و لازم هم نیست.", **facts)


def evaluate_subscription(subscription: dict | None, sub_base_url: str | None) -> dict:
    """The panel's ``subscription.url_prefix`` against Melorin's ``sub_base_url`` (origin compared, paths are free)."""
    panel_origin = _origin((subscription or {}).get("url_prefix"))
    melorin_origin = _origin(sub_base_url)
    if not panel_origin:
        return finding("subscription_prefix", "info", "پنل آدرس پایه‌ی اشتراک (url_prefix) را تنظیم نکرده است.")
    if not melorin_origin:
        return finding(
            "subscription_prefix",
            "info",
            "برای این پنل sub_base_url در ملورین تنظیم نشده؛ فقط آدرس پنل نمایش داده می‌شود.",
            panel=panel_origin,
        )
    if panel_origin != melorin_origin:
        return finding(
            "subscription_prefix", "drift",
            "آدرس اشتراک پنل با sub_base_url ملورین یکی نیست؛ لینک‌های ساخته‌شده یا QR ممکن است خراب باشند.",
            panel=panel_origin, melorin=melorin_origin,
        )  # fmt: skip
    return finding("subscription_prefix", "ok", "آدرس اشتراک پنل و ملورین یکی است.", panel=panel_origin)


def evaluate_hwid(hwid: dict | None) -> dict:
    """HWID (device limit) is a policy the panel owns: shown for troubleshooting, never a drift."""
    if not isinstance(hwid, dict):
        return finding("hwid", "unknown", "تنظیمات محدودیت دستگاه (HWID) خوانده نشد.")
    facts = {
        k: hwid.get(k) for k in ("enabled", "forced", "fallback_limit", "min_limit", "max_limit") if isinstance(hwid.get(k), int | bool)
    }
    state = "فعال" if hwid.get("enabled") else "غیرفعال"
    return finding("hwid", "info", f"محدودیت دستگاه (HWID) در پنل {state} است.", **facts)


def evaluate_notifications(settings: dict) -> dict:
    """Does the panel message people by itself? Flags only: tokens / chat ids / URLs are never copied."""
    notif = settings.get("notification_settings") if isinstance(settings.get("notification_settings"), dict) else {}
    telegram = bool(notif.get("notify_telegram"))
    discord = bool(notif.get("notify_discord"))
    if telegram or discord:
        return finding(
            "panel_notifications", "info",
            "پنل خودش هم اعلان می‌فرستد (تلگرام/دیسکورد)؛ پس از اتصال رویدادها، اعلان مشتری باید فقط از ملورین برود.",
            telegram=telegram, discord=discord,
        )  # fmt: skip
    return finding("panel_notifications", "ok", "پنل اعلان مستقل نمی‌فرستد.", telegram=False, discord=False)


MAX_RETENTION_DAYS = 3650


def retention_days(panel: Panel) -> int:
    """Days an expired user must be kept before the panel may delete it: the admin's number for this panel, never below the renewal grace."""
    configured = getattr(panel, "expected_retention_days", None)
    return max(GRACE_DAYS, int(configured)) if configured else GRACE_DAYS


def evaluate(
    settings: dict, *, policy: str, connected: bool, webhook_url: str | None, sub_base_url: str | None, retention: int = GRACE_DAYS
) -> list[dict]:
    """All findings for one panel from its settings. Pure: no I/O, no secrets in the output."""
    return [
        evaluate_webhook(settings.get("webhook"), connected=connected, url=webhook_url),
        evaluate_subscription(settings.get("subscription"), sub_base_url),
        evaluate_cleanup(settings.get("cleanup"), policy, retention),
        evaluate_hwid(settings.get("hwid")),
        evaluate_notifications(settings),
    ]


def verdict(findings: list[dict], *, policy: str, now) -> dict:
    return {
        "checked_at": now.isoformat(),
        "policy": policy,
        "drifting": sum(1 for f in findings if f["state"] == "drift"),
        "findings": findings,
        "error": None,
    }


def _public_webhook_url(panel: Panel) -> str | None:
    try:
        from melorin.modules.vpn.panel_events_admin import webhook_url

        return webhook_url(panel)
    except AppError:
        return None


async def check_panel(panel: Panel, adapter, *, now=None) -> dict:
    """Read ``panel``'s settings and store the verdict (the caller commits). A failed read keeps the previous findings and only notes the
    error, so a panel outage can never look like "drift fixed" or invent drift. Returns the stored verdict."""
    now = now or utcnow()
    previous = panel.settings_drift if isinstance(panel.settings_drift, dict) else None
    if not (panel_caps.capabilities_of(panel).has("settings_ops") and supports(adapter, "settings_ops")):
        out = {
            "checked_at": now.isoformat(),
            "policy": panel.expired_cleanup_policy,
            "drifting": 0,
            "findings": [],
            "error": "settings_unreadable",
        }
        panel.settings_drift, panel.settings_drift_at = out, now
        return out
    try:
        settings = await adapter.get_settings()
    except PanelError as exc:
        out = {**(previous or {"findings": [], "drifting": 0, "policy": panel.expired_cleanup_policy}), "error": exc.message[:200]}
        panel.settings_drift = out  # ``settings_drift_at`` keeps the time of the last SUCCESSFUL read
        return out
    cfg = panel.config or {}
    findings = evaluate(
        settings if isinstance(settings, dict) else {},
        policy=panel.expired_cleanup_policy if panel.expired_cleanup_policy in POLICIES else "keep",
        connected=panel.webhook_connected_at is not None,
        webhook_url=_public_webhook_url(panel),
        sub_base_url=cfg.get("sub_base_url"),
        retention=retention_days(panel),
    )
    out = verdict(findings, policy=panel.expired_cleanup_policy, now=now)
    panel.settings_drift, panel.settings_drift_at = out, now
    return out


async def run_all(session: AsyncSession, *, close_adapter) -> int:
    """Worker entry: check every enabled PasarGuard panel; announce a panel that starts (or stops) drifting once."""
    from melorin.modules.eventcenter import rules as event_center_rules
    from melorin.modules.vpn.adapters.registry import build_adapter

    done = 0
    panels = (await session.scalars(select(Panel).where(Panel.is_enabled.is_(True), Panel.kind == "pasarguard"))).all()
    for panel in panels:
        before = int((panel.settings_drift or {}).get("drifting") or 0)
        adapter = None
        try:
            adapter = build_adapter(panel)
            after = (await check_panel(panel, adapter))["drifting"]
            done += 1
            await event_center_rules.notify_settings_drift(session, panel, before, after)
        except Exception:
            log.warning("settings drift check failed panel=%s", panel.id, exc_info=True)
        finally:
            if adapter is not None:
                try:
                    await close_adapter(adapter)
                except Exception:
                    log.warning("settings drift: adapter close failed panel=%s", panel.id, exc_info=True)
    return done


async def set_policy(
    session: AsyncSession, panel_id: uuid.UUID, policy: str, *, actor_id: uuid.UUID, reason: str, retention_days: int | None = None
) -> dict:
    """Admin choice of the lifecycle policy (audited). It changes Melorin's expectation only; nothing is written to the panel."""
    if policy not in POLICIES:
        raise AppError("BAD_POLICY", "سیاست نامعتبر است.", 400)
    if retention_days is not None and not GRACE_DAYS <= retention_days <= MAX_RETENTION_DAYS:
        raise AppError("BAD_RETENTION", f"مدت نگهداری باید بین {GRACE_DAYS} (مهلت تمدید) و {MAX_RETENTION_DAYS} روز باشد.", 400)
    panel = await session.get(Panel, panel_id)
    if not panel:
        raise NotFound("پنل")
    if panel.kind != "pasarguard":
        raise AppError("NOT_PASARGUARD", "این سیاست فقط برای پنل پاسارگارد معنا دارد.", 409)
    old, panel.expired_cleanup_policy = panel.expired_cleanup_policy, policy
    old_days = panel.expected_retention_days
    # only ``aligned`` has a retention; ``keep`` clears it (panel auto-delete is expected OFF)
    panel.expected_retention_days = retention_days if policy == "aligned" else None
    audit.record(
        session, "panel.cleanup_policy_changed", actor_id=actor_id, actor_type="admin", entity_type="panel", entity_id=panel.id,
        data={"from": old, "to": policy, "reason": reason[:300], "retention_days_from": old_days, "retention_days_to": panel.expected_retention_days},
    )  # fmt: skip
    await session.commit()
    return await recheck(session, panel_id, actor_id=None)


async def recheck(session: AsyncSession, panel_id: uuid.UUID, *, actor_id: uuid.UUID | None) -> dict:
    """On-demand read-only check (admin button). Returns ``describe(panel)``."""
    from melorin.modules.vpn.adapters.registry import build_adapter

    panel = await session.get(Panel, panel_id)
    if not panel:
        raise NotFound("پنل")
    if panel.kind != "pasarguard":
        raise AppError("NOT_PASARGUARD", "کنترل رانش تنظیمات فقط برای پنل پاسارگارد است.", 409)
    adapter = None
    try:
        adapter = build_adapter(panel)
        await check_panel(panel, adapter)
    except Exception as exc:
        log.warning("settings drift check failed panel=%s", panel.id, exc_info=True)
        previous = panel.settings_drift if isinstance(panel.settings_drift, dict) else {"findings": [], "drifting": 0}
        panel.settings_drift = {**previous, "error": (getattr(exc, "message", None) or str(exc) or exc.__class__.__name__)[:200]}
    finally:
        close = getattr(adapter, "close", None)
        if callable(close):
            res = close()
            if hasattr(res, "__await__"):
                await res
    if actor_id is not None:
        audit.record(
            session, "panel.settings_drift_checked", actor_id=actor_id, actor_type="admin", entity_type="panel", entity_id=panel.id,
            data={"drifting": (panel.settings_drift or {}).get("drifting", 0)},
        )  # fmt: skip
    await session.commit()
    return describe(panel)


def describe(panel: Panel) -> dict:
    """What the admin API returns: the policy, its meaning and the last verdict."""
    drift = panel.settings_drift if isinstance(panel.settings_drift, dict) else None
    return {
        "panel_id": panel.id,
        "policy": panel.expired_cleanup_policy,
        "policies": [{"value": p, "label": POLICY_LABELS[p]} for p in POLICIES],
        "grace_days": GRACE_DAYS,
        "expected_retention_days": retention_days(panel) if panel.expired_cleanup_policy == "aligned" else None,
        "checked_at": panel.settings_drift_at,
        "drifting": int((drift or {}).get("drifting") or 0),
        "findings": (drift or {}).get("findings") or [],
        "error": (drift or {}).get("error"),
    }
