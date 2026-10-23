"""Admin API - پیام همگانی: message the admin's resellers and/or customers (or every customer of the whole project)."""

from fastapi import APIRouter
from pydantic import BaseModel, Field

from melorin.core.deps import AdminUser, Session, main_store
from melorin.modules.broadcast import service

router = APIRouter(prefix="/admin", tags=["admin"])


class BroadcastIn(BaseModel):
    audience: str = Field(max_length=30)
    title: str = Field(min_length=1, max_length=service.TITLE_MAX)
    body: str = Field(min_length=1, max_length=service.BODY_MAX)


@router.get("/broadcasts/audiences")
async def audiences(_: AdminUser, session: Session):
    """The groups the admin can pick, with how many people each one reaches right now."""
    return {"audiences": await service.audience_counts(session, await main_store(session)), "daily_limit": service.DAILY_LIMIT}


@router.get("/broadcasts")
async def history(_: AdminUser, session: Session):
    return await service.history(session, await main_store(session))


@router.post("/broadcasts", status_code=201)
async def send(body: BroadcastIn, admin: AdminUser, session: Session):
    bc = await service.send(session, sender=admin, store=await main_store(session), audience=body.audience, title=body.title, body=body.body)
    return {"ok": True, "id": bc.id, "recipients": bc.recipients}
