"""Reads behind the Event Center router (audit T11: the router holds no SQL). Behaviour unchanged."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from melorin.kernel.models.stores import Store


async def main_store(session: AsyncSession) -> Store | None:
    return await session.scalar(select(Store).where(Store.kind == "main"))
