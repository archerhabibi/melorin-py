"""Admin management of reseller stores: edit the store, its limits and its Telegram bot.

Everything the owner can change about the reseller's *business* (prices, branding, payment destinations) stays in the
reseller's own panel; this module is the admin's control surface: identity (name, domain), standing (status, debt
limit, sales / API switches) and the bot (token, on/off, live connection state reported by the runner).
"""

import datetime as dt
import uuid
from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from melorin.core import audit
from melorin.core.crypto import decrypt, encrypt
from melorin.core.deps import AdminUser, Session
from melorin.core.errors import AppError, NotFound
from melorin.modules.identity.models import User
from melorin.modules.reseller import identity
from melorin.modules.reseller.bots import status_out
from melorin.modules.stores.models import BotStoreBinding, ResellerApplication, ResellerProfile, Store, StoreMembership

router = APIRouter(tags=["admin-resellers"])

# Bot texts the reseller bot understands (Store.bot_messages). Unknown keys are rejected so typos do not silently vanish.
BOT_TEXT_KEYS = {"welcome": 1000, "support": 500, "rules": 3000}


class ResellerEdit(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=200)
    domain: str | None = Field(default=None, max_length=255)
    status: Literal["active", "suspended"] | None = None
    debt_limit: int | None = Field(default=None, ge=0)
    sales_enabled: bool | None = None
    api_enabled: bool | None = None
    bot_enabled: bool | None = None
    bot_messages: dict[str, str] | None = None


class BotTokenIn(BaseModel):
    token: str = Field(min_length=10, max_length=200)


async def _reseller_store(session, store_id: uuid.UUID, *, lock: bool = False) -> Store:
    st = await session.get(Store, store_id, with_for_update=lock)
    if not st or st.kind != "reseller":
        raise NotFound("فروشگاه نماینده")
    return st


async def _row(session, st: Store, *, detail: bool = False) -> dict:
    prof = await session.scalar(select(ResellerProfile).where(ResellerProfile.store_id == st.id))
    owner = await session.get(User, st.owner_user_id) if st.owner_user_id else None
    customers = (
        await session.scalar(
            select(func.count())
            .select_from(StoreMembership)
            .where(StoreMembership.store_id == st.id, StoreMembership.role == "customer", StoreMembership.status == "active")
        )
        or 0
    )
    out = {
        "id": st.id,
        "name": st.name,
        "slug": st.slug,
        "status": st.status,
        "domain": st.domain,
        "currency": st.currency,
        "parent_store_id": st.parent_store_id,
        "created_at": st.created_at,
        "owner": {"id": owner.id, "name": owner.display_name, "email": owner.email} if owner else None,
        "debt_limit": prof.debt_limit if prof else 0,
        "sales_enabled": prof.sales_enabled if prof else False,
        "api_enabled": prof.api_enabled if prof else False,
        "customers": customers,
        "bot": status_out(st),
    }
    if detail:
        out["bot_messages"] = st.bot_messages or {}
    return out


@router.get("/resellers")
async def list_resellers(_: AdminUser, session: Session):
    rows = (await session.scalars(select(Store).where(Store.kind == "reseller").order_by(Store.created_at.desc()).limit(500))).all()
    return [await _row(session, st) for st in rows]


@router.get("/resellers/{store_id}")
async def get_reseller(store_id: uuid.UUID, _: AdminUser, session: Session):
    return await _row(session, await _reseller_store(session, store_id), detail=True)


def _clean_texts(raw: dict[str, str]) -> dict[str, str]:
    bad = sorted(set(raw) - set(BOT_TEXT_KEYS))
    if bad:
        raise AppError("INVALID_BOT_TEXT", f"کلید متن ربات نامعتبر است: {', '.join(bad)}", 422)
    out = {}
    for key, value in raw.items():
        value = value.strip()
        if len(value) > BOT_TEXT_KEYS[key]:
            raise AppError("BOT_TEXT_TOO_LONG", f"متن «{key}» بیش از {BOT_TEXT_KEYS[key]} نویسه است.", 422)
        if value:
            out[key] = value
    return out


@router.patch("/resellers/{store_id}")
async def edit_reseller(store_id: uuid.UUID, body: ResellerEdit, admin: AdminUser, session: Session):
    st = await _reseller_store(session, store_id, lock=True)
    prof = await session.scalar(select(ResellerProfile).where(ResellerProfile.store_id == st.id).with_for_update())
    if prof is None and st.owner_user_id:
        prof = ResellerProfile(store_id=st.id, user_id=st.owner_user_id, debt_limit=0, api_enabled=False, sales_enabled=True)
        session.add(prof)
    before, after = {}, {}

    def change(label, old, new):
        if new is not None and new != old:
            before[label], after[label] = old, new
            return True
        return False

    if body.name is not None and change("name", st.name, body.name.strip()):
        st.name = body.name.strip()
    if body.domain is not None:
        domain = identity.normalize_domain(body.domain)
        if domain != st.domain:
            if await session.scalar(select(Store.id).where(Store.domain == domain, Store.id != st.id)) or await session.scalar(
                select(ResellerApplication.id).where(ResellerApplication.domain == domain, ResellerApplication.status == "pending")
            ):
                raise AppError("DOMAIN_TAKEN", "این دامنه قبلاً برای فروشگاه یا درخواست دیگری ثبت شده است.", 409)
            change("domain", st.domain, domain)
            st.domain = domain
    if body.status is not None and change("status", st.status, body.status):
        st.status = body.status
    if body.bot_enabled is not None and change("bot_enabled", st.bot_enabled, body.bot_enabled):
        st.bot_enabled = body.bot_enabled
        if not body.bot_enabled:
            st.bot_status, st.bot_status_detail = "stopped", "توسط مدیر غیرفعال شد."
    if body.bot_messages is not None:
        texts = _clean_texts(body.bot_messages)
        if change("bot_messages", st.bot_messages or {}, texts):
            st.bot_messages = texts or None
    if prof is not None:
        for field in ("debt_limit", "sales_enabled", "api_enabled"):
            value = getattr(body, field)
            if change(field, getattr(prof, field), value):
                setattr(prof, field, value)
    if after:
        audit.record(
            session,
            "reseller.edited",
            actor_id=admin.id,
            actor_type="admin",
            entity_type="reseller_store",
            entity_id=st.id,
            store_id=st.id,
            data={"before": before, "after": after},
        )
    await session.commit()
    return await _row(session, st, detail=True)


async def _ensure_bot_free(session, store: Store, bot_key: str, username: str | None) -> None:
    """The bot must not belong to another store, binding or pending application."""
    taken = await session.scalar(
        select(BotStoreBinding.id).where(BotStoreBinding.bot_key == bot_key, BotStoreBinding.store_id != store.id)
    ) or await session.scalar(
        select(ResellerApplication.id).where(ResellerApplication.bot_key == bot_key, ResellerApplication.status == "pending")
    )
    if not taken and username:
        taken = await session.scalar(select(Store.id).where(func.lower(Store.bot_username) == username.lower(), Store.id != store.id))
    if taken:
        raise AppError("BOT_TAKEN", "این ربات قبلاً برای فروشگاه یا درخواست دیگری ثبت شده است.", 409)


async def _bind(session, st: Store, bot_key: str, username: str | None) -> None:
    binding = await session.scalar(select(BotStoreBinding).where(BotStoreBinding.store_id == st.id))
    if binding is None:
        session.add(
            BotStoreBinding(
                bot_key=bot_key, bot_username=username, store_id=st.id, owner_user_id=st.owner_user_id, bot_kind="reseller", status="active"
            )
        )
    else:
        binding.bot_key, binding.bot_username, binding.status = bot_key, username, "active"


@router.put("/resellers/{store_id}/bot-token")
async def set_bot_token(store_id: uuid.UUID, body: BotTokenIn, admin: AdminUser, session: Session):
    """Replace the store's bot. Telegram must accept the token; the runner picks the new bot up within its poll interval."""
    st = await _reseller_store(session, store_id, lock=True)
    token, bot_key = identity.parse_bot_token(body.token)
    username = await identity.verify_bot(token)
    if username is None:
        raise AppError("TELEGRAM_UNREACHABLE", "ارتباط با تلگرام برقرار نشد؛ کمی بعد دوباره تلاش کنید.", 503)
    await _ensure_bot_free(session, st, bot_key, username)
    old = st.bot_username
    st.bot_token_enc, st.bot_username = encrypt(token), username
    st.bot_status, st.bot_status_detail, st.bot_seen_at = None, None, None
    await _bind(session, st, bot_key, username)
    audit.record(
        session,
        "reseller.bot_token_set",
        actor_id=admin.id,
        actor_type="admin",
        entity_type="reseller_store",
        entity_id=st.id,
        store_id=st.id,
        data={"before": old, "after": username},
    )
    await session.commit()
    return await _row(session, st, detail=True)


@router.delete("/resellers/{store_id}/bot-token")
async def clear_bot_token(store_id: uuid.UUID, admin: AdminUser, session: Session):
    """Disconnect the bot: the token is erased and the bot becomes free to be used by another store."""
    st = await _reseller_store(session, store_id, lock=True)
    old = st.bot_username
    st.bot_token_enc = st.bot_username = st.bot_status = st.bot_status_detail = st.bot_seen_at = None
    binding = await session.scalar(select(BotStoreBinding).where(BotStoreBinding.store_id == st.id))
    if binding is not None:
        await session.delete(binding)
    audit.record(
        session,
        "reseller.bot_token_cleared",
        actor_id=admin.id,
        actor_type="admin",
        entity_type="reseller_store",
        entity_id=st.id,
        store_id=st.id,
        data={"bot": old},
    )
    await session.commit()
    return await _row(session, st, detail=True)


@router.post("/resellers/{store_id}/verify-bot")
async def verify_store_bot(store_id: uuid.UUID, admin: AdminUser, session: Session):
    """Ask Telegram whether the stored token still works (it may have been revoked in BotFather)."""
    st = await _reseller_store(session, store_id, lock=True)
    if not st.bot_token_enc:
        raise AppError("NO_BOT_TOKEN", "برای این فروشگاه ربات ثبت نشده است.", 409)
    try:
        token = decrypt(st.bot_token_enc)
    except RuntimeError:
        raise AppError("BOT_TOKEN_UNREADABLE", "رمزگشایی توکن ممکن نیست؛ توکن را دوباره ثبت کنید.", 409) from None
    try:
        username = await identity.verify_bot(token)
    except AppError as exc:
        st.bot_status, st.bot_status_detail, st.bot_seen_at = (
            "error",
            "تلگرام توکن را نمی‌پذیرد؛ توکن جدید ثبت کنید.",
            dt.datetime.now(dt.UTC),
        )
        await session.commit()
        raise exc
    if username is None:
        raise AppError("TELEGRAM_UNREACHABLE", "ارتباط با تلگرام برقرار نشد؛ کمی بعد دوباره تلاش کنید.", 503)
    st.bot_username = username
    audit.record(
        session,
        "reseller.bot_verified",
        actor_id=admin.id,
        actor_type="admin",
        entity_type="reseller_store",
        entity_id=st.id,
        store_id=st.id,
        data={"bot_username": username},
    )
    await session.commit()
    return await _row(session, st, detail=True)
