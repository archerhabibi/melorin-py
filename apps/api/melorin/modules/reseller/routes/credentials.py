"""Reseller API credentials (create / rotate / enable / disable)."""

import uuid

from fastapi import APIRouter
from sqlalchemy import select

from melorin.core.deps import OwnerCtx, Session
from melorin.core.errors import NotFound
from melorin.kernel.models.stores import ApiCredential
from melorin.modules.reseller import api_keys
from melorin.modules.reseller.schemas import (
    ApiCredentialIn,
)

router = APIRouter(tags=["reseller"])


@router.get("/stores/{store_id}/reseller/api-credentials")
async def list_credentials(ctx: OwnerCtx, session: Session):
    rows = (
        await session.scalars(select(ApiCredential).where(ApiCredential.store_id == ctx.store.id).order_by(ApiCredential.created_at.desc()))
    ).all()
    return [api_keys.out(c) for c in rows]


@router.post("/stores/{store_id}/reseller/api-credentials", status_code=201)
async def create_credential(body: ApiCredentialIn, ctx: OwnerCtx, session: Session):
    cred, raw = await api_keys.create(session, ctx.store, ctx.user, body)
    return {**api_keys.out(cred), "api_key": raw, "warning": "این کلید فقط یک بار نمایش داده می‌شود."}


@router.post("/stores/{store_id}/reseller/api-credentials/{cred_id}/{action}")
async def credential_action(cred_id: uuid.UUID, action: str, ctx: OwnerCtx, session: Session):
    cred = await session.get(ApiCredential, cred_id, with_for_update=True)
    if not cred or cred.store_id != ctx.store.id:
        raise NotFound("کلید API")
    if action == "rotate":
        new, raw = await api_keys.rotate(session, cred, ctx.user)
        return {**api_keys.out(new), "api_key": raw, "warning": "این کلید فقط یک بار نمایش داده می‌شود."}
    await api_keys.set_status(session, cred, action, ctx.user)
    return api_keys.out(cred)
