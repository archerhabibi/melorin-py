"""Reseller applications: a customer asks the main store for a reseller store, and finishes the request after approval."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from melorin.core import audit, channel
from melorin.core.crypto import encrypt
from melorin.core.deps import CurrentAuth, Session, main_store
from melorin.core.errors import AppError, NotFound
from melorin.kernel.models.identity import User
from melorin.kernel.models.stores import ResellerApplication, ResellerProfile, Store, StoreMembership
from melorin.modules.reseller import identity
from melorin.modules.reseller.schemas import (
    ApplicationDetailsIn,
    ApplicationIn,
)

router = APIRouter(tags=["reseller"])


async def main_session_user(auth: CurrentAuth, session: Session):
    """Reseller applications are made to the MAIN store: only a session opened through the main site/bot may file or read them."""
    main = await main_store(session)
    if not auth.claims.is_admin and auth.claims.store_id != main.id:
        raise channel.mismatch()
    return auth.user


async def application_target_store(session, user_id, target_store_id):
    """Resolve the represented store and require active membership in that store.

    Missing target is kept backwards-compatible by selecting Main Store. New
    clients should always send target_store_id so a user can apply to several
    stores independently.
    """
    target = await session.get(Store, target_store_id) if target_store_id else await main_store(session)
    if not target or target.status != "active":
        raise NotFound("فروشگاه مقصد نمایندگی")
    membership = await session.scalar(
        select(StoreMembership).where(
            StoreMembership.store_id == target.id,
            StoreMembership.user_id == user_id,
            StoreMembership.status == "active",
        )
    )
    if not membership:
        raise AppError("STORE_MEMBERSHIP_REQUIRED", "برای درخواست نمایندگی باید عضو فعال همان فروشگاه باشید.", 403)
    return target


def application_out(a: ResellerApplication) -> dict:
    """Applicant-facing view. The bot token is never included."""
    return {
        "id": a.id,
        "target_store_id": a.target_store_id,
        "store_name": a.store_name,
        "message": a.message,
        "status": a.status,
        "needs_details": a.status == "awaiting_details",
        "domain": a.domain,
        "bot_username": a.bot_username,
        "bot_verified": a.bot_verified,
        "review_reason": a.review_reason if a.status == "rejected" else None,
        "store_id": a.store_id,
        "created_at": a.created_at,
    }


@router.post("/reseller/applications")
async def apply(body: ApplicationIn, user: Annotated[User, Depends(main_session_user)], session: Session):
    target = await application_target_store(session, user.id, body.target_store_id)
    if await session.scalar(
        select(ResellerProfile.id).where(
            ResellerProfile.user_id == user.id, ResellerProfile.store_id.in_(select(Store.id).where(Store.parent_store_id == target.id))
        )
    ):
        raise AppError("ALREADY_RESELLER", "شما برای این فروشگاه قبلاً نماینده هستید.", 409)
    if await session.scalar(
        select(ResellerApplication).where(
            ResellerApplication.user_id == user.id,
            ResellerApplication.target_store_id == target.id,
            ResellerApplication.status.in_(("pending", "awaiting_details")),
        )
    ):
        raise AppError("APPLICATION_EXISTS", "یک درخواست در حال بررسی دارید.", 409)
    domain = bot_key = username = token = None
    if body.domain is not None:  # one-step (web form): identity is validated now
        domain = identity.normalize_domain(body.domain)
        token, bot_key = identity.parse_bot_token(body.bot_token)
        await identity.ensure_identity_free(session, domain=domain, bot_key=bot_key)
        username = await identity.verify_bot(token)
        if username:
            await identity.ensure_identity_free(session, domain=domain, bot_key=bot_key, bot_username=username)
    a = ResellerApplication(
        user_id=user.id,
        target_store_id=target.id,
        store_name=body.store_name.strip(),
        message=body.message,
        domain=domain,
        bot_token_enc=encrypt(token) if token else None,
        bot_key=bot_key,
        bot_username=username,
        bot_verified=username is not None,
    )
    session.add(a)
    audit.record(
        session,
        "reseller.applied",
        actor_id=user.id,
        entity_type="reseller_application",
        entity_id=a.id,
        data={"domain": domain, "bot_key": bot_key, "two_step": domain is None},
    )
    await session.commit()
    return application_out(a)


@router.get("/reseller/applications")
async def my_applications(user: Annotated[User, Depends(main_session_user)], session: Session):
    rows = (
        await session.scalars(
            select(ResellerApplication)
            .where(ResellerApplication.user_id == user.id)
            .order_by(ResellerApplication.created_at.desc())
            .limit(50)
        )
    ).all()
    return [application_out(a) for a in rows]


@router.post("/reseller/applications/{application_id}/cancel")
async def cancel_application(application_id: uuid.UUID, user: Annotated[User, Depends(main_session_user)], session: Session):
    a = await session.get(ResellerApplication, application_id, with_for_update=True)
    if not a or a.user_id != user.id:
        raise NotFound("درخواست نمایندگی")
    if a.status not in ("pending", "awaiting_details"):
        raise AppError("APPLICATION_NOT_PENDING", "فقط درخواست در حال بررسی قابل لغو است.", 409)
    a.status, a.bot_token_enc = "cancelled", None
    audit.record(session, "reseller.application_cancelled", actor_id=user.id, entity_type="reseller_application", entity_id=a.id)
    await session.commit()
    return application_out(a)


@router.post("/reseller/applications/{application_id}/details")
async def submit_details(
    application_id: uuid.UUID, body: ApplicationDetailsIn, user: Annotated[User, Depends(main_session_user)], session: Session
):
    """Second step of a request the admin already approved: the applicant sends the store domain and the bot token,
    both are validated, and the reseller store is created right away (the admin approval is the authorisation)."""
    from melorin.modules.reseller.provisioning import create_reseller_store

    a = await session.get(ResellerApplication, application_id, with_for_update=True)
    if not a or a.user_id != user.id:
        raise NotFound("درخواست نمایندگی")
    if a.status != "awaiting_details":
        raise AppError("APPLICATION_NOT_AWAITING_DETAILS", "این درخواست در مرحلهٔ دریافت اطلاعات نیست.", 409)
    target = await application_target_store(session, user.id, a.target_store_id)
    if await session.scalar(
        select(Store.id).where(Store.owner_user_id == user.id, Store.kind == "reseller", Store.parent_store_id == target.id)
    ):
        raise AppError("ALREADY_RESELLER", "شما برای این فروشگاه قبلاً نماینده هستید.", 409)
    domain = identity.normalize_domain(body.domain)
    token, bot_key = identity.parse_bot_token(body.bot_token)
    await identity.ensure_identity_free(session, domain=domain, bot_key=bot_key, exclude_application_id=a.id)
    username = await identity.verify_bot(token)
    if username is None:  # Telegram unreachable: a store must not be created for a bot nobody has verified
        # 424 (not 5xx): the bot runner replays an update on 5xx, which would hammer Telegram while it is unreachable.
        raise AppError("TELEGRAM_UNREACHABLE", "ارتباط با تلگرام برقرار نشد؛ کمی بعد دوباره تلاش کنید.", 424)
    await identity.ensure_identity_free(session, domain=domain, bot_key=bot_key, bot_username=username, exclude_application_id=a.id)
    a.domain, a.bot_key, a.bot_username, a.bot_verified = domain, bot_key, username, True
    a.status = "approved"
    await create_reseller_store(session, a, target, token_enc=encrypt(token), debt_limit=a.approved_debt_limit or 0)
    audit.record(
        session,
        "reseller.application_details_submitted",
        actor_id=user.id,
        entity_type="reseller_application",
        entity_id=a.id,
        data={"domain": domain, "bot_key": bot_key, "bot_username": username},
    )
    try:
        await session.commit()
    except IntegrityError:  # another applicant took the same domain/bot between the check and the commit
        await session.rollback()
        raise AppError("IDENTITY_TAKEN", "این دامنه یا ربات همین الان برای فروشگاه دیگری ثبت شد؛ مقدار دیگری بفرستید.", 409) from None
    return application_out(a)
