"""Admin API - reseller applications routes (split from the former 1,900-line router; paths unchanged)."""

import logging
import uuid
from fastapi import APIRouter
from sqlalchemy import select
from melorin.core import audit
from melorin.core.deps import AdminUser, Session
from melorin.core.errors import AppError, NotFound
from melorin.kernel.models.identity import User
from melorin.kernel.models.stores import ResellerApplication, ResellerProfile, Store, StoreMembership
from melorin.modules.admin.schemas import (
    ResellerApproval,
)

router = APIRouter(prefix="/admin", tags=["admin"])
log = logging.getLogger("melorin.admin")


# ----- Resellers, flags, audit -----
def _application_row(x, user, target):
    """Admin view of an application. The encrypted bot token is never serialised."""
    return {
        "id": x.id,
        "user_id": x.user_id,
        "user_email": user.email if user else None,
        "user_name": user.display_name if user else None,
        "target_store_id": x.target_store_id,
        "target_store_name": target.name if target else None,
        "store_name": x.store_name,
        "message": x.message,
        "status": x.status,
        "domain": x.domain,
        "bot_username": x.bot_username,
        "bot_verified": x.bot_verified,
        "has_bot_token": bool(x.bot_token_enc),
        "review_reason": x.review_reason,
        "reviewed_at": x.reviewed_at,
        "store_id": x.store_id,
        "created_at": x.created_at,
        "approved_debt_limit": x.approved_debt_limit,
    }


@router.get("/reseller-applications")
async def applications(_: AdminUser, session: Session, status: str | None = None):
    q = (
        select(ResellerApplication, User, Store)
        .join(User, User.id == ResellerApplication.user_id, isouter=True)
        .join(Store, Store.id == ResellerApplication.target_store_id, isouter=True)
    )
    if status:
        q = q.where(ResellerApplication.status == status)
    # Pending first (oldest first, so nobody waits behind newer requests), then history newest first.
    rows = (await session.execute(q.order_by(ResellerApplication.created_at))).all()
    rows.sort(key=lambda r: (r[0].status != "pending", r[0].created_at if r[0].status == "pending" else -r[0].created_at.timestamp()))
    return [_application_row(x, u, t) for x, u, t in rows]


@router.post("/reseller-applications/{application_id}/review")
async def review_application(application_id: uuid.UUID, body: ResellerApproval, admin: AdminUser, session: Session):
    from melorin.core import events
    from melorin.modules.reseller import identity
    from melorin.modules.reseller.provisioning import create_reseller_store

    a = await session.get(ResellerApplication, application_id, with_for_update=True)
    # ``awaiting_details`` (approved, domain/bot not supplied yet) can still be withdrawn by the admin, never approved twice.
    if not a or a.status not in ("pending", "awaiting_details"):
        raise NotFound("درخواست نمایندگی")
    if a.status == "awaiting_details" and body.approve:
        raise AppError("AWAITING_DETAILS", "این درخواست قبلاً تأیید شده و منتظر دامنه و توکن ربات از متقاضی است.", 409)
    reason = (body.reason or "").strip() or None
    if not body.approve and not reason:
        raise AppError("REASON_REQUIRED", "برای رد درخواست، دلیل را بنویسید تا متقاضی ببیند.", 400)
    has_details = bool(a.domain and a.bot_token_enc and a.bot_key)
    target = None
    if body.approve:
        target = await session.get(Store, a.target_store_id)
        if not target or target.status != "active":
            raise AppError("TARGET_STORE_INVALID", "فروشگاه مقصد نمایندگی فعال نیست.", 409)
        existing_store = await session.scalar(
            select(Store).where(Store.owner_user_id == a.user_id, Store.kind == "reseller", Store.parent_store_id == target.id)
        )
        if existing_store:
            raise AppError("RESELLER_EXISTS", "این کاربر برای این فروشگاه قبلاً نمایندگی دارد.", 409)
        member = await session.scalar(
            select(StoreMembership).where(
                StoreMembership.store_id == target.id, StoreMembership.user_id == a.user_id, StoreMembership.status == "active"
            )
        )
        if not member:
            raise AppError("STORE_MEMBERSHIP_REQUIRED", "متقاضی دیگر عضو فعال فروشگاه مقصد نیست.", 409)
        if has_details:
            await identity.ensure_identity_free(
                session, domain=a.domain, bot_key=a.bot_key, bot_username=a.bot_username, exclude_application_id=a.id
            )
    a.reviewed_by, a.reviewed_at = admin.id, __import__("datetime").datetime.now(__import__("datetime").UTC)
    a.review_reason = reason
    if body.approve and not has_details:
        # Two-step request (filed from Telegram): approve the request only. The domain and bot token are collected from
        # the applicant afterwards; the store is created when they arrive (reseller router, ``/details``).
        a.status, a.approved_debt_limit = "awaiting_details", body.debt_limit
        token_enc = None
    else:
        a.status = "approved" if body.approve else "rejected"
        token_enc, a.bot_token_enc = a.bot_token_enc, None  # the secret moves to the Store (approve) or is dropped (reject)
        if body.approve:
            await create_reseller_store(session, a, target, token_enc=token_enc, debt_limit=body.debt_limit)
    audit.record(
        session,
        "reseller.application_reviewed",
        actor_id=admin.id,
        actor_type="admin",
        entity_type="reseller_application",
        entity_id=a.id,
        data={
            "approve": body.approve,
            "status": a.status,
            "reason": reason,
            "debt_limit": body.debt_limit if body.approve else None,
            "domain": a.domain,
        },
    )
    if a.status == "awaiting_details":
        title, text = (
            "✅ درخواست نمایندگی شما تأیید شد",
            f"«{a.store_name}»: برای ادامه در ربات دستور /reseller را بزنید و دامنه و توکن رباتِ فروشگاه را بفرستید.",
        )
    elif a.status == "approved":
        title, text = "✅ درخواست نمایندگی شما تأیید شد", f"فروشگاه «{a.store_name}» ساخته شد. از «پنل نماینده» تنظیمات را ادامه دهید."
    else:
        title, text = "❌ درخواست نمایندگی شما رد شد", f"«{a.store_name}»: {reason}"
    await events.emit(
        session,
        events.NOTIFY,
        {
            "user_id": a.user_id,
            "store_id": a.target_store_id,
            "kind": "reseller_application",
            "title": title,
            "body": text,
            "dedup_key": f"reseller_application:{a.id}:{a.status}",
        },
    )
    await session.commit()
    return {"ok": True, "status": a.status, "store_id": a.store_id}


@router.post("/reseller-applications/{application_id}/verify-bot")
async def verify_application_bot(application_id: uuid.UUID, admin: AdminUser, session: Session):
    """Re-ask Telegram about the bot of a pending application (the first check may have failed to reach Telegram)."""
    from melorin.core.crypto import decrypt
    from melorin.modules.reseller import identity

    a = await session.get(ResellerApplication, application_id, with_for_update=True)
    if not a or a.status != "pending" or not a.bot_token_enc:
        raise NotFound("درخواست نمایندگی")
    username = await identity.verify_bot(decrypt(a.bot_token_enc))
    if username is None:
        raise AppError("TELEGRAM_UNREACHABLE", "ارتباط با تلگرام برقرار نشد؛ کمی بعد دوباره تلاش کنید.", 503)
    a.bot_username, a.bot_verified = username, True
    audit.record(
        session,
        "reseller.application_bot_verified",
        actor_id=admin.id,
        actor_type="admin",
        entity_type="reseller_application",
        entity_id=a.id,
        data={"bot_username": username},
    )
    await session.commit()
    user = await session.get(User, a.user_id)
    return _application_row(a, user, await session.get(Store, a.target_store_id))


@router.put("/reseller-stores/{store_id}/api")
async def toggle_reseller_api(store_id: uuid.UUID, enabled: bool, admin: AdminUser, session: Session):
    p = await session.scalar(select(ResellerProfile).where(ResellerProfile.store_id == store_id))
    if not p:
        raise NotFound("فروشگاه نماینده")
    p.api_enabled = enabled
    audit.record(
        session,
        "reseller.api_toggled",
        actor_id=admin.id,
        actor_type="admin",
        entity_type="reseller_store",
        entity_id=store_id,
        store_id=store_id,
        data={"enabled": enabled},
    )
    await session.commit()
    return {"store_id": store_id, "api_enabled": enabled}
