"""Website login with Telegram's OpenID Connect provider (https://core.telegram.org/bots/telegram-login).

Standard Authorization Code flow with PKCE (S256), done entirely on the server:

1. ``/auth/telegram/oidc/start``    builds the authorize URL; ``state``, ``nonce`` and the PKCE verifier travel in a
   short-lived, signed, HttpOnly cookie that only this browser holds (no database row, no migration);
2. Telegram redirects the browser to ``/auth/telegram/oidc/callback?code=...&state=...``;
3. the server swaps the code for an ``id_token`` (Basic auth with Client ID + Client Secret), verifies its signature
   against Telegram's JWKS and checks ``iss`` / ``aud`` / ``exp`` (+ ``nonce`` when Telegram echoes it);
4. the Telegram user ID (``id`` claim, the same number the bot sees) is mapped to the same ``Identity`` the bot-approval
   flow and the bot itself use, so a customer is one account whichever way they sign in.

Admins never get a session here (same rule as the bot-approval flow and the storefront Google flow).
"""

import base64
import hashlib
import hmac
import secrets
import time
import uuid
from urllib.parse import urlencode, urlparse

import httpx
import jwt

from melorin.core.config import get_settings
from melorin.core.errors import AppError
from melorin.modules.identity.schemas import TelegramProfile
from melorin.modules.stores.models import Store

ISSUER = "https://oauth.telegram.org"
AUTH_URL = f"{ISSUER}/auth"
TOKEN_URL = f"{ISSUER}/token"
JWKS_URL = f"{ISSUER}/.well-known/jwks.json"
DISCOVERY_URL = f"{ISSUER}/.well-known/openid-configuration"
# BotFather lets the owner pick the signing algorithm. EdDSA/ES256K tokens are restricted to the bare ``openid`` scope
# (no ``id`` claim), so they cannot identify a customer here. Pinning the list also blocks algorithm-confusion attacks.
ALLOWED_ALGS = ["RS256", "ES256"]
SCOPE = "openid profile"
COOKIE = "mlr_tg_oidc"
COOKIE_PATH = "/api/v1/auth/telegram/oidc"
FLOW_TTL_SECONDS = 600
CALLBACK_PATH = "/api/v1/auth/telegram/oidc/callback"
_FLOW_TYP = "tg_oidc_flow"  # distinguishes this cookie from access tokens signed with the same secret (those need ``sub``)
HTTP_TIMEOUT = 10.0
_jwks_cache: dict = {"at": 0.0, "keys": {}}
JWKS_TTL_SECONDS = 3600


def _origin(url: str) -> str | None:
    p = urlparse((url or "").strip())
    return f"{p.scheme}://{p.netloc}" if p.scheme in ("http", "https") and p.netloc else None


def callback_origin(store: Store | None) -> str:
    """Origin the customer is browsing (and Telegram redirects back to): the reseller's own domain or the main store."""
    if store is not None and store.kind == "reseller" and store.domain:
        return f"https://{store.domain.strip().lower()}"
    return _origin(get_settings().store_web_url) or "http://localhost:3000"


def redirect_uri(origin: str) -> str:
    return f"{origin}{CALLBACK_PATH}"


def bot_id_of(token: str | None) -> str | None:
    """A bot token looks like ``123456789:AA...``; the number before ':' is the bot ID, which is also the OIDC Client ID."""
    head = (token or "").split(":", 1)[0]
    return head if head.isdigit() else None


# ---------------- flow cookie ----------------
def pkce_pair() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(64)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    return verifier, challenge


def _flow_key() -> bytes:
    """Own HMAC key derived from the app secret: a flow cookie can never validate as any other token signed with ``jwt_secret``."""
    return hmac.new(get_settings().jwt_secret.encode(), b"melorin:telegram-oidc-flow:v1", hashlib.sha256).digest()


def seal(**claims) -> str:
    return jwt.encode({**claims, "typ": _FLOW_TYP, "exp": int(time.time()) + FLOW_TTL_SECONDS}, _flow_key(), algorithm="HS256")


def unseal(token: str | None) -> dict | None:
    if not token:
        return None
    try:
        data = jwt.decode(token, _flow_key(), algorithms=["HS256"], options={"require": ["exp"]})
    except jwt.PyJWTError:
        return None
    return data if data.get("typ") == _FLOW_TYP else None


def authorize_url(client_id: str, redirect: str, state: str, challenge: str, nonce: str) -> str:
    return f"{AUTH_URL}?" + urlencode(
        {
            "client_id": client_id,
            "redirect_uri": redirect,
            "response_type": "code",
            "scope": SCOPE,
            "state": state,
            "nonce": nonce,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
        }
    )


# ---------------- Telegram calls ----------------
def _oauth_error(r: httpx.Response) -> str:
    """The RFC 6749 ``error`` code of a failed token call (a short ASCII token, safe to log); empty when absent."""
    try:
        err = (r.json() or {}).get("error")
    except ValueError:
        return ""
    return err[:40] if isinstance(err, str) and err.replace("_", "").isalnum() else ""


async def exchange_code(client_id: str, client_secret: str, code: str, redirect: str, verifier: str) -> str:
    """Server-to-server code exchange; returns the raw ``id_token``."""
    try:
        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as c:
            r = await c.post(
                TOKEN_URL,
                auth=(client_id, client_secret),
                headers={"Accept": "application/json"},
                data={
                    "grant_type": "authorization_code",
                    "code": code,
                    "redirect_uri": redirect,
                    "client_id": client_id,
                    "code_verifier": verifier,
                },
            )
    except httpx.HTTPError as exc:
        raise AppError("TELEGRAM_OIDC_UNREACHABLE", "اتصال به سرور ورود تلگرام برقرار نشد.", 502) from exc
    if r.status_code >= 500:
        raise AppError("TELEGRAM_OIDC_UNREACHABLE", "سرور ورود تلگرام موقتاً در دسترس نیست.", 502)
    if r.status_code != 200:
        err = _oauth_error(r)
        if r.status_code == 401 or err == "invalid_client":
            # Wrong/rotated Client Secret or Client ID: an admin problem, not the customer's. Surfaced in security events + panel test.
            raise AppError("TELEGRAM_OIDC_CLIENT_REJECTED", "تلگرام Client ID/Secret را نپذیرفت.", 502, {"telegram_error": err})
        raise AppError("TELEGRAM_OIDC_EXCHANGE_FAILED", "تلگرام کد ورود را نپذیرفت.", 401, {"telegram_error": err})
    try:
        token = (r.json() or {}).get("id_token")
    except ValueError:
        token = None
    if not isinstance(token, str) or not token:
        raise AppError("TELEGRAM_OIDC_EXCHANGE_FAILED", "پاسخ تلگرام شامل id_token نبود.", 401)
    return token


async def fetch_jwks() -> dict:
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as c:
        r = await c.get(JWKS_URL)
    r.raise_for_status()
    return r.json()


async def _key_for(kid: str | None, alg: str):
    """Signing key by ``kid``; the JWKS is cached for an hour and re-read once when an unknown ``kid`` shows up (key rotation)."""
    now = time.time()
    for attempt in (0, 1):
        stale = now - _jwks_cache["at"] > JWKS_TTL_SECONDS
        if attempt == 1 or stale or not _jwks_cache["keys"]:
            try:
                doc = await fetch_jwks()
            except (httpx.HTTPError, ValueError) as exc:
                raise AppError("TELEGRAM_OIDC_UNREACHABLE", "کلیدهای امضای تلگرام دریافت نشد.", 502) from exc
            keys = {}
            for jwk in doc.get("keys", []):
                try:
                    keys[jwk.get("kid")] = jwt.PyJWK.from_dict(jwk)
                except jwt.PyJWTError:
                    continue
            _jwks_cache.update(at=time.time(), keys=keys)
        key = _jwks_cache["keys"].get(kid) or (
            next(iter(_jwks_cache["keys"].values())) if kid is None and len(_jwks_cache["keys"]) == 1 else None
        )
        if key is not None:
            return key
    raise AppError("TELEGRAM_OIDC_INVALID", "کلید امضای توکن تلگرام شناخته نشد.", 401)


async def verify_id_token(id_token: str, client_id: str, nonce: str | None = None) -> dict:
    """Cryptographically validates the ``id_token`` as required by the Telegram documentation."""
    try:
        header = jwt.get_unverified_header(id_token)
        alg = header.get("alg")
        if alg not in ALLOWED_ALGS:
            raise AppError("TELEGRAM_OIDC_INVALID", "الگوریتم امضای توکن تلگرام پذیرفته نیست.", 401)
        key = await _key_for(header.get("kid"), alg)
        claims = jwt.decode(
            id_token,
            key.key,
            algorithms=[alg],
            audience=str(client_id),
            issuer=ISSUER,
            leeway=30,
            options={"require": ["exp", "iat", "iss", "aud", "sub"]},
        )
    except jwt.PyJWTError as exc:
        raise AppError("TELEGRAM_OIDC_INVALID", "توکن تلگرام نامعتبر است.", 401) from exc
    # PKCE + state already bind the code to this browser; when Telegram echoes the nonce it must be ours.
    if "nonce" in claims and nonce is not None and not secrets.compare_digest(str(claims["nonce"]), nonce):
        raise AppError("TELEGRAM_OIDC_INVALID", "توکن تلگرام برای این درخواست صادر نشده است.", 401)
    return claims


def profile_from_claims(claims: dict) -> TelegramProfile:
    """``id`` is the real Telegram user ID (``sub`` is an OIDC-scoped identifier and would create duplicate accounts)."""
    raw = claims.get("id")
    try:
        tg_id = int(raw)
    except (TypeError, ValueError):
        raise AppError("TELEGRAM_OIDC_NO_ID", "تلگرام شناسهٔ کاربر را نفرستاد؛ دسترسی profile باید فعال باشد.", 401) from None
    if tg_id <= 0:
        raise AppError("TELEGRAM_OIDC_NO_ID", "شناسهٔ کاربر تلگرام نامعتبر است.", 401)
    first = claims.get("given_name") or claims.get("name")
    return TelegramProfile(
        telegram_id=tg_id,
        first_name=str(first)[:100] if first else None,
        last_name=str(claims["family_name"])[:100] if claims.get("family_name") else None,
        username=str(claims["preferred_username"])[:64] if claims.get("preferred_username") else None,
    )


def new_flow(client_id: str, store_id: uuid.UUID, origin: str) -> tuple[str, str]:
    """Returns ``(authorize_url, sealed_cookie)`` for a fresh login attempt."""
    state, nonce = secrets.token_urlsafe(24), secrets.token_urlsafe(24)
    verifier, challenge = pkce_pair()
    ru = redirect_uri(origin)
    return authorize_url(client_id, ru, state, challenge, nonce), seal(
        state=state, nonce=nonce, cv=verifier, sid=str(store_id), org=origin, ru=ru
    )
