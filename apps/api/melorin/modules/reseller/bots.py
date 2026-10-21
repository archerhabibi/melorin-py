"""Reseller Telegram bots as Core knows them.

Core is the single source of truth: the reseller runner never reads tokens from its own environment in normal
operation, it asks Core which bots should be running (``GET /internal/reseller-bots``) and reports back what it
managed to do (``POST /internal/reseller-bots/{store_id}/status``). The admin panel reads the same state, so
"is this bot really connected?" has one honest answer.
"""

import datetime as dt
import hashlib

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field
from sqlalchemy import select

from melorin.core import audit
from melorin.core.crypto import decrypt
from melorin.core.channel import BotService
from melorin.core.deps import Session, require_bot_service
from melorin.core.errors import AppError, NotFound
from melorin.kernel.models.stores import Store

POLL_SECONDS = 30  # how often the runner re-reads the list
STALE_AFTER = dt.timedelta(seconds=POLL_SECONDS * 4)  # a "running" bot that stopped reporting is shown as offline
REPORTABLE = {"connecting", "running", "error", "stopped"}


def fingerprint(store: Store, token: str) -> str:
    """Changes whenever the runner must restart this bot (token, slug) — never reveals the token."""
    return hashlib.sha256(f"{store.id}|{store.slug}|{token}".encode()).hexdigest()[:16]


def effective_state(store: Store, now: dt.datetime | None = None) -> str:
    """What the admin should see. no_token | disabled | store_suspended | pending | connecting | running | offline | error | stopped."""
    if not store.bot_token_enc:
        return "no_token"
    if store.status != "active":
        return "store_suspended"
    if not store.bot_enabled:
        return "disabled"
    state = store.bot_status or "pending"
    if state in ("running", "connecting") and store.bot_seen_at:
        seen = store.bot_seen_at if store.bot_seen_at.tzinfo else store.bot_seen_at.replace(tzinfo=dt.UTC)
        if (now or dt.datetime.now(dt.UTC)) - seen > STALE_AFTER:
            return "offline"
    return state


def status_out(store: Store) -> dict:
    return {
        "state": effective_state(store),
        "detail": store.bot_status_detail,
        "seen_at": store.bot_seen_at,
        "enabled": store.bot_enabled,
        "has_token": bool(store.bot_token_enc),
        "username": store.bot_username,
    }


async def runnable_bots(session) -> list[dict]:
    """Active reseller stores whose bot should be polling right now (token decrypted for the runner only)."""
    rows = (
        await session.scalars(
            select(Store)
            .where(
                Store.kind == "reseller",
                Store.status == "active",
                Store.bot_enabled.is_(True),
                Store.bot_token_enc.is_not(None),
            )
            .order_by(Store.created_at)
        )
    ).all()
    out = []
    for st in rows:
        try:
            token = decrypt(st.bot_token_enc)
        except RuntimeError:  # encryption key rotated / corrupted: surface it instead of crash-looping the runner
            st.bot_status, st.bot_status_detail = "error", "رمزگشایی توکن ممکن نیست؛ توکن را دوباره ثبت کنید."
            continue
        out.append(
            {
                "store_id": st.id,
                "slug": st.slug,
                "name": st.name,
                "bot_username": st.bot_username,
                "token": token,
                "fingerprint": fingerprint(st, token),
            }
        )
    await session.commit()
    return out


class BotStatusIn(BaseModel):
    state: str
    detail: str | None = Field(default=None, max_length=300)
    fingerprint: str | None = Field(default=None, max_length=32)


async def apply_status(session, store_id, body: BotStatusIn) -> bool:
    """Record what the runner reports. A report about an old token (fingerprint mismatch) is ignored."""
    if body.state not in REPORTABLE:
        raise AppError("INVALID_BOT_STATE", "وضعیت ربات نامعتبر است.", 422)
    st = await session.get(Store, store_id, with_for_update=True)
    if not st or st.kind != "reseller":
        raise NotFound("فروشگاه نماینده")
    if body.fingerprint and st.bot_token_enc:
        try:
            if body.fingerprint != fingerprint(st, decrypt(st.bot_token_enc)):
                return False
        except RuntimeError:
            return False
    before = st.bot_status
    st.bot_status, st.bot_status_detail, st.bot_seen_at = body.state, (body.detail or None), dt.datetime.now(dt.UTC)
    if body.state == "error" and before != "error":  # transitions only, so a flapping bot does not flood the audit log
        audit.record(
            session,
            "reseller.bot_error",
            actor_type="system",
            entity_type="reseller_store",
            entity_id=st.id,
            store_id=st.id,
            data={"detail": body.detail},
        )
    await session.commit()
    return True


def _internal_only(request: Request) -> None:
    """The runner talks to Core on the private network. A request that came through a reverse proxy (it carries
    forwarding headers) is somebody on the internet: refuse it even if it knows the shared secret."""
    if any(h in request.headers for h in ("x-forwarded-for", "x-forwarded-host", "x-real-ip")):
        raise NotFound("صفحه")


def _reseller_runner_only(bot: BotService = Depends(require_bot_service)) -> None:
    """Reseller bot tokens go to the reseller runner only; the main runner's secret (when per-runner secrets are set) cannot read them."""
    if not bot.may_serve("reseller"):
        raise AppError("CHANNEL_FORBIDDEN", "این ربات اجازه‌ی کار با این فروشگاه را ندارد.", 403)


internal = APIRouter(
    prefix="/internal", tags=["internal"], dependencies=[Depends(_internal_only), Depends(_reseller_runner_only)], include_in_schema=False
)


@internal.get("/reseller-bots")
async def list_reseller_bots(session: Session):
    return {"bots": await runnable_bots(session), "poll_seconds": POLL_SECONDS}


@internal.post("/reseller-bots/{store_id}/status")
async def report_bot_status(store_id: str, body: BotStatusIn, session: Session):
    import uuid

    try:
        sid = uuid.UUID(store_id)
    except ValueError:
        raise NotFound("فروشگاه نماینده") from None
    return {"ok": await apply_status(session, sid, body)}
