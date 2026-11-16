"""Bot-facing endpoints. The bot only relays what Telegram told it; every decision is made here (docs/25 §12.2)."""

from fastapi import APIRouter
from sqlalchemy import func, select

from melorin.core.deps import BotAuth, Session
from melorin.kernel.models.identity import Identity, User
from melorin.modules.identity.lookup import find_identity

router = APIRouter(prefix="/internal/identity", tags=["identity-linking-internal"])


@router.get("/telegram/status")
async def telegram_status(telegram_id: int, session: Session, bot: BotAuth):
    """Is this Telegram id attached to a person, and to how many accounts / login methods? No names, no balances."""
    ident = await find_identity(session, "telegram", str(telegram_id))
    if ident is None or ident.person_id is None:
        return {"linked": False, "accounts": 0, "methods": 0}
    accounts = await session.scalar(
        select(func.count()).select_from(User).where(User.person_id == ident.person_id, User.is_active.is_(True))
    )
    methods = await session.scalar(
        select(func.count()).select_from(Identity).where(Identity.person_id == ident.person_id, Identity.status == "active")
    )
    return {"linked": True, "accounts": int(accounts or 0), "methods": int(methods or 0)}
