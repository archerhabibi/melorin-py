"""Sign in with Google (Google Identity Services): local ID-token verification, account linking and login.

Split out of ``identity/service.py`` in Phase 3.11 (behaviour unchanged). Tests patch the names in *this* module.
"""

import hmac
import uuid
import logging
import re
import time

import httpx
import jwt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from melorin.core import audit, integrations
from melorin.core.db import utcnow
from melorin.core.errors import AppError
from melorin.kernel.models.identity import Identity, IdentityLinkReview, User
from melorin.modules.identity import auto_link
from melorin.modules.identity.lookup import email_taken as _email_taken
from melorin.modules.identity.lookup import find_identity

log = logging.getLogger(__name__)

# Sign in with Google (Google Identity Services). The browser hands us a signed ID token (a JWT). Following Google's
# guidance we verify it locally against Google's published public keys instead of the debugging-only /tokeninfo
# endpoint: signature (RS256), issuer, audience (= our Client ID), expiry and - because the page binds every sign-in
# to a nonce cookie - the nonce claim, which stops a stolen/replayed token from being accepted.
GOOGLE_CERTS_URL = "https://www.googleapis.com/oauth2/v3/certs"
GOOGLE_ISSUERS = ("https://accounts.google.com", "accounts.google.com")
GOOGLE_CLOCK_SKEW = 30  # seconds of leeway for exp/iat
_GOOGLE_KEYS_MIN_TTL, _GOOGLE_KEYS_MAX_TTL, _GOOGLE_KEYS_MISS_COOLDOWN = 300, 86400, 60
_google_keys: dict = {"keys": {}, "expires": 0.0, "fetched": 0.0}


def _google_invalid() -> AppError:
    return AppError("GOOGLE_INVALID", "توکن Google نامعتبر است.", 401)


async def _load_google_keys(force: bool = False) -> dict:
    """Google's signing keys by ``kid``, cached for as long as Google's Cache-Control allows (clamped)."""
    now = time.time()
    if not force and _google_keys["keys"] and now < _google_keys["expires"]:
        return _google_keys["keys"]
    if force and now - _google_keys["fetched"] < _GOOGLE_KEYS_MISS_COOLDOWN and _google_keys["keys"]:
        return _google_keys["keys"]  # unknown kid: do not let a forged header make us hammer Google
    try:
        async with httpx.AsyncClient(timeout=10) as c:
            r = await c.get(GOOGLE_CERTS_URL)
        r.raise_for_status()
        jwks = r.json()
    except (httpx.HTTPError, ValueError) as exc:
        log.warning("google certs fetch failed: %s", type(exc).__name__)
        if _google_keys["keys"]:
            return _google_keys["keys"]  # keep verifying with the last known keys while Google is unreachable
        raise AppError("GOOGLE_UNREACHABLE", "اتصال سرور به Google برقرار نشد؛ کمی بعد دوباره تلاش کنید.", 503) from exc
    keys = {}
    for jwk in jwks.get("keys", []):
        if jwk.get("kid") and jwk.get("kty") == "RSA":
            keys[jwk["kid"]] = jwt.PyJWK(jwk, algorithm="RS256").key
    if not keys:
        raise AppError("GOOGLE_UNREACHABLE", "پاسخ کلیدهای Google نامعتبر بود.", 503)
    m = re.search(r"max-age=(\d+)", r.headers.get("cache-control", ""))
    ttl = min(max(int(m.group(1)) if m else 3600, _GOOGLE_KEYS_MIN_TTL), _GOOGLE_KEYS_MAX_TTL)
    _google_keys.update(keys=keys, expires=now + ttl, fetched=now)
    return keys


async def verify_google_token(id_token: str, client_id: str) -> dict:
    """Verify a Google ID token and return its claims. Raises GOOGLE_INVALID for any token we must not trust."""
    if not client_id:
        raise AppError("GOOGLE_DISABLED", "ورود با Google پیکربندی نشده است.", 400)
    try:
        header = jwt.get_unverified_header(id_token)
    except jwt.PyJWTError as exc:
        raise _google_invalid() from exc
    kid = header.get("kid")
    if header.get("alg") != "RS256" or not kid:
        raise _google_invalid()
    keys = await _load_google_keys()
    if kid not in keys:
        keys = await _load_google_keys(force=True)  # Google rotates keys; refresh once for an unknown kid
    if kid not in keys:
        raise _google_invalid()
    try:
        claims = jwt.decode(
            id_token,
            keys[kid],
            algorithms=["RS256"],
            audience=client_id,
            issuer=list(GOOGLE_ISSUERS),
            leeway=GOOGLE_CLOCK_SKEW,
            options={"require": ["exp", "iat", "iss", "aud", "sub"]},
        )
    except jwt.PyJWTError as exc:
        raise _google_invalid() from exc
    return claims


async def _google_claims(session: AsyncSession, id_token: str, nonce: str | None) -> dict:
    """Verified claims of a Google ID token that is bound to this browser's nonce cookie (see GET /auth/google/nonce)."""
    cfg = await integrations.get_google(session)
    if not integrations.google_ready(cfg):
        raise AppError("GOOGLE_DISABLED", "ورود با Google فعال نیست.", 400)
    g = await verify_google_token(id_token, cfg["client_id"])
    if not nonce or not hmac.compare_digest(str(g.get("nonce") or ""), nonce):
        raise AppError("GOOGLE_NONCE_INVALID", "نشست ورود با Google منقضی شده است؛ دوباره تلاش کنید.", 401)
    return g


async def link_google(session: AsyncSession, user: User, id_token: str, nonce: str | None = None) -> None:
    """Attach a Google account to the signed-in user (e.g. an account created from Telegram), so both logins open the
    same account. A Google account that already belongs to another user is never merged: it is reported for review."""
    g = await _google_claims(session, id_token, nonce)
    sub, email = g["sub"], (g.get("email") or "").lower() or None
    ident = await find_identity(session, "google", sub)
    if ident and ident.user_id == user.id:
        return
    if ident:
        review = IdentityLinkReview(
            email=email or "",
            source_user_id=user.id,
            candidate_user_ids=[str(ident.user_id)],
            provider="google",
            reason="google_account_belongs_to_other_user",
        )
        session.add(review)
        audit.security_event(session, "identity_link_conflict", user.id, {"provider": "google", "candidate_user_id": str(ident.user_id)})
        await session.flush()
        res = await auto_link.try_auto_resolve(session, review)  # empty shell on either side: settled by itself (docs/21)
        await session.commit()
        if res is None:
            raise AppError("IDENTITY_LINK_REVIEW", "این حساب Google به حساب دیگری متصل است و برای بررسی دستی گزارش شد.", 409)
        if res.keeper != str(user.id):  # the signed-in account was the empty shell: its session ended with the merge
            raise AppError("IDENTITY_MERGED", "حساب‌ها به‌طور خودکار یکی شدند؛ دوباره وارد شوید.", 409)
        return
    email_verified = bool(email) and str(g.get("email_verified")).lower() == "true"
    session.add(
        Identity(
            user_id=user.id, provider="google", subject=sub, verified_at=utcnow(), data={"email": email, "email_verified": email_verified}
        )
    )
    if email_verified and not user.email and not await _email_taken(session, email):
        user.email = email
    audit.record(session, "identity.linked", actor_id=user.id, entity_type="user", entity_id=user.id, data={"provider": "google"})
    await session.commit()


async def login_with_google(session: AsyncSession, id_token: str, nonce: str | None = None) -> tuple[User, bool]:
    """``nonce`` is the value of the httpOnly nonce cookie issued by GET /auth/google/nonce; the ID token must carry
    the same value (it was passed to google.accounts.id.initialize), which binds the token to this browser."""
    g = await _google_claims(session, id_token, nonce)
    sub, email = g["sub"], (g.get("email") or "").lower() or None
    ident = await find_identity(session, "google", sub)
    if ident:
        return await session.get(User, ident.user_id), False
    user: User | None = None
    created = False
    email_verified = email and str(g.get("email_verified")).lower() == "true"
    # Verified email may connect to the existing central User. An ambiguous/conflicting
    # match is recorded for Admin review, never guessed or merged.
    if email_verified:
        e_idents = (
            await session.scalars(
                select(Identity).where(Identity.provider == "email", Identity.subject == email, Identity.verified_at.is_not(None))
            )
        ).all()
        candidate_ids = {i.user_id for i in e_idents}
        if len(candidate_ids) == 1:
            user = await session.get(User, next(iter(candidate_ids)))
        elif len(candidate_ids) > 1:
            user = User(display_name=g.get("name"), is_guest=True)
            created = True
            session.add(user)
            await session.flush()
            session.add(  # several candidates: ambiguous by definition, always an admin decision
                IdentityLinkReview(
                    email=email,
                    source_user_id=user.id,
                    candidate_user_ids=[str(x) for x in candidate_ids],
                    provider="google",
                    reason="multiple_verified_email_users",
                )
            )
            audit.security_event(
                session, "identity_link_conflict", user.id, {"email": email, "candidate_user_ids": [str(x) for x in candidate_ids]}
            )
        elif await _email_taken(session, email):
            # User.email can be populated without an Identity in legacy data.
            owner_id = await session.scalar(select(User.id).where(User.email == email))
            user = User(display_name=g.get("name"), is_guest=True)
            created = True
            session.add(user)
            await session.flush()
            review = IdentityLinkReview(
                email=email,
                source_user_id=user.id,
                candidate_user_ids=[str(owner_id)],
                provider="google",
                reason="email_field_conflict",
            )
            session.add(review)
            audit.security_event(session, "identity_link_conflict", user.id, {"email": email, "candidate_user_id": str(owner_id)})
            await session.flush()
            res = await auto_link.try_auto_resolve(session, review)  # the verified Google e-mail proves ownership (docs/21)
            if res is not None:
                user = await session.get(User, uuid.UUID(res.keeper))
                created = user is not None and user.id == review.source_user_id
    if user is None:
        user = User(display_name=g.get("name"), email=email if email_verified else None)
        created = True
        session.add(user)
        await session.flush()
    session.add(
        Identity(
            user_id=user.id,
            provider="google",
            subject=sub,
            verified_at=utcnow(),
            data={"email": email, "email_verified": bool(email_verified)},
        )
    )
    audit.record(session, "identity.linked", actor_id=user.id, entity_type="user", entity_id=user.id, data={"provider": "google"})
    return user, created
