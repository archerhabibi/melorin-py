"""Admin API - per-store VPN notice settings, notice texts and the daily digest switch (PG-06)."""

import logging
import uuid

from fastapi import APIRouter
from pydantic import BaseModel, Field

from melorin.core import audit
from melorin.core.deps import AdminUser, Session
from melorin.core.errors import AppError, NotFound
from melorin.kernel.models.stores import Store
from melorin.modules.vpn import notices

router = APIRouter(prefix="/admin", tags=["admin"])
log = logging.getLogger("melorin.admin.store_vpn_notices")


# ------------------------------------------------------------------------------------------- per-store notice settings (PG-06)
class NoticeSettingsIn(BaseModel):
    traffic_low_levels: list[int] = Field(
        max_length=notices.MAX_LEVELS, description="percents (1-99) at which the customer is warned; [] = no warnings"
    )


class NoticeSettingsOut(BaseModel):
    store_id: uuid.UUID
    traffic_low_levels: list[int]
    is_default: bool
    default_levels: list[int] = list(notices.TRAFFIC_LOW_LEVELS)


def _notice_out(store: Store) -> NoticeSettingsOut:
    custom = bool(store.vpn_notice_settings) and "traffic_low_levels" in store.vpn_notice_settings
    return NoticeSettingsOut(
        store_id=store.id, traffic_low_levels=list(notices.levels_for_store(store.vpn_notice_settings)), is_default=not custom
    )


@router.get("/stores/{store_id}/vpn-notices", response_model=NoticeSettingsOut)
async def get_store_vpn_notices(store_id: uuid.UUID, _: AdminUser, session: Session):
    store = await session.get(Store, store_id)
    if not store:
        raise NotFound("فروشگاه")
    return _notice_out(store)


@router.put("/stores/{store_id}/vpn-notices", response_model=NoticeSettingsOut)
async def put_store_vpn_notices(store_id: uuid.UUID, body: NoticeSettingsIn, admin: AdminUser, session: Session):
    """Set when THIS store's customers are warned about low traffic. Takes effect at the next sync; a level already warned stays warned."""
    store = await session.get(Store, store_id)
    if not store:
        raise NotFound("فروشگاه")
    try:
        levels = notices.normalize_levels(body.traffic_low_levels)
    except ValueError as exc:
        raise AppError("INVALID_NOTICE_LEVELS", "آستانه‌های هشدار حجم نامعتبر است", status=422, details={"reason": str(exc)}) from exc
    before = list(notices.levels_for_store(store.vpn_notice_settings))
    store.vpn_notice_settings = {**(store.vpn_notice_settings or {}), "traffic_low_levels": list(levels)}
    audit.record(
        session,
        "store.vpn_notices.updated",
        actor_id=admin.id,
        actor_type="admin",
        entity_type="store",
        entity_id=store.id,
        store_id=store.id,
        data={"before": before, "after": list(levels)},
    )
    await session.commit()
    return _notice_out(store)


class NoticeTextItem(BaseModel):
    title: str = Field(min_length=1, max_length=notices.MAX_TITLE)
    body: str = Field(min_length=1, max_length=notices.MAX_BODY)


class NoticeTextsIn(BaseModel):
    texts: dict[str, NoticeTextItem] = Field(
        description="notice kind -> wording; placeholders {store} and {level}; {} clears all custom texts"
    )


class NoticeTextsOut(BaseModel):
    store_id: uuid.UUID
    texts: dict[str, dict[str, str]]
    kinds: list[str] = list(notices.TEXT_KINDS)
    placeholders: list[str] = list(notices.TEXT_TOKENS)


@router.get("/stores/{store_id}/vpn-notice-texts", response_model=NoticeTextsOut)
async def get_store_vpn_notice_texts(store_id: uuid.UUID, _: AdminUser, session: Session):
    store = await session.get(Store, store_id)
    if not store:
        raise NotFound("فروشگاه")
    return NoticeTextsOut(store_id=store.id, texts=notices.texts_for_store(store.vpn_notice_settings))


@router.put("/stores/{store_id}/vpn-notice-texts", response_model=NoticeTextsOut)
async def put_store_vpn_notice_texts(store_id: uuid.UUID, body: NoticeTextsIn, admin: AdminUser, session: Session):
    """PG-06: this store's own wording for customer notices (expiry, low traffic, ...). Replaces the previous set; kinds not listed use the platform text."""
    store = await session.get(Store, store_id)
    if not store:
        raise NotFound("فروشگاه")
    try:
        texts = notices.normalize_texts({k: v.model_dump() for k, v in body.texts.items()})
    except ValueError as exc:
        raise AppError("INVALID_NOTICE_TEXTS", "متن اعلان نامعتبر است", status=422, details={"reason": str(exc)}) from exc
    before = sorted(notices.texts_for_store(store.vpn_notice_settings))
    settings = {**(store.vpn_notice_settings or {})}
    if texts:
        settings["texts"] = texts
    else:
        settings.pop("texts", None)
    store.vpn_notice_settings = settings or None
    audit.record(
        session,
        "store.vpn_notice_texts.updated",
        actor_id=admin.id,
        actor_type="admin",
        entity_type="store",
        entity_id=store.id,
        store_id=store.id,
        data={"before": before, "after": sorted(texts)},
    )
    await session.commit()
    return NoticeTextsOut(store_id=store.id, texts=texts)


class DigestIn(BaseModel):
    enabled: bool


@router.put("/stores/{store_id}/vpn-digest")
async def put_store_vpn_digest(store_id: uuid.UUID, body: DigestIn, admin: AdminUser, session: Session):
    """PG-06: switch the store owner's daily VPN digest on/off (off by default; a day with nothing to report sends nothing)."""
    store = await session.get(Store, store_id)
    if not store:
        raise NotFound("فروشگاه")
    settings = {**(store.vpn_notice_settings or {})}
    before = settings.get("daily_digest") is True
    settings["daily_digest"] = bool(body.enabled)
    store.vpn_notice_settings = settings
    audit.record(
        session,
        "store.vpn_digest.updated",
        actor_id=admin.id,
        actor_type="admin",
        entity_type="store",
        entity_id=store.id,
        store_id=store.id,
        data={"before": before, "after": bool(body.enabled)},
    )
    await session.commit()
    return {"store_id": str(store.id), "daily_digest": bool(body.enabled), "has_owner": store.owner_user_id is not None}


@router.delete("/stores/{store_id}/vpn-notices", response_model=NoticeSettingsOut)
async def reset_store_vpn_notices(store_id: uuid.UUID, admin: AdminUser, session: Session):
    """Back to the platform defaults."""
    store = await session.get(Store, store_id)
    if not store:
        raise NotFound("فروشگاه")
    store.vpn_notice_settings = None
    audit.record(
        session,
        "store.vpn_notices.reset",
        actor_id=admin.id,
        actor_type="admin",
        entity_type="store",
        entity_id=store.id,
        store_id=store.id,
        data={},
    )
    await session.commit()
    return _notice_out(store)
