import datetime as dt  # noqa: F401
from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from melorin.core.config import get_settings
from melorin.kernel.base import NAMING, Base, CreatedMixin, IdMixin, TimestampMixin, utcnow  # noqa: F401  (re-exported: historical import path)


_engine = None
_sessionmaker: async_sessionmaker[AsyncSession] | None = None


def configure(url: str | None = None) -> None:
    global _engine, _sessionmaker
    s = get_settings()
    url = url or s.database_url
    kwargs = {"pool_pre_ping": True}
    if url.startswith("postgresql"):
        kwargs.update(pool_size=s.db_pool_size, max_overflow=s.db_pool_size)
    _engine = create_async_engine(url, **kwargs)
    _sessionmaker = async_sessionmaker(_engine, expire_on_commit=False)


def engine():
    if _engine is None:
        configure()
    return _engine


def session_factory() -> async_sessionmaker[AsyncSession]:
    if _sessionmaker is None:
        configure()
    assert _sessionmaker is not None
    return _sessionmaker


async def get_session() -> AsyncIterator[AsyncSession]:
    """Request-scoped session. Use cases commit explicitly; anything uncommitted is rolled back."""
    async with session_factory()() as session:
        try:
            yield session
        finally:
            if session.in_transaction():
                await session.rollback()
