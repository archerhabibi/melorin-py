"""PostgreSQL serialization for bank SMS matching and human decisions."""

import asyncio
import datetime as dt

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker

from _db import make_store, open_schema_engine, pg_url
from melorin.kernel.models.payments import BankSmsMessage, BankSmsSource
from melorin.kernel.models.stores import Store
from melorin.modules.payments.bank_sms.matching import match_message

pytestmark = [
    pytest.mark.concurrency,
    pytest.mark.skipif(pg_url() is None, reason="PostgreSQL lane: set TEST_PG_URL"),
]


async def test_matcher_waits_for_a_human_and_observes_the_new_sms_status():
    async with open_schema_engine() as engine:
        factory = async_sessionmaker(engine, expire_on_commit=False)
        async with factory() as session:
            store = await make_store(session)
            source = BankSmsSource(store_id=store.id, is_enabled=True, auto_verify=True)
            session.add(source)
            await session.flush()
            sms = BankSmsMessage(
                store_id=store.id,
                source_id=source.id,
                fingerprint="one-deposit",
                raw_text="test deposit",
                direction="deposit",
                amount_rial=1_500_000,
                occurred_at=dt.datetime.now(dt.UTC),
                status="unmatched",
            )
            session.add(sms)
            await session.commit()
            store_id, source_id, sms_id = store.id, source.id, sms.id

        async with factory() as human, factory() as matcher:
            held = await human.get(BankSmsMessage, sms_id, with_for_update=True)
            stale = await matcher.get(BankSmsMessage, sms_id)
            source = await matcher.get(BankSmsSource, source_id)
            store = await matcher.get(Store, store_id)
            task = asyncio.create_task(match_message(matcher, stale, source, store))
            try:
                with pytest.raises(asyncio.TimeoutError):
                    await asyncio.wait_for(asyncio.shield(task), timeout=0.3)
            finally:
                held.status = "ignored"
                await human.commit()
            assert await asyncio.wait_for(task, timeout=3) == "ignored"
            assert stale.status == "ignored" and stale.payment_id is None
