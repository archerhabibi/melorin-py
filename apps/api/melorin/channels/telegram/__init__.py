"""Telegram channel adapter (Phase 3.5).

* ``bot_api``     - minimal Bot API transport used by the worker/delivery (``TelegramChannel``)
* ``web``         - bot-approved website login (numbered confirmation, one-time sessions)
* ``web_router``  - its HTTP surface (``/auth/telegram/web-login/...``)
* ``oidc``        - "Log in with Telegram" OpenID Connect helpers
* ``oidc_router`` - its HTTP surface

Everything here is transport/protocol glue: identity creation, sessions and authorization stay in ``modules.identity`` / Core.
"""

from melorin.channels.telegram.bot_api import TelegramChannel

__all__ = ["TelegramChannel"]
