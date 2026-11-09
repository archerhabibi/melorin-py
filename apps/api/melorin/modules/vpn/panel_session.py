"""One lifecycle for panel adapters (audit T02).

Before this module eight files carried their own ``_close(adapter)`` (some awaited ``close()``, some also tolerated a sync
``close()``, some logged at debug and some at warning). They now all delegate here:

* ``close_adapter``  - close any adapter, including legacy/test adapters with a synchronous ``close()``; never raises.
* ``panel_session``  - ``async with panel_session(panel, server) as adapter:`` builds, yields and always closes the adapter.
"""

import inspect
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from melorin.modules.vpn.adapters.registry import build_adapter

log = logging.getLogger("melorin.panel_session")


async def close_adapter(adapter, label: str = "adapter") -> None:
    """Close ``adapter`` and swallow (but log) any failure: a failed close must never mask the real result."""
    close = getattr(adapter, "close", None)
    if not callable(close):
        return
    try:
        result = close()
        if inspect.isawaitable(result):
            await result
    except Exception:
        log.warning("%s: adapter close failed", label, exc_info=True)


def closer(label: str):
    """Build a module-local ``_close`` bound to a log label (keeps the call sites unchanged)."""

    async def _close(adapter) -> None:
        await close_adapter(adapter, label)

    return _close


@asynccontextmanager
async def panel_session(panel, server=None, *, credentials: dict | None = None) -> AsyncIterator:
    adapter = build_adapter(panel, server, credentials=credentials)
    try:
        yield adapter
    finally:
        await close_adapter(adapter, getattr(panel, "name", None) or "panel")
