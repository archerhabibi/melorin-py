"""Shared pytest configuration.

M6.6: the unit suite must not depend on the developer's / CI's ambient
``MELORIN_*`` environment. ``get_settings()`` is evaluated at import time by
several modules (worker, Telegram login ...), so the environment has to be
scrubbed *before* test modules are collected, not only per test.

Tests marked ``integration`` talk to real services and therefore keep the
ambient configuration (``MELORIN_DATABASE_URL``, ``MELORIN_REDIS_URL`` ...).
"""

from __future__ import annotations

import os

import pytest

_PREFIX = "MELORIN_"
_AMBIENT = {k: v for k, v in os.environ.items() if k.startswith(_PREFIX)}


# M6.10: the application default (22 bytes) is below the 32-byte HMAC minimum and
# makes PyJWT emit InsecureKeyLengthWarning in every login test. The hermetic
# environment therefore ships a deliberately long, test-only signing key.
TEST_JWT_SECRET = "test-only-jwt-signing-key-0123456789-abcdefghij"


def _scrub() -> None:
    for key in [k for k in os.environ if k.startswith(_PREFIX)]:
        del os.environ[key]
    os.environ["MELORIN_JWT_SECRET"] = TEST_JWT_SECRET
    # Hermetic receipt OCR: whether the machine happens to have `tesseract` must not change what an upload queues (with an
    # engine configured the receipt stays "ocr_pending" until a worker reads it). Tests that need an engine opt in explicitly.
    os.environ["MELORIN_RECEIPT_OCR_ENGINE"] = "off"


def _restore() -> None:
    _scrub()
    os.environ.update(_AMBIENT)


def _clear_settings_cache() -> None:
    from melorin.core import config

    config.get_settings.cache_clear()


# Runs at conftest import, i.e. before any test module is imported.
_scrub()

# A developer's local ``apps/api/.env`` must not leak into the suite either.
from melorin.core import config as _config  # noqa: E402

_config.Settings.model_config["env_file"] = None

# Test-only: scrypt at production cost (n=2**14, ~45 ms) dominates every test that creates a user. The cost is stored in each hash,
# so a cheap factor keeps hashing/verification/rehash fully functional. The hardened value stays in production code and
# is pinned by tests/test_security_kdf_cost.py.
from melorin.core import security as _security  # noqa: E402

PRODUCTION_SCRYPT_LOG2N = _security._SCRYPT["log2n"]
_security._SCRYPT["log2n"] = 4


@pytest.fixture(autouse=True)
def _hermetic_environment(request: pytest.FixtureRequest):
    """Give every test a clean, deterministic ``MELORIN_*`` environment."""
    if request.node.get_closest_marker("integration"):
        _restore()
    else:
        _scrub()
    _clear_settings_cache()
    try:
        yield
    finally:
        # Never leak values set by one test (or its monkeypatch) into the next.
        _scrub()
        _clear_settings_cache()


@pytest.fixture(autouse=True)
def _hermetic_job_lock(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch):
    """Unit tests use an in-memory lock backend; integration tests may use real Redis."""
    if request.node.get_closest_marker("integration"):
        return

    from melorin.worker import wrap

    class TestRedisLock:
        def __init__(self):
            self.store: dict[str, str] = {}

        async def set(self, key, value, nx=False, ex=None):
            if nx and key in self.store:
                return None
            self.store[key] = value
            return True

        async def eval(self, _script, _n, key, token):
            if self.store.get(key) == token:
                del self.store[key]
                return 1
            return 0

    redis = TestRedisLock()
    monkeypatch.setattr(wrap, "get_redis", lambda: redis)
