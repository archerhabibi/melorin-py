"""``async with panel_session(panel, server)`` — build a panel adapter and always release it (audit T02).

The close/error helpers live once, in ``adapters.lifecycle`` (``close_adapter``, ``panel_failure``); this module only adds the
context manager on top so callers stop hand-writing ``try/finally: await close_adapter(adapter)``.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from melorin.modules.panel_integrations.adapters.lifecycle import close_adapter, panel_failure  # noqa: F401  (re-exported for callers)


@asynccontextmanager
async def panel_session(panel, server=None, *, credentials: dict | None = None) -> AsyncIterator:
    """Builds the adapter and always closes it (a failed close is logged, never raised).

    ``server`` follows ``build_adapter``: pass it ONLY when creating a new account. Errors are not translated here, so each
    caller keeps its own policy (wrap with ``panel_failure`` where the old code did).
    """
    from melorin.modules.panel_integrations.adapters.registry import build_adapter  # late: registry imports half of vpn

    adapter = build_adapter(panel, server, credentials=credentials)
    try:
        yield adapter
    finally:
        await close_adapter(adapter)
