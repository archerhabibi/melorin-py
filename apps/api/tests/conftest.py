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
