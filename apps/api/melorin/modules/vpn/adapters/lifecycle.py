"""Single place that knows how to release a panel adapter (audit T02).

Eight modules used to carry their own ``_close`` copy with slightly different log levels and sync/async handling.
``close_adapter`` accepts both async and legacy sync ``close()`` implementations (tests use the latter).
"""

from __future__ import annotations

import inspect
import logging

log = logging.getLogger("melorin.vpn.adapters")


async def close_adapter(adapter, *, strict: bool = False) -> None:
    """Close ``adapter`` if it has a ``close`` method.

    ``strict=False`` (default) logs and swallows failures so a broken close never masks the real result of a request.
    ``strict=True`` re-raises; the worker jobs use it to keep their historical behaviour.
    """
    close = getattr(adapter, "close", None)
    if not callable(close):
        return
    try:
        result = close()
        if inspect.isawaitable(result):
            await result
    except Exception:
        if strict:
            raise
        log.warning("adapter close failed", exc_info=True)
