"""Helpers for tests that call route handlers directly: build the channel-bound session Core would have verified."""

from __future__ import annotations

import types
import uuid

from melorin.core.channel import ADMIN, BOT, SITE, SessionClaims
from melorin.core.deps import AuthSession


def auth_for(user, store, channel: str = SITE) -> AuthSession:
    """A customer session of ``user`` opened through ``channel`` of ``store`` (what the login handlers mint)."""
    return AuthSession(user=user, claims=SessionClaims(user_id=user.id, channel=channel, store_id=store.id if store else None))


def admin_auth(user) -> AuthSession:
    return AuthSession(user=user, claims=SessionClaims(user_id=user.id, channel=ADMIN, store_id=None))


def fake_request(host: str = "localhost", peer: str = "203.0.113.9", **headers):
    """Minimal stand-in for ``fastapi.Request`` (headers/cookies/client) for handlers called directly."""
    h = {"host": host, "user-agent": "pytest", **{k.replace("_", "-"): v for k, v in headers.items()}}
    return types.SimpleNamespace(headers=h, cookies={}, client=types.SimpleNamespace(host=peer))


__all__ = ["ADMIN", "BOT", "SITE", "admin_auth", "auth_for", "fake_request", "uuid"]
