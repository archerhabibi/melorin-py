"""Reseller API - پیام همگانی: a reseller messages the customers of HIS OWN store (never another store's)."""

from fastapi import APIRouter
from pydantic import BaseModel, Field

from melorin.core.deps import OwnerCtx, Session
from melorin.modules.broadcast import service

router = APIRouter(tags=["reseller"])


class BroadcastIn(BaseModel):
    title: str = Field(min_length=1, max_length=service.TITLE_MAX)
    body: str = Field(min_length=1, max_length=service.BODY_MAX)


@router.get("/stores/{store_id}/reseller/broadcasts")
async def broadcasts(ctx: OwnerCtx, session: Session):
    return {
        "audiences": await service.audience_counts(session, ctx.store),
        "daily_limit": service.DAILY_LIMIT,
        "items": await service.history(session, ctx.store),
    }


@router.post("/stores/{store_id}/reseller/broadcasts", status_code=201)
async def send_broadcast(body: BroadcastIn, ctx: OwnerCtx, session: Session):
    bc = await service.send(session, sender=ctx.user, store=ctx.store, audience="customers", title=body.title, body=body.body)
    return {"ok": True, "id": bc.id, "recipients": bc.recipients}
