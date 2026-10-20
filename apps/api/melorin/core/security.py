"""Password hashing (scrypt), JWT access tokens, opaque token hashing, TOTP."""

import base64
import datetime as dt
import hashlib
import hmac
import secrets
import struct
import time
import uuid
import asyncio

import jwt

from melorin.core.config import get_settings

_SCRYPT = dict(n=2**14, r=8, p=1, dklen=32)


def _hash_password_sync(password: str) -> str:
    salt = secrets.token_bytes(16)
    dk = hashlib.scrypt(password.encode(), salt=salt, **_SCRYPT)
    return "scrypt$" + base64.b64encode(salt).decode() + "$" + base64.b64encode(dk).decode()


def _verify_password_sync(password: str, stored: str | None) -> bool:
    if not stored or not stored.startswith("scrypt$"):
        return False
    _, s, h = stored.split("$")
    dk = hashlib.scrypt(password.encode(), salt=base64.b64decode(s), **_SCRYPT)
    return hmac.compare_digest(dk, base64.b64decode(h))


async def hash_password(password: str) -> str:
    """Run the deliberately expensive KDF off the asyncio event loop."""
    return await asyncio.to_thread(_hash_password_sync, password)


async def verify_password(password: str, stored: str | None) -> bool:
    """Verify a password in the default worker pool, not in the event loop."""
    return await asyncio.to_thread(_verify_password_sync, password, stored)


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def new_opaque_token(nbytes: int = 32) -> str:
    return secrets.token_urlsafe(nbytes)


def new_numeric_code(digits: int = 6) -> str:
    return "".join(secrets.choice("0123456789") for _ in range(digits))


def create_access_token(
    user_id: uuid.UUID, is_admin: bool, *, store_id: uuid.UUID | None = None, channel: str | None = None
) -> tuple[str, int]:
    """Short-lived JWT. Besides the user it carries WHERE the session was opened (docs/16-Channel-Binding-Design.md):

    * ``chn``: ``site`` | ``bot`` | ``admin``  (the channel Core verified at login, never what the client claimed);
    * ``sid``: the store that channel belongs to (absent only for ``admin`` sessions, which are platform-wide).

    ``adm`` is kept for old readers; Core itself trusts ``chn == "admin"`` (see ``core.channel.SessionClaims``).
    """
    s = get_settings()
    now = int(time.time())
    chn = channel or ("admin" if is_admin else "site")
    payload = {"sub": str(user_id), "adm": is_admin, "iat": now, "exp": now + s.jwt_access_ttl_seconds, "typ": "access", "chn": chn}
    if store_id is not None:
        payload["sid"] = str(store_id)
    return jwt.encode(payload, s.jwt_secret, algorithm="HS256"), s.jwt_access_ttl_seconds


def decode_access_token(token: str) -> dict:
    return jwt.decode(token, get_settings().jwt_secret, algorithms=["HS256"], options={"require": ["exp", "sub"]})


def refresh_expiry() -> dt.datetime:
    return dt.datetime.now(dt.UTC) + dt.timedelta(days=get_settings().refresh_ttl_days)


# ---- TOTP (RFC 6238) ----
def totp_new_secret() -> str:
    return base64.b32encode(secrets.token_bytes(20)).decode().rstrip("=")


def _totp(secret: str, counter: int) -> str:
    key = base64.b32decode(secret + "=" * (-len(secret) % 8))
    h = hmac.new(key, struct.pack(">Q", counter), hashlib.sha1).digest()
    o = h[-1] & 0x0F
    code = (struct.unpack(">I", h[o : o + 4])[0] & 0x7FFFFFFF) % 1_000_000
    return f"{code:06d}"


def totp_verify(secret: str, code: str, window: int = 1) -> bool:
    return totp_counter(secret, code, window) is not None


def totp_counter(secret: str, code: str, window: int = 1) -> int | None:
    """Return the accepted RFC 6238 time-step, enabling replay protection."""
    if not secret or not code or not code.isdigit():
        return None
    c = int(time.time()) // 30
    for w in range(-window, window + 1):
        counter = c + w
        if hmac.compare_digest(_totp(secret, counter), code):
            return counter
    return None
