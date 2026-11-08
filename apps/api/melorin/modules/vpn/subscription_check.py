"""Subscription consistency test (PG-13).

The subscription address lives in three places: the panel's ``settings.subscription.url_prefix``, Melorin's ``config.sub_base_url``
and each store admin's ``sub_domain``. A mismatch gives broken links or wrong branding. This test reads those, takes a real account's
subscription link (nothing is created on the panel), checks it, fetches its public ``/info`` page and stores a verdict on the panel.

Checks (each ``ok | warn | fail | skip``): ``prefix`` (panel prefix vs Melorin's ``sub_base_url``), ``link_prefix`` (a real account link starts
with the panel prefix), ``reachable`` (``/info`` answers 200), ``store_domains`` (store admins' ``sub_domain`` hosts differ from the prefix
host: informational). The fetch only ever goes to hosts Melorin was configured with (SSRF guard in the adapter)."""

from __future__ import annotations

import logging
import uuid
from urllib.parse import urlsplit

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from melorin.core import audit
from melorin.core.db import utcnow
from melorin.core.errors import AppError, NotFound
from melorin.domain.order_state import VpnStatus
from melorin.kernel.models.vpn import Panel, PanelAdmin, VpnAccount
from melorin.modules.vpn.adapters.base import PanelError, supports
from melorin.modules.vpn.adapters.registry import build_adapter

log = logging.getLogger("melorin.vpn.subscription_check")


def _host(url: str | None) -> str:
    return (urlsplit(url or "").hostname or "").lower()


def _origin(url: str | None) -> str:
    parts = urlsplit((url or "").strip())
    return f"{parts.scheme}://{parts.netloc}".lower().rstrip("/") if parts.scheme and parts.netloc else ""


def _sub_domain_host(profile: dict | None) -> str:
    """Host of an admin's ``sub_domain`` profile value (stored with or without a scheme)."""
    raw = str((profile or {}).get("sub_domain") or "").strip()
    if not raw:
        return ""
    return _host(raw if "://" in raw else f"https://{raw}")


def check(name: str, state: str, message: str, **extra) -> dict:
    return {"name": name, "state": state, "message": message, **extra}


def evaluate(
    *, panel_prefix: str | None, sub_base_url: str | None, link: str | None, probe: dict | None, store_domains: list[str]
) -> list[dict]:
    """Pure verdict from what was read; no I/O. ``probe`` is the adapter's ``{ok, status, error}`` or ``None`` when no link was probed."""
    out: list[dict] = []
    p, b = _origin(panel_prefix), _origin(sub_base_url)
    if not p:
        out.append(check("prefix", "warn", "پنل آدرس پایهٔ اشتراک (url_prefix) را تنظیم نکرده است."))
    elif not b:
        out.append(check("prefix", "ok", "sub_base_url در ملورین تنظیم نشده؛ آدرس پایهٔ پنل استفاده می‌شود.", panel=p))
    elif p == b:
        out.append(check("prefix", "ok", "آدرس اشتراک پنل و ملورین یکی است.", panel=p, melorin=b))
    else:
        out.append(
            check("prefix", "fail", "آدرس اشتراک پنل با sub_base_url ملورین یکی نیست؛ لینک‌ها خراب یا ناهماهنگ می‌شوند.", panel=p, melorin=b)
        )
    if not link:
        out.append(check("link_prefix", "skip", "اکانت واقعی برای آزمایش لینک وجود ندارد."))
        out.append(check("reachable", "skip", "بدون لینک، دسترسی‌پذیری آزمایش نشد."))
    else:
        expected = p or b
        if expected and not link.lower().startswith(expected):
            out.append(
                check(
                    "link_prefix",
                    "fail",
                    "لینک اشتراک اکانت با آدرس پایهٔ پنل شروع نمی‌شود (احتمالاً دامنه عوض شده و لینک‌های قدیمی مانده‌اند).",
                    expected=expected,
                )
            )
        else:
            out.append(check("link_prefix", "ok", "لینک اشتراک با آدرس پایه می‌خواند."))
        if probe is None:
            out.append(check("reachable", "skip", "این اتصال آزمایش لینک را پشتیبانی نمی‌کند."))
        elif probe.get("ok"):
            out.append(check("reachable", "ok", "صفحهٔ اطلاعات اشتراک پاسخ ۲۰۰ داد."))
        else:
            out.append(check("reachable", "fail", f"صفحهٔ اطلاعات اشتراک در دسترس نیست ({probe.get('error') or probe.get('status')})."))
    odd = sorted({d for d in store_domains if d and p and d != _host(p)})
    if odd:
        out.append(
            check(
                "store_domains",
                "warn",
                "برخی ادمین‌های فروشگاه sub_domain جدا دارند؛ مطمئن شوید این دامنه‌ها به پنل اشاره می‌کنند.",
                domains=odd[:10],
            )
        )
    else:
        out.append(check("store_domains", "ok", "دامنهٔ اشتراک ویژه‌ای برای فروشگاه‌ها تنظیم نشده یا با پنل یکی است."))
    return out


def verdict(checks: list[dict]) -> str:
    states = {c["state"] for c in checks}
    return "fail" if "fail" in states else ("warn" if "warn" in states else "ok")


async def run(session: AsyncSession, panel_id: uuid.UUID, *, actor_id: uuid.UUID | None) -> dict:
    panel = await session.get(Panel, panel_id)
    if not panel:
        raise NotFound("پنل")
    if panel.kind != "pasarguard":
        raise AppError("CHECK_NOT_SUPPORTED", "آزمایش اشتراک فعلاً فقط برای پنل پاسارگارد است.", 409)
    adapter = build_adapter(panel)
    result: dict
    try:
        if not supports(adapter, "subscription_probe"):
            raise AppError("CAPABILITY_MISSING", "اتصال این پنل اجازهٔ خواندن تنظیمات اشتراک را ندارد (settings.read).", 409)
        try:
            settings = await adapter.get_subscription_settings()
        except PanelError as exc:
            raise AppError("PANEL_ERROR", f"پنل پاسخ نداد: {exc.message[:200]}", 502) from exc
        prefix = str(settings.get("url_prefix") or "").strip() or None
        sub_base = str((panel.config or {}).get("sub_base_url") or "").strip() or None
        recent = (
            await session.scalars(
                select(VpnAccount)
                .where(
                    VpnAccount.panel_id == panel.id,
                    VpnAccount.status.in_([VpnStatus.ACTIVE, VpnStatus.SUSPENDED, VpnStatus.LIMITED]),
                    VpnAccount.delivery_snapshot.is_not(None),
                )
                .order_by(VpnAccount.created_at.desc())
                .limit(20)
            )
        ).all()
        # a link as DELIVERED is all the format check needs (prefix, scheme, reachability); it is not read as the account's state
        account = next((a for a in recent if (a.delivery_snapshot or {}).get("subscription_url")), None)
        link = (account.delivery_snapshot or {}).get("subscription_url") if account else None
        if link and link.startswith("/"):  # relative link: the panel joins it with the prefix
            link = (prefix or sub_base or "").rstrip("/") + link
        allowed = {h for h in (_host(prefix), _host(sub_base), _host(panel.base_url)) if h}
        probe = await adapter.probe_subscription(link, allowed_hosts=allowed) if link else None
        domains = [
            _sub_domain_host(a.profile) for a in (await session.scalars(select(PanelAdmin).where(PanelAdmin.panel_id == panel.id))).all()
        ]
        checks = evaluate(panel_prefix=prefix, sub_base_url=sub_base, link=link, probe=probe, store_domains=[d for d in domains if d])
        result = {
            "verdict": verdict(checks),
            "checks": checks,
            "panel_prefix": prefix,
            "sub_base_url": sub_base,
            "tested_account": account.username if account else None,
        }
    finally:
        close = getattr(adapter, "close", None)
        if callable(close):
            res = close()
            if hasattr(res, "__await__"):
                await res
    panel.subscription_check, panel.subscription_checked_at = result, utcnow()
    audit.record(
        session, "panel.subscription_checked", actor_id=actor_id, actor_type="admin", entity_type="panel", entity_id=panel.id,
        data={"verdict": result["verdict"]},
    )  # fmt: skip
    await session.commit()
    return result
