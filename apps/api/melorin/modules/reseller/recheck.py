"""Continuous identity re-verification of approved reseller stores (docs/21).

Proving the domain and the bot once, at filing time, is not enough: a domain can be sold or lapse, a bot token can be
revoked or leaked. Every approved store whose application proved its domain is re-checked on a schedule:

* domain proof (DNS TXT or well-known file) must still be there;
* the bot token stored for the store must still be accepted by Telegram and still belong to the same bot.

A single failed round proves nothing (DNS hiccups happen): the owner gets a gentle warning and the check repeats every
6 hours. After ``RESELLER_RECHECK_FAIL_LIMIT`` consecutive failed rounds the identity counts as **lost**: admins are
alerted and, only when ``RESELLER_RECHECK_SUSPEND=true``, the store is suspended. Recovery clears the state, notifies
admins and never un-suspends by itself (that stays an admin decision). Telegram being unreachable is neutral.
"""

from __future__ import annotations

import datetime as dt
import logging

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from melorin.core import audit, events
from melorin.core.config import get_settings
from melorin.core.crypto import decrypt
from melorin.core.db import utcnow
from melorin.core.errors import AppError
from melorin.kernel.models.stores import ResellerApplication, Store

log = logging.getLogger("melorin.reseller.recheck")

BATCH = 50
RETRY_AFTER_FAILURE = dt.timedelta(hours=6)
RETRY_AFTER_UNREACHABLE = dt.timedelta(hours=1)


async def check(
    session: AsyncSession, a: ResellerApplication, store: Store, *, transport=None, dns_transport=None
) -> tuple[list[str], bool]:
    """(definite failures, telegram_unreachable). Pure checks, no state change."""
    from melorin.modules.reseller import auto_verify, identity

    errors: list[str] = []
    if a.domain and a.domain_verified_at is not None:
        value = auto_verify.challenge_value(a.id, a.domain)
        if not (
            await auto_verify.check_dns(a.domain, value, transport=dns_transport)
            or await auto_verify.check_http(a.domain, value, transport=transport)
        ):
            errors.append("domain_proof_missing")
    unreachable = False
    if store.bot_token_enc:
        try:
            username = await identity.verify_bot(decrypt(store.bot_token_enc), transport=transport)
        except AppError:
            errors.append("bot_rejected")
        else:
            if username is None:
                unreachable = True
            elif store.bot_username and username.lower() != store.bot_username.lower():
                errors.append("bot_changed")
    return errors, unreachable


async def _notify_owner(session: AsyncSession, a: ResellerApplication, *, title: str, body: str, key: str) -> None:
    await events.emit(
        session,
        events.NOTIFY,
        {"user_id": a.user_id, "store_id": a.target_store_id, "kind": "reseller_identity", "title": title, "body": body, "dedup_key": key},
    )


async def recheck_one(session: AsyncSession, a: ResellerApplication, *, transport=None, dns_transport=None) -> str:
    """Re-verify one approved store and reschedule. Returns ``ok`` | ``warn`` | ``lost`` | ``unreachable`` | ``skipped``."""
    from melorin.modules.reseller import onboarding

    s = get_settings()
    now = utcnow()
    store = await session.get(Store, a.store_id) if a.store_id else None
    if store is None:
        a.recheck_next_at = None
        return "skipped"
    errors, unreachable = await check(session, a, store, transport=transport, dns_transport=dns_transport)
    interval = dt.timedelta(hours=max(1, int(s.reseller_recheck_hours)))

    if errors:
        a.recheck_failures = (a.recheck_failures or 0) + 1
        a.recheck_error = ",".join(errors)[:200]
        a.recheck_next_at = now + RETRY_AFTER_FAILURE
        limit = max(1, int(s.reseller_recheck_fail_limit))
        if a.recheck_failures >= limit and a.identity_lost_at is None:
            a.identity_lost_at = now
            suspended = False
            if s.reseller_recheck_suspend and store.status == "active":
                store.status, suspended = "suspended", True
            audit.record(
                session,
                "reseller.identity_lost",
                actor_type="system",
                entity_type="reseller_application",
                entity_id=a.id,
                data={"errors": errors, "failures": a.recheck_failures, "suspended": suspended, "store_id": str(store.id)},
            )
            await onboarding.alert_admins(
                session,
                kind="admin_reseller_identity_lost",
                title="⚠️ هویت یک نماینده دیگر قابل اثبات نیست",
                body=f"«{store.name}» ({a.domain}): {a.recheck_error} - {a.recheck_failures} بررسی پیاپی ناموفق."
                + (" فروشگاه تعلیق شد." if suspended else ""),
                key=f"reseller_identity_lost:{a.id}",
            )
            await _notify_owner(
                session,
                a,
                title="⚠️ هویت فروشگاه شما تأیید نمی‌شود",
                body="رکورد/فایل تأیید دامنه یا دسترسی ربات شما دیگر معتبر نیست. آن را اصلاح کنید؛ بررسی بعدی خودکار است.",
                key=f"reseller_identity_lost_owner:{a.id}",
            )
            return "lost"
        if a.recheck_failures == 1:
            await _notify_owner(
                session,
                a,
                title="⚠️ تأیید دامنه یا ربات شما پیدا نشد",
                body=f"بررسی خودکار هویت فروشگاه «{store.name}» ناموفق بود ({a.recheck_error}). تا چند ساعت دیگر دوباره بررسی می‌شود؛ اگر تغییری داده‌اید اصلاح کنید.",
                key=f"reseller_identity_warn:{a.id}:{now.date().isoformat()}",
            )
        return "warn" if a.identity_lost_at is None else "lost"

    if unreachable:  # Telegram down: neither proof nor failure
        a.recheck_next_at = now + RETRY_AFTER_UNREACHABLE
        return "unreachable"

    recovered = a.identity_lost_at is not None
    a.recheck_failures, a.recheck_error, a.identity_lost_at, a.recheck_next_at = 0, None, None, now + interval
    if recovered:
        audit.record(
            session,
            "reseller.identity_recovered",
            actor_type="system",
            entity_type="reseller_application",
            entity_id=a.id,
            data={"store_id": str(store.id)},
        )
        await onboarding.alert_admins(
            session,
            kind="admin_reseller_identity_recovered",
            title="✅ هویت نماینده دوباره تأیید شد",
            body=f"«{store.name}» ({a.domain}): دامنه و ربات دوباره معتبر است."
            + (" فروشگاه همچنان تعلیق است؛ تصمیم با شماست." if store.status == "suspended" else ""),
            key=f"reseller_identity_recovered:{a.id}:{now.date().isoformat()}",
        )
    return "ok"


async def sweep(session: AsyncSession, *, transport=None, dns_transport=None) -> int:
    """Re-verify every approved, active store whose check is due. Returns how many were processed."""
    if not get_settings().reseller_recheck:
        return 0
    rows = (
        await session.scalars(
            select(ResellerApplication)
            .join(Store, Store.id == ResellerApplication.store_id)
            .where(
                ResellerApplication.status == "approved",
                ResellerApplication.recheck_next_at.is_not(None),
                ResellerApplication.recheck_next_at <= utcnow(),
                Store.status == "active",
            )
            .order_by(ResellerApplication.recheck_next_at)
            .limit(BATCH)
            .with_for_update(of=ResellerApplication, skip_locked=True)
        )
    ).all()
    for a in rows:
        try:
            await recheck_one(session, a, transport=transport, dns_transport=dns_transport)
        except (httpx.HTTPError, Exception):  # one broken store must not stop the others
            log.exception("identity recheck failed application=%s", a.id)
            a.recheck_next_at = utcnow() + RETRY_AFTER_UNREACHABLE
    await session.commit()
    return len(rows)
