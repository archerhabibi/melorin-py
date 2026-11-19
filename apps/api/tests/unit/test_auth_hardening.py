"""Regression tests for the audit findings on input normalisation, password hashing, JWT claims and key rotation."""

import time

import jwt
import pytest
from cryptography.fernet import Fernet

from melorin.core import security
from melorin.core.security import (
    _totp,
    create_access_token,
    decode_access_token,
    hash_password,
    needs_rehash,
    normalize_digits,
    safe_equal,
    totp_counter,
    verify_password,
)

SECRET = "JBSWY3DPEHPK3PXP"


@pytest.mark.parametrize("digits", ["۰۱۲۳۴۵۶۷۸۹", "٠١٢٣٤٥٦٧٨٩", "０１２３４５６７８９"])
def test_normalize_digits_maps_persian_arabic_and_fullwidth(digits):
    assert normalize_digits(digits) == "0123456789"


@pytest.mark.parametrize("fmt", ["{}", "{} ", "{}-{}"])
def test_totp_accepts_persian_arabic_fullwidth_digits_without_crashing(fmt):
    code = _totp(SECRET, int(time.time()) // 30)
    for table in (0x06F0, 0x0660, 0xFF10):
        typed = "".join(chr(table + int(c)) for c in code)
        assert totp_counter(SECRET, typed) == int(time.time()) // 30


@pytest.mark.parametrize("bad", ["", "12345", "1234567", "abcdef", "12 34", "١٢٣٤٥٦٧", "\u00e9\u00e9\u00e9\u00e9\u00e9\u00e9"])
def test_totp_rejects_malformed_codes_without_raising(bad):
    assert totp_counter(SECRET, bad) is None


def test_safe_equal_never_raises_on_non_ascii():
    assert safe_equal("é", "é") and not safe_equal("é", "e") and not safe_equal(None, "x")


async def test_hash_embeds_parameters_and_legacy_hashes_need_rehash():
    stored = await hash_password("pw-1234567890")
    assert stored.startswith("scrypt$") and len(stored.split("$")) == 6
    assert not needs_rehash(stored)
    # legacy 3-part format (N=2^14) still verifies and is flagged for upgrade
    import base64
    import hashlib

    salt = b"0123456789abcdef"
    dk = hashlib.scrypt(b"old-pass", salt=salt, n=2**14, r=8, p=1, dklen=32)
    legacy = "scrypt$" + base64.b64encode(salt).decode() + "$" + base64.b64encode(dk).decode()
    assert await verify_password("old-pass", legacy) and needs_rehash(legacy)
    assert not await verify_password("nope", legacy)


async def test_unknown_account_does_the_same_kdf_work(monkeypatch):
    security._dummy_hash()  # warm the cached dummy so only the two verifications are counted
    calls = []
    real = security._scrypt
    monkeypatch.setattr(security, "_scrypt", lambda *a: calls.append(1) or real(*a))
    assert not await verify_password("x", None)
    assert not await verify_password("x", "garbage")
    assert len(calls) == 2  # missing/invalid hash still burns one KDF (no user-enumeration timing)


def test_absurd_cost_in_a_stored_hash_is_refused():
    assert security._parse("scrypt$30$8$1$AAAA$AAAA") is None


def test_access_token_carries_registered_claims_and_kid():
    import uuid

    tok, _ = create_access_token(uuid.uuid4(), False)
    claims = decode_access_token(tok)
    assert claims["iss"] == "melorin" and claims["aud"] == "melorin-api" and len(claims["jti"]) == 32
    assert jwt.get_unverified_header(tok)["kid"]
    assert decode_access_token(create_access_token(uuid.uuid4(), False)[0])["jti"] != claims["jti"]


def test_token_for_another_audience_or_key_is_rejected(monkeypatch):
    import uuid

    from melorin.core.config import get_settings

    s = get_settings()
    now = int(time.time())
    base = {"sub": str(uuid.uuid4()), "iat": now, "exp": now + 60, "iss": s.jwt_issuer, "jti": "x"}
    with pytest.raises(jwt.PyJWTError):
        decode_access_token(jwt.encode({**base, "aud": "someone-else"}, s.jwt_secret, algorithm="HS256"))
    with pytest.raises(jwt.PyJWTError):  # no jti/aud at all (token minted by the old code)
        decode_access_token(jwt.encode({"sub": "u", "exp": now + 60}, s.jwt_secret, algorithm="HS256"))


def test_jwt_key_rotation_keeps_old_tokens_valid(monkeypatch):
    import uuid

    from melorin.core.config import get_settings

    old = get_settings().jwt_secret
    tok, _ = create_access_token(uuid.uuid4(), False)
    monkeypatch.setenv("MELORIN_JWT_SECRET", "brand-new-signing-key-0123456789-abcdefghijklmnop")
    monkeypatch.setenv("MELORIN_JWT_PREVIOUS_SECRETS", old)
    get_settings.cache_clear()
    assert decode_access_token(tok)["sub"]
    monkeypatch.setenv("MELORIN_JWT_PREVIOUS_SECRETS", "")
    get_settings.cache_clear()
    with pytest.raises(jwt.PyJWTError):
        decode_access_token(tok)


def test_encryption_key_rotation_decrypts_with_previous_key(monkeypatch):
    from melorin.core import crypto

    k_old, k_new = Fernet.generate_key().decode(), Fernet.generate_key().decode()
    monkeypatch.setenv("MELORIN_ENCRYPTION_KEY", k_old)
    from melorin.core.config import get_settings

    get_settings.cache_clear()
    crypto._fernet.cache_clear()
    cipher = crypto.encrypt("bot-token")
    monkeypatch.setenv("MELORIN_ENCRYPTION_KEY", k_new)
    monkeypatch.setenv("MELORIN_ENCRYPTION_KEY_PREVIOUS", k_old)
    get_settings.cache_clear()
    crypto._fernet.cache_clear()
    assert crypto.decrypt(cipher) == "bot-token"  # old ciphertext still readable
    rotated = crypto._fernet().rotate(cipher.encode()).decode()
    assert Fernet(k_new.encode()).decrypt(rotated.encode()) == b"bot-token"  # re-encrypted under the primary key
    crypto._fernet.cache_clear()
