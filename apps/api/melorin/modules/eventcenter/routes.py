"""Event Center settings API: one group for the Admin, one for each reseller store (SRS §17)."""

from fastapi import APIRouter

from melorin.core.deps import AdminUser, OwnerCtx, Session
from melorin.kernel.models.stores import Store
from melorin.modules.eventcenter import service
from melorin.modules.eventcenter.schemas import EventCenterIn

admin_router = APIRouter(prefix="/admin", tags=["admin"])
reseller_router = APIRouter(tags=["reseller"])


async def _main_store(session) -> Store | None:
    from sqlalchemy import select

    return await session.scalar(select(Store).where(Store.kind == "main"))


async def _read(session, store: Store | None) -> dict:
    owner = store if store is not None and store.kind == "reseller" else None
    dest = await service.get_destination(session, owner.id if owner else None)
    return service.view(dest, bot_ready=await service.bot_ready(session, owner), admin=owner is None)


async def _save(session, store: Store | None, actor_id, body: EventCenterIn) -> dict:
    owner = store if store is not None and store.kind == "reseller" else None
    await service.save(
        session, store=owner, actor_id=actor_id, chat_id=body.chat_id, topics=body.topics, is_enabled=body.is_enabled, note=body.note
    )
    await session.commit()
    return await _read(session, owner)


# ----- Admin -----
@admin_router.get("/event-center")
async def admin_get(_: AdminUser, session: Session):
    return await _read(session, None)


@admin_router.put("/event-center")
async def admin_put(body: EventCenterIn, admin: AdminUser, session: Session):
    return await _save(session, None, admin.id, body)


@admin_router.delete("/event-center")
async def admin_delete(admin: AdminUser, session: Session):
    removed = await service.remove(session, store=None, actor_id=admin.id)
    await session.commit()
    return {"removed": removed}


@admin_router.post("/event-center/test")
async def admin_test(_: AdminUser, session: Session):
    return {"results": await service.send_test(session, store=None)}


@admin_router.post("/event-center/check")
async def admin_check(_: AdminUser, session: Session):
    return await service.inspect(session, store=None)


@admin_router.post("/event-center/provision")
async def admin_provision(admin: AdminUser, session: Session):
    return await service.provision_topics(session, store=None, actor_id=admin.id)


# ----- Reseller (owner of the store only) -----
@reseller_router.get("/stores/{store_id}/reseller/event-center")
async def reseller_get(ctx: OwnerCtx, session: Session):
    return await _read(session, ctx.store)


@reseller_router.put("/stores/{store_id}/reseller/event-center")
async def reseller_put(body: EventCenterIn, ctx: OwnerCtx, session: Session):
    return await _save(session, ctx.store, ctx.user.id, body)


@reseller_router.delete("/stores/{store_id}/reseller/event-center")
async def reseller_delete(ctx: OwnerCtx, session: Session):
    removed = await service.remove(session, store=ctx.store, actor_id=ctx.user.id)
    await session.commit()
    return {"removed": removed}


@reseller_router.post("/stores/{store_id}/reseller/event-center/test")
async def reseller_test(ctx: OwnerCtx, session: Session):
    return {"results": await service.send_test(session, store=ctx.store)}


@reseller_router.post("/stores/{store_id}/reseller/event-center/check")
async def reseller_check(ctx: OwnerCtx, session: Session):
    return await service.inspect(session, store=ctx.store)


@reseller_router.post("/stores/{store_id}/reseller/event-center/provision")
async def reseller_provision(ctx: OwnerCtx, session: Session):
    return await service.provision_topics(session, store=ctx.store, actor_id=ctx.user.id)
