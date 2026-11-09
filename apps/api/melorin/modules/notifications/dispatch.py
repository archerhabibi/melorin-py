"""One place that turns "notify this user of this store" into a ready Telegram channel + chat id (T04).

``worker.runner._notify`` and ``orders.delivery`` each resolved the user's Telegram identity, the store's bot token
(or the main bot) and the channel kind on their own. Callers keep their own settings object (so tests and per-process
overrides keep working) and keep deciding what to send and how to record the outcome.
"""

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from melorin.core.crypto import decrypt
from melorin.kernel.models.identity import Identity
from melorin.kernel.models.stores import Store


async def telegram_target(session: AsyncSession, user_id: uuid.UUID, store_id: uuid.UUID | None, settings: Any) -> tuple[Any, str] | None:
    """``(channel, chat_id)`` for the user, or ``None`` when they have no Telegram identity or no bot token is configured.

    ``None`` always maps to the ``skipped`` notification status.
    """
    identity = await session.scalar(select(Identity).where(Identity.user_id == user_id, Identity.provider == "telegram"))
    if not identity:
        return None
    store = await session.get(Store, store_id) if store_id else None
    token = decrypt(store.bot_token_enc) if store and store.bot_token_enc else settings.main_bot_token
    if not token:
        return None
    from melorin.channels.telegram import TelegramChannel  # looked up at call time: tests replace the class

    kind = "reseller" if store and store.kind == "reseller" else "main"
    return TelegramChannel(token, settings.store_web_url, kind), identity.subject
