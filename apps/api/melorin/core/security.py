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
import binascii
import contextvars
import functools
import re
from collections.abc import Callable
from typing import TypeVar

import jwt

from melorin.core.invariants import require
from melorin.core.config import get_settings

# --------------------------------------------------------------------------- #
# Input normalisation + constant-time comparison (V-001 / V-002)
# --------------------------------------------------------------------------- #
# Persian (U+06F0..) and Arabic-Indic (U+0660..) digits and full-width digits are all "digits" for str.isdigit(), but
# hmac.compare_digest(str, str) raises TypeError on any non-ASCII str. Normalise to ASCII first, then compare BYTES.
_DIGIT_TABLE = {
    **{0x06F0 + i: ord("0") + i for i in range(10)},  # Persian
    **{0x0660 + i: ord("0") + i for i in range(10)},  # Arabic-Indic
    **{0xFF10 + i: ord("0") + i for i in range(10)},  # full-width
}


def normalize_digits(value: str | None) -> str:
    """Map Persian / Arabic-Indic / full-width digits to ASCII and strip spaces, dashes and Arabic separators."""
    if not value:
        return ""
    out = value.translate(_DIGIT_TABLE)
    return re.sub(r"[\s\-\u200c\u200f\u200e\u066c\u066b,]+", "", out)


def safe_equal(a: str | bytes | None, b: str | bytes | None) -> bool:
    """Constant-time equality that never raises on non-ASCII input (compares UTF-8 bytes)."""
    if a is None or b is None:
        return False
    ab = a if isinstance(a, bytes) else a.encode("utf-8", "surrogatepass")
    bb = b if isinstance(b, bytes) else b.encode("utf-8", "surrogatepass")
    return hmac.compare_digest(ab, bb)


# --------------------------------------------------------------------------- #
# Password hashing (V-003 / V-015)
# --------------------------------------------------------------------------- #
# Format: ``scrypt$<log2N>$<r>$<p>$<salt b64>$<hash b64>``. The parameters travel WITH the hash, so raising the cost later
# only needs a new default here: ``needs_rehash`` is true for older hashes and the login path upgrades them transparently.
# 2^16 / r=8 / p=2 is OWASP's equivalent of 2^17 / r=8 / p=1 at half the memory (64 MiB per hash).
_SCRYPT = dict(log2n=16, r=8, p=2, dklen=32)  # mutable on purpose: tests/conftest.py lowers log2n for speed (guarded by a contract test)
_SCRYPT_MAXMEM = 160 * 1024 * 1024
# Each scrypt costs ~64 MiB: bound how many run at once so a login flood cannot exhaust the container's memory.
_KDF_SLOTS = asyncio.Semaphore(2)  # per API process; with 2 uvicorn workers => at most 4 x 64 MiB at once
_KDFResult = TypeVar("_KDFResult")


def _scrypt(password: str, salt: bytes, log2n: int, r: int, p: int) -> bytes:
    return hashlib.scrypt(password.encode(), salt=salt, n=2**log2n, r=r, p=p, dklen=_SCRYPT["dklen"], maxmem=_SCRYPT_MAXMEM)


def _hash_password_sync(password: str) -> str:
    salt = secrets.token_bytes(16)
    dk = _scrypt(password, salt, _SCRYPT["log2n"], _SCRYPT["r"], _SCRYPT["p"])
    return f"scrypt${_SCRYPT['log2n']}${_SCRYPT['r']}${_SCRYPT['p']}${base64.b64encode(salt).decode()}${base64.b64encode(dk).decode()}"


def _parse(stored: str) -> tuple[int, int, int, bytes, bytes] | None:
    parts = stored.split("$")
    try:
        if parts[0] != "scrypt":
            return None
        if len(parts) == 6:  # current format
            log2n, r, p = int(parts[1]), int(parts[2]), int(parts[3])
            salt, dk = base64.b64decode(parts[4]), base64.b64decode(parts[5])
        elif len(parts) == 3:  # legacy ``scrypt$salt$hash`` (N=2^14, r=8, p=1)
            log2n, r, p = 14, 8, 1
            salt, dk = base64.b64decode(parts[1]), base64.b64decode(parts[2])
        else:
            return None
    except (ValueError, binascii.Error):
        return None
    if not (1 <= log2n <= 20 and 1 <= r <= 16 and 1 <= p <= 4):  # never let a stored string pick an absurd cost
        return None
    return log2n, r, p, salt, dk


@functools.lru_cache(maxsize=1)
def _dummy_hash() -> str:
    """A valid hash of a random password, computed once: unknown e-mails are verified against it so that response time
    does not reveal whether the account exists."""
    return _hash_password_sync(secrets.token_urlsafe(16))


def _verify_password_sync(password: str, stored: str | None) -> bool:
    parsed = _parse(stored) if stored else None
    if parsed is None:
        # Burn the same CPU as a real check, then fail.
        parsed_dummy = _parse(_dummy_hash())
        parsed_dummy = require(parsed_dummy, "parsed_dummy")
        log2n, r, p, salt, dk = parsed_dummy
        _scrypt(password, salt, log2n, r, p)
        return False
    log2n, r, p, salt, dk = parsed
    return hmac.compare_digest(_scrypt(password, salt, log2n, r, p), dk)


def needs_rehash(stored: str | None) -> bool:
    parsed = _parse(stored) if stored else None
    return parsed is not None and parsed[:3] != (_SCRYPT["log2n"], _SCRYPT["r"], _SCRYPT["p"])


async def _run_kdf(func: Callable[..., _KDFResult], *args: object) -> _KDFResult:
    """Keep the slot until the worker actually stops, even when the caller is cancelled."""
    slots = _KDF_SLOTS
    await slots.acquire()
    try:
        context = contextvars.copy_context()  # preserve the context propagation of asyncio.to_thread
        worker = asyncio.get_running_loop().run_in_executor(None, context.run, functools.partial(func, *args))
    except BaseException:
        slots.release()
        raise

    def finish(result: asyncio.Future[_KDFResult]) -> None:
        slots.release()
        if not result.cancelled():
            result.exception()  # also consume errors when the caller has already gone away

    worker.add_done_callback(finish)
    return await asyncio.shield(worker)


async def hash_password(password: str) -> str:
    """Run the deliberately expensive KDF off the asyncio event loop."""
    return await _run_kdf(_hash_password_sync, password)


async def verify_password(password: str, stored: str | None) -> bool:
    """Verify in the worker pool. Always does the full amount of work, even for a missing/invalid hash."""
    return await _run_kdf(_verify_password_sync, password, stored)


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def new_opaque_token(nbytes: int = 32) -> str:
    return secrets.token_urlsafe(nbytes)


def new_numeric_code(digits: int = 6) -> str:
    return "".join(secrets.choice("0123456789") for _ in range(digits))


def _signing_keys() -> list[str]:
    """Current key first, then ``MELORIN_JWT_PREVIOUS_SECRETS`` (comma-separated) so a rotation does not log everyone out."""
    st = get_settings()
    return [st.jwt_secret, *[k.strip() for k in st.jwt_previous_secrets.split(",") if k.strip()]]


def _kid(key: str) -> str:
    return hashlib.sha256(b"melorin-jwt-kid:" + key.encode()).hexdigest()[:12]


def create_access_token(
    user_id: uuid.UUID, is_admin: bool, *, store_id: uuid.UUID | None = None, channel: str | None = None
) -> tuple[str, int]:
    """Short-lived JWT. Besides the user it carries WHERE the session was opened (docs/08-IDENTITY-ACCOUNT-PERSON.md):

    * ``chn``: ``site`` | ``bot`` | ``admin``  (the channel Core verified at login, never what the client claimed);
    * ``sid``: the store that channel belongs to (absent only for ``admin`` sessions, which are platform-wide).

    Registered claims: ``iss``/``aud`` (reject tokens minted for another service), ``jti`` (unique id for audit/revocation),
    header ``kid`` (which key signed it, for rotation). ``adm`` is kept for old readers; Core itself trusts ``chn == "admin"``.
    """
    s = get_settings()
    now = int(time.time())
    chn = channel or ("admin" if is_admin else "site")
    payload = {
        "sub": str(user_id),
        "adm": is_admin,
        "iat": now,
        "nbf": now,
        "exp": now + s.jwt_access_ttl_seconds,
        "iss": s.jwt_issuer,
        "aud": s.jwt_audience,
        "jti": uuid.uuid4().hex,
        "typ": "access",
        "chn": chn,
    }
    if store_id is not None:
        payload["sid"] = str(store_id)
    key = s.jwt_secret
    return jwt.encode(payload, key, algorithm="HS256", headers={"kid": _kid(key)}), s.jwt_access_ttl_seconds


def decode_access_token(token: str) -> dict:
    s = get_settings()
    keys = _signing_keys()
    try:
        kid = jwt.get_unverified_header(token).get("kid")
    except jwt.PyJWTError:
        kid = None
    # Try the key named by ``kid`` first, then the rest (tokens minted before kid existed carry none).
    ordered = sorted(keys, key=lambda k: 0 if kid and _kid(k) == kid else 1)
    last: jwt.PyJWTError | None = None
    for key in ordered:
        try:
            return jwt.decode(
                token,
                key,
                algorithms=["HS256"],
                audience=s.jwt_audience,
                issuer=s.jwt_issuer,
                options={"require": ["exp", "sub", "iss", "aud", "jti"]},
            )
        except jwt.InvalidSignatureError as exc:
            last = exc
            continue
    raise last or jwt.InvalidSignatureError("no signing key")


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


_TOTP_RE = re.compile(r"[0-9]{6}")


def totp_counter(secret: str, code: str, window: int = 1) -> int | None:
    """Return the accepted RFC 6238 time-step, enabling replay protection.

    The code is normalised first (Persian/Arabic digits, spaces) and must be exactly six ASCII digits; comparison is on bytes.
    """
    code = normalize_digits(code)
    if not secret or not _TOTP_RE.fullmatch(code):
        return None
    c = int(time.time()) // 30
    found: int | None = None
    for w in range(-window, window + 1):  # no early exit: constant work whatever the match
        counter = c + w
        if safe_equal(_totp(secret, counter), code) and found is None:
            found = counter
    return found
