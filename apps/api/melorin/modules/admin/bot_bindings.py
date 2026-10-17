import uuid

from sqlalchemy import select

from melorin.core import audit
from melorin.core.errors import AppError
from melorin.modules.stores.models import BotStoreBinding, Store


def out(row: BotStoreBinding) -> dict:
    return {
        "id": row.id,
        "bot_key": row.bot_key,
        "bot_username": row.bot_username,
        "store_id": row.store_id,
        "owner_user_id": row.owner_user_id,
        "bot_kind": row.bot_kind,
        "status": row.status,
        "config": row.config or {},
    }


async def list_bindings(session):
    return (await session.scalars(select(BotStoreBinding).order_by(BotStoreBinding.created_at))).all()


async def create_binding(session, body, actor):
    store = await session.get(Store, body.store_id)
    if not store or store.status != "active":
        raise AppError("STORE_NOT_FOUND", "فروشگاه فعال یافت نشد.", 404)
    if body.bot_kind == "reseller" and store.kind != "reseller":
        raise AppError("BOT_STORE_KIND_MISMATCH", "ربات reseller فقط به Store نمایندگی متصل می‌شود.", 400)
    if body.bot_kind == "main" and store.kind != "main":
        raise AppError("BOT_STORE_KIND_MISMATCH", "ربات اصلی فقط به Main Store متصل می‌شود.", 400)
    row = BotStoreBinding(
        bot_key=body.bot_key.strip(),
        bot_username=body.bot_username,
        store_id=store.id,
        owner_user_id=store.owner_user_id or actor.id,
        bot_kind=body.bot_kind,
        status="active",
        config=body.config,
    )
    session.add(row)
    audit.record(
        session,
        "bot_store_binding.created",
        actor_id=actor.id,
        actor_type="admin",
        entity_type="bot_store_binding",
        entity_id=row.id,
        store_id=store.id,
    )
    await session.commit()
    return row
