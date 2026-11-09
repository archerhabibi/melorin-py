"""One place for the lifecycle of a panel adapter (audit T02).

Before this module, seven ``vpn`` files each carried their own ``_close(adapter)`` (same job, different log level, some tolerating a
synchronous ``close()``) and three carried their own ``PanelError -> AppError`` mapping. Behaviour is unchanged: closing never raises
(a failed close is only logged) and the error mapping keeps the Persian messages each caller already showed.
"""

from __future__ import annotations

import inspect
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from melorin.core.errors import AppError
from melorin.modules.vpn.adapters.base import ErrorKind, PanelError

log = logging.getLogger("melorin.panel_session")

DEFAULT_REJECTED_HINT = "پنل این درخواست را نپذیرفت؛ بعداً دوباره تلاش کنید یا با پشتیبانی تماس بگیرید."
UNAVAILABLE_HINT = "پنل در حال حاضر پاسخ نمی‌دهد؛ چند لحظه بعد دوباره تلاش کنید."


async def close_adapter(adapter) -> None:
    """Close ``adapter`` and never raise. Accepts adapters (legacy / test doubles) whose ``close`` is synchronous or absent."""
    close = getattr(adapter, "close", None)
    if not callable(close):
        return
    try:
        result = close()
        if inspect.isawaitable(result):
            await result
    except Exception:
        log.warning("adapter close failed", exc_info=True)


def panel_error(exc: PanelError, *, rejected_hint: str = DEFAULT_REJECTED_HINT) -> AppError:
    """Customer/admin-safe mapping: a permanent refusal is 409, anything transient is 503. ``exc`` text is never echoed."""
    if exc.kind == ErrorKind.PERMANENT:
        return AppError("PANEL_REJECTED", rejected_hint, 409)
    return AppError("PANEL_UNAVAILABLE", UNAVAILABLE_HINT, 503)


@asynccontextmanager
async def panel_session(panel, server=None, *, credentials: dict | None = None) -> AsyncIterator:
    """``async with panel_session(panel, server) as adapter:`` builds the adapter and always closes it.

    ``server`` follows ``build_adapter``: pass it ONLY when creating a new account. Errors are not translated here, so each caller keeps
    its own policy (wrap with :func:`panel_error` where the old code did)."""
    from melorin.modules.vpn.adapters.registry import build_adapter  # late: registry imports half of vpn

    adapter = build_adapter(panel, server, credentials=credentials)
    try:
        yield adapter
    finally:
        await close_adapter(adapter)
