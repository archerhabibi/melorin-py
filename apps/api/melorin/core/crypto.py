"""Encryption-at-rest for secrets (bot tokens, panel credentials, gateway keys)."""

import base64
import hashlib
import logging
from functools import lru_cache
from typing import overload

from cryptography.fernet import Fernet, InvalidToken

from melorin.core.config import get_settings

log = logging.getLogger(__name__)


@lru_cache
def _fernet() -> Fernet:
    s = get_settings()
    key = s.encryption_key
    if not key:
        if not s.is_dev:
            raise RuntimeError("MELORIN_ENCRYPTION_KEY is required outside development")
        log.warning("Using derived dev encryption key. Never do this in production.")
        key = base64.urlsafe_b64encode(hashlib.sha256(s.jwt_secret.encode()).digest()).decode()
    try:
        return Fernet(key.encode())
    except (ValueError, TypeError) as e:
        raise RuntimeError("MELORIN_ENCRYPTION_KEY is not a valid Fernet key") from e


@overload
def encrypt(plain: str) -> str: ...
@overload
def encrypt(plain: None) -> None: ...
def encrypt(plain: str | None) -> str | None:
    return None if plain is None else _fernet().encrypt(plain.encode()).decode()


@overload
def decrypt(cipher: str) -> str: ...
@overload
def decrypt(cipher: None) -> None: ...
def decrypt(cipher: str | None) -> str | None:
    if cipher is None:
        return None
    try:
        return _fernet().decrypt(cipher.encode()).decode()
    except InvalidToken as e:  # key rotated / corrupted
        raise RuntimeError("cannot decrypt secret") from e
