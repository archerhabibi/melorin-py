"""Unit of work: one place that decides when a use case's transaction ends (audit T10).

``get_session`` rolls back whatever a use case left uncommitted, and 300+ call sites commit by hand. ``unit_of_work`` is the single
spelling for "everything written so far belongs together": it commits when the block ends normally and rolls back (then re-raises)
when it does not. Behaviour is the same as ``await session.commit()`` at the end of the block; the gain is that a failure inside the
block can no longer leave a half-written session behind for the next statement to commit by accident.

Migrate call sites gradually; ``tests/test_commit_ratchet.py`` keeps the hand-written count from growing.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import AsyncSession


@asynccontextmanager
async def unit_of_work(session: AsyncSession) -> AsyncIterator[AsyncSession]:
    try:
        yield session
        await session.commit()
    except BaseException:
        await session.rollback()
        raise
