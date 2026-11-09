"""One way for the payments module to tell a store's admins something (audit T04).

``bank_sms`` and ``provisional`` each had an identical private ``_notify``. Both now call this; the text still goes
through the Event Center outbox topic, so rules, dedup and delivery stay in one place.
"""

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from melorin.core import events


async def notify_store_payments(session: AsyncSession, store_id: uuid.UUID, text: str) -> None:
    await events.emit(session, events.EVENT_CENTER, {"store_id": store_id, "topic": "payments", "text": text})
