"""One paging loop for reading panel users (audit T08).

``reconcile`` (every panel user) and ``store_usage`` (every user of one panel admin) each carried their own copy of "ask the panel page
by page until it runs out". They differ only in *which* adapter call they page and in how many rows they accept, so the loop lives here and
each caller passes its own ``fetch``. Behaviour is unchanged: the offset is the number of rows already read, a short or empty page ends the
listing, and the listing is ``complete`` unless ``max_rows`` was reached first.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Hashable
from dataclasses import dataclass, field
from typing import Any

# fetch(offset=..., limit=...) -> (rows, total); ``total`` may be ``None`` when the panel does not report one.
Fetch = Callable[..., Awaitable[tuple[list, Any]]]


@dataclass
class Listing:
    rows: list = field(default_factory=list)
    total: int | None = None
    complete: bool = True


async def read_pages(fetch: Fetch, *, page_size: int, max_rows: int, key: Callable[[Any], Hashable] | None = None) -> Listing:
    """Read ``fetch`` page by page.

    ``max_rows``: stop asking once this many rows were read; the listing is then marked incomplete (the caller must not draw "missing"
    conclusions from it). ``key``: identify a row so that a panel repeating one across pages is counted once when comparing against
    ``total``."""
    rows: list = []
    seen: set = set()
    total: int | None = None
    while len(rows) < max_rows:
        page, count = await fetch(offset=len(rows), limit=page_size)
        if isinstance(count, int):
            total = count
        if not page:
            return Listing(rows, total, True)
        rows.extend(page)
        read = len(rows)
        if key is not None:
            seen.update(key(r) for r in page)
            read = len(seen)
        if len(page) < page_size or (total is not None and read >= total):
            return Listing(rows, total, True)
    return Listing(rows, total, False)


class PanelReader:
    """Read-side view of one panel adapter: the listings the reconciler and the store usage report need.

    Only reads. Closing the adapter stays with whoever built it (see ``panel_session``)."""

    def __init__(self, adapter, *, seed: Callable[[Any, Any], Any] | None = None) -> None:
        """``seed(adapter, account)`` lets name-mapping adapters (upstream_bot) re-learn an account's upstream name before a single-user
        read; callers pass ``registry.seed_adapter`` (they keep their own reference so tests can replace it)."""
        self.adapter = adapter
        self._seed = seed

    async def account(self, account):
        """The panel's current copy of ``account`` (``None`` when the panel does not know the user). Errors propagate."""
        adapter = self._seed(self.adapter, account) if self._seed else self.adapter
        return await adapter.get_account(account.username)

    async def read_many(self, accounts, *, concurrency: int, on_error: Callable[[Any, Exception], None] | None = None) -> dict:
        """``{account.id: panel copy or None}``; a failing read is ``None`` (reported to ``on_error``), never a guess and never raised."""
        gate = asyncio.Semaphore(concurrency)

        async def one(account):
            async with gate:
                try:
                    return account.id, await self.account(account)
                except Exception as exc:
                    if on_error is not None:
                        on_error(account, exc)
                    return account.id, None

        return dict(await asyncio.gather(*(one(a) for a in accounts)))

    async def accounts(self, *, page_size: int, max_rows: int) -> Listing:
        """Every panel user, de-duplicated by username when comparing against the panel's own total."""
        return await read_pages(self.adapter.list_accounts, page_size=page_size, max_rows=max_rows, key=lambda r: r.username)

    async def owner_accounts(self, username: str, *, page_size: int, max_rows: int) -> Listing:
        """Every user owned by panel admin ``username``."""

        async def fetch(*, offset: int, limit: int):
            return await self.adapter.list_owner_accounts(username, offset=offset, limit=limit)

        return await read_pages(fetch, page_size=page_size, max_rows=max_rows)
