"""Outgoing webhook endpoints: manage, rotate secret, delivery log, redeliver, test."""

import uuid

from fastapi import APIRouter

from melorin.core.deps import OwnerCtx, Session
from melorin.modules.reseller.schemas import (
    WebhookEndpointIn,
    WebhookEndpointPatch,
)
from melorin.modules.webhooks import service as webhooks

router = APIRouter(tags=["reseller"])


@router.get("/stores/{store_id}/reseller/webhooks")
async def list_webhooks(ctx: OwnerCtx, session: Session):
    return [webhooks.endpoint_out(e) for e in await webhooks.list_endpoints(session, ctx.store.id)]


@router.post("/stores/{store_id}/reseller/webhooks", status_code=201)
async def create_webhook(body: WebhookEndpointIn, ctx: OwnerCtx, session: Session):
    ep, secret = await webhooks.create_endpoint(session, ctx.store.id, str(body.url), body.events, body.description, ctx.user.id)
    return {**webhooks.endpoint_out(ep), "secret": secret, "warning": "این secret فقط یک بار نمایش داده می‌شود."}


@router.patch("/stores/{store_id}/reseller/webhooks/{endpoint_id}")
async def patch_webhook(endpoint_id: uuid.UUID, body: WebhookEndpointPatch, ctx: OwnerCtx, session: Session):
    ep = await webhooks.get_endpoint(session, ctx.store.id, endpoint_id)
    ep = await webhooks.update_endpoint(
        session,
        ep,
        url=str(body.url) if body.url else None,
        events=body.events,
        description=body.description,
        status=body.status,
        actor_id=ctx.user.id,
    )
    return webhooks.endpoint_out(ep)


@router.post("/stores/{store_id}/reseller/webhooks/{endpoint_id}/rotate-secret")
async def rotate_webhook_secret(endpoint_id: uuid.UUID, ctx: OwnerCtx, session: Session):
    ep = await webhooks.get_endpoint(session, ctx.store.id, endpoint_id)
    secret = await webhooks.rotate_secret(session, ep, ctx.user.id)
    return {"secret": secret, "warning": "secret قبلی تا ۲۴ ساعت همچنان برای امضای دوم معتبر است."}


@router.delete("/stores/{store_id}/reseller/webhooks/{endpoint_id}")
async def delete_webhook(endpoint_id: uuid.UUID, ctx: OwnerCtx, session: Session):
    ep = await webhooks.get_endpoint(session, ctx.store.id, endpoint_id)
    await webhooks.update_endpoint(session, ep, status="disabled", actor_id=ctx.user.id)
    return {"ok": True}


@router.get("/stores/{store_id}/reseller/webhooks/{endpoint_id}/deliveries")
async def webhook_deliveries(endpoint_id: uuid.UUID, ctx: OwnerCtx, session: Session):
    ep = await webhooks.get_endpoint(session, ctx.store.id, endpoint_id)
    return [webhooks.delivery_out(d) for d in await webhooks.list_deliveries(session, ep.id)]


@router.post("/stores/{store_id}/reseller/webhooks/{endpoint_id}/deliveries/{delivery_id}/redeliver")
async def redeliver(endpoint_id: uuid.UUID, delivery_id: uuid.UUID, ctx: OwnerCtx, session: Session):
    ep = await webhooks.get_endpoint(session, ctx.store.id, endpoint_id)
    await webhooks.redeliver(session, ep, delivery_id, ctx.user.id)
    return {"ok": True}


@router.post("/stores/{store_id}/reseller/webhooks/{endpoint_id}/test")
async def test_webhook(endpoint_id: uuid.UUID, ctx: OwnerCtx, session: Session):
    ep = await webhooks.get_endpoint(session, ctx.store.id, endpoint_id)
    d = await webhooks.enqueue_test(session, ep)
    return {"ok": True, "delivery_id": d.id}
