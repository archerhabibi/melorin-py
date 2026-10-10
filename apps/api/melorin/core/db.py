import datetime as dt
import uuid
from collections.abc import AsyncIterator

from sqlalchemy import DateTime, MetaData, Uuid, func
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from melorin.core.config import get_settings

NAMING = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING)


def utcnow() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


class IdMixin:
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)


class CreatedMixin:
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow, server_default=func.now())


class TimestampMixin(CreatedMixin):
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, server_default=func.now()
    )


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
