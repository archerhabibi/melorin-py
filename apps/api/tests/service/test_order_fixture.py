"""Regression for the shared order fixture's unique, six-character numbers."""

import uuid
from types import SimpleNamespace

import _db
from _db import make_product, make_store, make_user, open_session


async def test_order_fixture_stays_unique_when_uuid_prefixes_repeat(monkeypatch):
    async with open_session() as session:
        store = await make_store(session)
        user = await make_user(session)
        product = await make_product(session)
        monkeypatch.setattr(_db, "uuid", SimpleNamespace(uuid4=lambda: uuid.UUID("abcdef" + uuid.uuid4().hex[6:])))

        first = await _db.make_order(session, user=user, store=store, product=product)
        second = await _db.make_order(session, user=user, store=store, product=product)
        assert len(first.number) == len(second.number) == 6
        assert first.number != second.number
