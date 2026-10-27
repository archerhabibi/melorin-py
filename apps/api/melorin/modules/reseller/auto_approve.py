"""Automatic approval of a fully proven reseller application (docs/21).

An application that brought a Telegram bot **and** a domain, and for which Core has already proven both (bot ``getMe``,
DNS/HTTP domain control), carries no open question for an admin to answer except "do we want this reseller at all".
When the operator has decided that question in advance (``RESELLER_AUTO_APPROVE=true``) the approval happens by itself,
through exactly the same store-creation code as the manual path. It is **off by default** because it grants a store.

Guard rails (any one of them leaves the application for an admin, nothing is rejected automatically):
* only ``pending`` applications that have both a verified bot and a verified domain;
* the applicant is an active, non-guest, non-admin account older than ``RESELLER_AUTO_APPROVE_MIN_ACCOUNT_DAYS``;
* the target store is active, the applicant is still an active member, no reseller store exists for that pair yet;
* the domain and bot are still free (same check as the manual path);
* the debt limit is the fixed ``RESELLER_AUTO_APPROVE_DEBT_LIMIT`` (default 0: the reseller pays before it sells).
"""

from __future__ import annotations

import datetime as dt
import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from melorin.core import audit, events
from melorin.core.config import get_settings
from melorin.core.db import utcnow
from melorin.core.errors import AppError
from melorin.kernel.models.identity import User
from melorin.kernel.models.stores import ResellerApplication, Store, StoreMembership

log = logging.getLogger("melorin.reseller.auto_approve")


def _aware(value: dt.datetime) -> dt.datetime:
    return value.replace(tzinfo=value.tzinfo or dt.UTC)


async def blockers(session: AsyncSession, a: ResellerApplication) -> list[str]:
    """Reasons this application must wait for an admin. Empty list = safe to approve automatically."""
    s = get_settings()
    out: list[str] = []
    if not s.reseller_auto_approve:
        return ["disabled"]
    if a.status != "pending":
        return ["not_pending"]
    if not (a.domain and a.bot_token_enc and a.bot_key):
        out.append("details_missing")
    if not a.bot_verified:
        out.append("bot_unverified")
    if a.domain_verified_at is None:
        out.append("domain_unverified")
    user = await session.get(User, a.user_id)
    min_age = dt.timedelta(days=max(0, int(s.reseller_auto_approve_min_account_days)))
    if user is None or not user.is_active or user.is_guest or user.is_super_admin or user.admin_roles or user.archived_at:
        out.append("applicant_not_eligible")
    elif _aware(user.created_at) + min_age > utcnow():
        out.append("account_too_new")
    target = await session.get(Store, a.target_store_id)
    if target is None or target.status != "active":
        out.append("target_store_invalid")
    else:
        if await session.scalar(
            select(Store.id).where(Store.owner_user_id == a.user_id, Store.kind == "reseller", Store.parent_store_id == target.id)
        ):
            out.append("reseller_exists")
        if not await session.scalar(
            select(StoreMembership.id).where(
                StoreMembership.store_id == target.id, StoreMembership.user_id == a.user_id, StoreMembership.status == "active"
            )
        ):
            out.append("membership_missing")
    return out


async def try_approve(session: AsyncSession, a: ResellerApplication) -> bool:
    """Approve ``a`` by itself when every guard rail holds. Returns True when the store was created. Never raises."""
    from melorin.modules.reseller import identity

    try:
        if await blockers(session, a):
            return False
        await identity.ensure_identity_free(
            session, domain=a.domain, bot_key=a.bot_key, bot_username=a.bot_username, exclude_application_id=a.id
        )
        target = await session.get(Store, a.target_store_id)
        limit = max(0, int(get_settings().reseller_auto_approve_debt_limit))
        now = utcnow()
        async with session.begin_nested():  # all-or-nothing: a half-approved application is never left behind
            return await _approve(session, a, target, limit, now)
    except AppError:
        await session.refresh(a)
        return False  # identity taken in the meantime etc.: the admin sees the application and decides
    except Exception:
        log.exception("auto approve failed application=%s", a.id)
        await session.refresh(a)
        return False


async def _approve(session, a, target, limit, now) -> bool:
    from melorin.modules.reseller import onboarding
    from melorin.modules.reseller.provisioning import create_reseller_store

    a.status, a.auto_approved, a.reviewed_at, a.reviewed_by = "approved", True, now, None
    a.review_reason = "auto:fully_proven"
    token_enc, a.bot_token_enc = a.bot_token_enc, None
    await create_reseller_store(session, a, target, token_enc=token_enc, debt_limit=limit)
    a.recheck_next_at = now + dt.timedelta(hours=max(1, int(get_settings().reseller_recheck_hours)))
    await onboarding.complete_review_task(session, a, None)
    await onboarding.ensure_admin_tasks(session, a)
    audit.record(
        session,
        "reseller.application_auto_approved",
        actor_type="system",
        entity_type="reseller_application",
        entity_id=a.id,
        data={"domain": a.domain, "domain_method": a.domain_method, "debt_limit": limit, "store_id": str(a.store_id)},
    )
    await events.emit(
        session,
        events.NOTIFY,
        {
            "user_id": a.user_id,
            "store_id": a.target_store_id,
            "kind": "reseller_application",
            "title": "✅ درخواست نمایندگی شما تأیید شد",
            "body": f"فروشگاه «{a.store_name}» پس از تأیید خودکار هویت (ربات و دامنه) ساخته شد.\n\nکارهای بعدی شما:\n{onboarding.steps_text('approved', domain=a.domain)}",
            "dedup_key": f"reseller_application:{a.id}:approved",
        },
    )
    await onboarding.alert_admins(
        session,
        kind="admin_reseller_auto_approved",
        title="🤖 نمایندگی جدید به‌صورت خودکار تأیید شد",
        body=f"«{a.store_name}» ({a.domain}) با ربات و دامنهٔ اثبات‌شده، سقف بدهی {limit}. در صورت نیاز از «نمایندگان» تعلیق کنید.",
        key=f"reseller_auto_approved:{a.id}",
    )
    return True
