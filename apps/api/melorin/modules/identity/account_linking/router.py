"""User-facing API of linking (``/identity``). Thin: the rules live in ``linking`` / ``telegram`` / ``consolidation``."""

from fastapi import APIRouter, Request, Response

from melorin.core.deps import CurrentUser, Session, main_store
from melorin.core.errors import AppError
from melorin.core.ratelimit import hit
from melorin.modules.identity import google as google_signin
from melorin.modules.identity import service
from melorin.modules.identity.account_linking import consolidation, linking, persons, queries, reauth, telegram
from melorin.modules.identity.account_linking.schemas import (
    ConfirmIn,
    ConsolidationIn,
    EmailConfirmIn,
    EmailStartIn,
    GoogleLinkIn,
    RejectIn,
    TelegramStartOut,
    UnlinkIn,
)
from melorin.modules.identity.routes._common import GOOGLE_NONCE_COOKIE, GOOGLE_NONCE_PATH

router = APIRouter(prefix="/identity", tags=["identity-linking"])


async def _limit(user: CurrentUser, what: str, limit: int = 10, window: int = 60) -> None:
    if not await hit(f"alink:{what}:{user.id}", limit, window):
        raise AppError("RATE_LIMITED", "درخواست‌ها زیاد است؛ کمی بعد دوباره امتحان کنید.", 429)


@router.get("/me")
async def my_profile(user: CurrentUser, session: Session):
    out = await queries.profile(session, user)
    await session.commit()  # a legacy account may have just received its person
    return out


@router.get("/linked-accounts")
async def linked_accounts(user: CurrentUser, session: Session):
    p = await queries.profile(session, user)
    await session.commit()
    return {"accounts": p["accounts"], "identities": p["identities"]}


@router.get("/link-operations")
async def link_operations(user: CurrentUser, session: Session):
    person = await persons.ensure_person(session, user)
    return await queries.operations(session, person.id)


@router.get("/history")
async def unified_orders(user: CurrentUser, session: Session, limit: int = 50, offset: int = 0):
    person = await persons.ensure_person(session, user)
    return await queries.orders(session, person.id, min(max(limit, 1), 100), max(offset, 0))


@router.post("/link/telegram/start", response_model=TelegramStartOut)
async def link_telegram_start(user: CurrentUser, session: Session):
    await _limit(user, "tg-start")
    op, raw = await telegram.start(session, user)
    store = await main_store(session)
    link = f"https://t.me/{store.bot_username}?start=link_{raw}" if store.bot_username else None
    await session.commit()
    return TelegramStartOut(operation_id=op.id, code=raw, expires_in=600, replace=op.operation_type == "replace", telegram_deeplink=link)


@router.post("/link/google")
async def link_google(body: GoogleLinkIn, user: CurrentUser, session: Session, request: Request, response: Response):
    """Complete a Google link. Same nonce-cookie binding as Google sign-in (``GET /auth/google/nonce`` is the *start*)."""
    await _limit(user, "google")
    cookies = getattr(request, "cookies", None) or {}
    outcome = await google_signin.link_google(session, user, body.id_token, cookies.get(GOOGLE_NONCE_COOKIE))
    response.delete_cookie(GOOGLE_NONCE_COOKIE, path=GOOGLE_NONCE_PATH)
    return {"ok": True, "outcome": outcome}


@router.post("/link/email/start")
async def link_email_start(body: EmailStartIn, user: CurrentUser, session: Session):
    await _limit(user, "email-start", 5, 300)
    dev_code = await service.request_email_code(session, str(body.email))
    return {"ok": True, "expires_in": 600, **({"dev_code": dev_code} if dev_code else {})}


@router.post("/link/email/confirm")
async def link_email_confirm(body: EmailConfirmIn, user: CurrentUser, session: Session):
    await _limit(user, "email-confirm")
    await service.attach_email(session, user, str(body.email), body.code)
    return {"ok": True}


@router.post("/link/confirm")
async def link_confirm(body: ConfirmIn, user: CurrentUser, session: Session):
    await _limit(user, "confirm", 10, 300)
    return await linking.confirm_person_link(session, user, body.operation_id, keep_telegram=body.keep_telegram)


@router.post("/link/reject")
async def link_reject(body: RejectIn, user: CurrentUser, session: Session):
    return await linking.reject_operation(session, user, body.operation_id)


@router.get("/reauth")
async def reauth_method(user: CurrentUser, session: Session):
    """Which proof a sensitive change needs: ``password`` | ``email_code`` | ``google`` | ``telegram_code`` | ``session``."""
    return {"method": await reauth.method_for(session, user)}


@router.post("/reauth/email/start")
async def reauth_email_start(user: CurrentUser, session: Session):
    await _limit(user, "reauth-start", 5, 300)
    dev_code = await reauth.start_email_code(session, user)
    return {"ok": True, "expires_in": 600, **({"dev_code": dev_code} if dev_code else {})}


@router.post("/reauth/telegram/start")
async def reauth_telegram_start(user: CurrentUser, session: Session):
    await _limit(user, "reauth-start", 5, 300)
    dev_code = await reauth.start_telegram_code(session, user)
    return {"ok": True, "expires_in": 600, **({"dev_code": dev_code} if dev_code else {})}


@router.post("/unlink")
async def unlink(body: UnlinkIn, user: CurrentUser, session: Session, request: Request, response: Response):
    await _limit(user, "unlink", 10, 300)
    await reauth.require(
        session,
        user,
        password=body.current_password,
        code=body.reauth_code,
        google_id_token=body.google_id_token,
        google_nonce=(getattr(request, "cookies", None) or {}).get(GOOGLE_NONCE_COOKIE),
    )
    response.delete_cookie(GOOGLE_NONCE_COOKIE, path=GOOGLE_NONCE_PATH)  # the nonce is single use
    return await linking.unlink_identity(session, user, body.identity_id)


@router.post("/consolidation")
async def request_consolidation(body: ConsolidationIn, user: CurrentUser, session: Session):
    await _limit(user, "consolidate", 5, 300)
    op = await consolidation.request(session, user, key=body.idempotency_key)
    await session.commit()
    return queries.consolidation_card(op)


@router.get("/consolidation-status")
async def consolidation_status(user: CurrentUser, session: Session):
    person = await persons.ensure_person(session, user)
    return await queries.consolidations(session, person.id)
