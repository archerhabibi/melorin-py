"""Identity API composition root.

The former 403-line router lives in one module per route family under ``identity/routes/``: ``sign_in`` (the ``/auth``
router: e-mail code, password, Google, Telegram, web hand-off, refresh, logout), ``account`` (the ``/me`` router: profile,
stores, linking, password, TOTP) and ``_common`` (cookie names and helpers shared by both, also used by the Telegram
channel adapters). Paths, methods and schemas are unchanged; this module only exposes the two routers.
"""

from melorin.modules.identity.routes._common import (  # noqa: F401
    GOOGLE_NONCE_COOKIE,
    GOOGLE_NONCE_PATH,
    GOOGLE_NONCE_TTL,
    REFRESH_COOKIE,
    _set_refresh_cookie,
)
from melorin.modules.identity.routes.account import me
from melorin.modules.identity.routes.sign_in import auth

__all__ = ["auth", "me", "REFRESH_COOKIE", "GOOGLE_NONCE_COOKIE", "GOOGLE_NONCE_PATH", "GOOGLE_NONCE_TTL", "_set_refresh_cookie"]

# Backward-compatible attribute access (``router.create_web_handoff``) for callers and tests written before the split.
_FAMILIES = ("sign_in", "account", "_common")


def __getattr__(name: str):
    import importlib

    for family in _FAMILIES:
        module = importlib.import_module(f"melorin.modules.identity.routes.{family}")
        if name in vars(module):
            return getattr(module, name)
    raise AttributeError(name)
