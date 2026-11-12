"""Admin API - Telegram button styles: colour, Premium custom emoji and decoration of the bots' buttons.

``GET/PUT /admin/telegram/button-styles`` edit the configuration, ``POST .../preview`` sends a sample keyboard to the
admin's own Telegram (so a rejected Premium emoji id is seen immediately), and the public, secret-free
``GET /telegram/button-styles`` is what the main and reseller bots download (they cache it for a short time).
"""

from typing import Any

from fastapi import APIRouter, Response
from pydantic import BaseModel, Field

from melorin.channels.telegram.bot_api import TelegramApiError, TelegramChannel
from melorin.core import admin_telegram, audit, integrations, settings_store
from melorin.core.deps import AdminUser, Session
from melorin.core.errors import AppError
from melorin.domain import button_style as bs
from melorin.modules.admin.integrations.telegram_login import _main_bot

router = APIRouter(prefix="/admin", tags=["admin"])
public = APIRouter(tags=["telegram"])

PUBLIC_CACHE_SECONDS = 30


class ButtonStylesIn(BaseModel):
    enabled: bool = False
    rules: list[dict[str, Any]] = Field(default_factory=list, max_length=bs.MAX_RULES)


async def _load(session) -> dict[str, Any]:
    return bs.stored(await settings_store.get(session, integrations.BUTTON_STYLES_KEY))


def _view(cfg: dict[str, Any]) -> dict[str, Any]:
    return {
        "config": cfg,
        "catalog": list(bs.CATALOG),
        "presets": list(bs.PRESETS),
        "styles": [{"id": s, "label": bs.STYLE_LABEL[s]} for s in bs.STYLES],
        "limits": {"max_rules": bs.MAX_RULES, "max_decor": bs.MAX_DECOR, "url_key": bs.URL_KEY},
    }


def _invalid(exc: bs.ButtonStyleError) -> AppError:
    return AppError("BUTTON_STYLE_INVALID", str(exc), 422)


def _telegram_failure(exc: TelegramApiError) -> AppError:
    """Tell the admin what really went wrong: only a 400 is Telegram refusing the style / Premium emoji itself."""
    if exc.code == 403:
        return AppError(
            "TELEGRAM_CHAT_UNREACHABLE",
            "ربات اصلی اجازهٔ پیام دادن به تلگرام شما را ندارد؛ ابتدا ربات را در تلگرام باز کنید و Start بزنید (یا ربات را آزاد کنید).",
            409,
        )
    if exc.code == 401:
        return AppError("MAIN_BOT_TOKEN_INVALID", "توکن ربات اصلی معتبر نیست؛ آن را در تنظیمات ربات بررسی کنید.", 409)
    if exc.code == 429:
        return AppError("TELEGRAM_RATE_LIMITED", "تلگرام موقتاً درخواست‌ها را محدود کرده است؛ چند لحظه بعد دوباره امتحان کنید.", 429)
    if exc.code >= 500:
        return AppError("TELEGRAM_UNREACHABLE", "اتصال به تلگرام برقرار نشد؛ کمی بعد دوباره امتحان کنید.", 502)
    return AppError(
        "TELEGRAM_REJECTED_STYLE",
        f"تلگرام پیش‌نمایش را نپذیرفت: {exc.description}. اگر ایموجی پریمیوم گذاشته‌اید، مطمئن شوید شناسه درست است و صاحب ربات اشتراک Premium دارد.",
        422,
    )


@router.get("/telegram/button-styles")
async def get_button_styles(_: AdminUser, session: Session):
    return _view(await _load(session))


@router.put("/telegram/button-styles")
async def put_button_styles(body: ButtonStylesIn, admin: AdminUser, session: Session):
    try:
        cfg = bs.normalize(body.model_dump())
    except bs.ButtonStyleError as exc:
        raise _invalid(exc) from exc
    await integrations.save(session, integrations.BUTTON_STYLES_KEY, cfg)
    audit.record(
        session,
        "integration.telegram.button_styles.updated",
        actor_id=admin.id,
        actor_type="admin",
        entity_type="integration",
        entity_id="telegram_button_styles",
        data={"enabled": cfg["enabled"], "rules": len(cfg["rules"])},
    )
    await session.commit()
    return _view(cfg)


@router.post("/telegram/button-styles/preview")
async def preview_button_styles(body: ButtonStylesIn, admin: AdminUser, session: Session):
    """Send a sample of the submitted (not necessarily saved) styling to the admin's own Telegram chat."""
    try:
        cfg = bs.normalize({**body.model_dump(), "enabled": True})
    except bs.ButtonStyleError as exc:
        raise _invalid(exc) from exc
    chat_id = await admin_telegram.current(session, admin.id)
    if not chat_id:
        raise AppError("ADMIN_TELEGRAM_MISSING", "آیدی عددی تلگرام شما در سیستم ثبت نشده است؛ ابتدا آن را ثبت کنید.", 409)
    token, _username = await _main_bot(session)
    if not token:
        raise AppError("MAIN_BOT_TOKEN_MISSING", "توکن ربات اصلی تنظیم نشده است.", 409)
    inline, reply = bs.sample_markups(cfg)
    channel = TelegramChannel(token=token, core_base_url="http://core.invalid", channel="main")
    try:
        await channel.call("sendMessage", {"chat_id": chat_id, "text": "پیش‌نمایش دکمه‌های اینلاین", "reply_markup": inline})
        await channel.call("sendMessage", {"chat_id": chat_id, "text": "پیش‌نمایش کیبورد پایین", "reply_markup": reply})
    except TelegramApiError as exc:
        raise _telegram_failure(exc) from exc
    return {"ok": True}


@public.get("/telegram/button-styles")
async def public_button_styles(response: Response, session: Session):
    """Secret-free styling the bots apply when they build keyboards (nothing but keys, colours, emoji ids, decoration)."""
    response.headers["Cache-Control"] = f"public, max-age={PUBLIC_CACHE_SECONDS}"
    return bs.public_projection(await _load(session))
