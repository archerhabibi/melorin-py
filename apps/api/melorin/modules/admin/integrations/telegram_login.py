"""Sign in with Telegram: login settings, the main store's bot @username, and the diagnostics endpoint."""

import httpx
from fastapi import APIRouter
from sqlalchemy import func, select

from melorin.channels.telegram import oidc as telegram_oidc
from melorin.channels.telegram.web import normalise_bot_username
from melorin.core import audit, integrations
from melorin.core.config import get_settings
from melorin.core.crypto import decrypt
from melorin.core.deps import AdminUser, Session
from melorin.core.errors import AppError
from melorin.kernel.models.stores import BotStoreBinding, Store
from melorin.modules.admin.integrations._audit import record_integration
from melorin.modules.admin.integrations.schemas import MainBotIn, TelegramIn
from melorin.modules.admin.integrations.telegram_diagnostics import run_diagnostics

router = APIRouter(prefix="/integrations", tags=["admin-integrations"])


async def _main_bot(session: Session) -> tuple[str, str]:
    """(bot token, @username) of the main store's bot; the env token is the fallback. Never leaves this module."""
    main = await session.scalar(select(Store).where(Store.kind == "main"))
    token = (decrypt(main.bot_token_enc) if main and main.bot_token_enc else "") or get_settings().main_bot_token or ""
    return token, (main.bot_username or "").lstrip("@") if main else ""


async def telegram_public(session: Session, cfg: dict) -> dict:
    token, username = await _main_bot(session)
    main = await session.scalar(select(Store).where(Store.kind == "main"))
    domains = (
        await session.scalars(select(Store.domain).where(Store.kind == "reseller", Store.status == "active", Store.domain.is_not(None)))
    ).all()
    origins = list(dict.fromkeys([telegram_oidc.callback_origin(main), *(f"https://{d.strip().lower()}" for d in domains if d)]))
    return {
        "enabled": bool(cfg["enabled"]),
        "store_login": bool(cfg["store_login"]),
        "bot_login": bool(cfg["bot_login"]),
        "number_match": bool(cfg["number_match"]),
        "ttl_seconds": integrations.telegram_ttl(cfg),
        "oidc_login": bool(cfg["oidc_login"]),
        "client_id": cfg["client_id"],
        "client_secret_set": bool(cfg.get("client_secret_enc")),
        "source": cfg["source"],
        "main_bot_username": username,
        "suggested_client_id": telegram_oidc.bot_id_of(token) or "",
        "origins": origins,
        "redirect_uris": [telegram_oidc.redirect_uri(o) for o in origins],
        "ttl_min": integrations.TELEGRAM_TTL_MIN,
        "ttl_max": integrations.TELEGRAM_TTL_MAX,
    }


@router.put("/telegram")
async def update_telegram(body: TelegramIn, admin: AdminUser, session: Session):
    cur = await integrations.get_telegram(session)
    client_id = body.client_id.strip()
    if client_id and not integrations.TELEGRAM_CLIENT_ID_RE.match(client_id):
        raise AppError("TELEGRAM_CLIENT_ID_INVALID", "Client ID تلگرام فقط عدد است (همان شناسهٔ عددی ربات، مثلاً 123456789).", 400)
    secret = integrations.merge_secret(cur.get("client_secret_enc"), body.client_secret.strip() if body.client_secret is not None else None)
    if body.enabled and not (body.bot_login or body.oidc_login):
        raise AppError("TELEGRAM_NO_METHOD", "حداقل یکی از دو روش ورود (تأیید در ربات یا ورود مستقیم تلگرام) باید فعال باشد.", 400)
    if body.enabled and body.oidc_login and not (client_id and secret):
        raise AppError("TELEGRAM_CONFIG_INCOMPLETE", "برای فعال‌سازی ورود مستقیم تلگرام، Client ID و Client Secret الزامی است.", 400)
    new = {
        "enabled": body.enabled,
        "store_login": body.store_login,
        "bot_login": body.bot_login,
        "number_match": body.number_match,
        "ttl_seconds": body.ttl_seconds,
        "oidc_login": body.oidc_login,
        "client_id": client_id,
        "client_secret_enc": secret,
    }
    await integrations.save(session, integrations.TELEGRAM_KEY, new)
    record_integration(
        session,
        admin,
        "telegram.updated",
        "telegram",
        {k: v for k, v in new.items() if k != "client_secret_enc"} | {"client_secret_set": bool(secret)},
    )
    await session.commit()
    return await telegram_public(session, {**new, "source": "panel"})


async def _bot_get_me(token: str) -> tuple[bool, str | None]:
    """(reachable, username). ``reachable`` is False only on network failure; a rejected token gives (True, None)."""
    try:
        async with httpx.AsyncClient(timeout=10) as c:
            r = await c.get(f"https://api.telegram.org/bot{token}/getMe")
        me = (r.json() or {}).get("result") or {}
        return True, (me.get("username") or None) if r.status_code == 200 else None
    except (httpx.HTTPError, ValueError):
        return False, None


def _resolve_bot_username(raw: str, token: str, reachable: bool, real: str | None) -> str:
    """The @username to store, or an ``AppError`` explaining why not.

    A typed name is checked against the bot the token really belongs to (when Telegram could be reached);
    an empty one is detected from the token.
    """
    if raw:
        name = normalise_bot_username(raw)
        if not name:
            raise AppError(
                "BOT_USERNAME_INVALID", "نام کاربری ربات فقط شامل حروف انگلیسی، عدد و _ است (۳ تا ۶۴ نویسه)، مثلاً @meeloorin_bot.", 400
            )
        if token and reachable and not real:
            raise AppError("BOT_TOKEN_REJECTED", "تلگرام توکن ربات اصلی را نپذیرفت؛ ابتدا توکن را اصلاح کنید.", 400)
        if real and real.lower() != name.lower():
            raise AppError("BOT_USERNAME_MISMATCH", f"این نام کاربری با ربات واقعیِ توکن (@{real}) یکی نیست.", 400)
        return name
    if not token:
        raise AppError("BOT_TOKEN_MISSING", "توکن ربات اصلی تنظیم نشده است؛ نام کاربری را دستی وارد کنید.", 400)
    if not reachable:
        raise AppError(
            "TELEGRAM_UNREACHABLE", "سرور به api.telegram.org وصل نشد؛ نام کاربری را دستی وارد کنید یا دسترسی خروجی را بررسی کنید.", 502
        )
    name = normalise_bot_username(real)
    if not name:
        raise AppError("BOT_TOKEN_REJECTED", "تلگرام توکن ربات اصلی را نپذیرفت (ابطال یا اشتباه است).", 400)
    return name


@router.put("/telegram/main-bot-username")
async def set_main_bot_username(body: MainBotIn, admin: AdminUser, session: Session):
    """Stores the main store's bot @username (needed to build the login deep link). Empty body = detect it from the token."""
    main = await session.scalar(select(Store).where(Store.kind == "main"))
    if not main:
        raise AppError("MAIN_STORE_NOT_FOUND", "فروشگاه اصلی پیدا نشد.", 404)
    token, _ = await _main_bot(session)
    raw = (body.username or "").strip()
    reachable, real = (await _bot_get_me(token)) if token else (False, None)
    name = _resolve_bot_username(raw, token, reachable, real)
    taken = await session.scalar(select(Store.id).where(func.lower(Store.bot_username) == name.lower(), Store.id != main.id))
    if taken:
        raise AppError("BOT_USERNAME_TAKEN", "این نام کاربری برای فروشگاه دیگری ثبت شده است.", 409)
    old = main.bot_username
    main.bot_username = name
    binding = await session.scalar(select(BotStoreBinding).where(BotStoreBinding.store_id == main.id))
    if binding:
        binding.bot_username = name
    audit.record(
        session,
        "integration.telegram.main_bot_username",
        actor_id=admin.id,
        actor_type="admin",
        entity_type="store",
        entity_id=main.id,
        store_id=main.id,
        data={"old": old, "new": name, "verified": bool(real)},
    )
    await session.commit()
    return await telegram_public(session, await integrations.get_telegram(session))


@router.post("/telegram/test")
async def test_telegram(admin: AdminUser, session: Session):
    """Read-only diagnostics on the SAVED config: Telegram OIDC reachability, key set, Client ID vs. the main bot, bot username."""
    cfg = await integrations.get_telegram(session)
    token, username = await _main_bot(session)
    main = await session.scalar(select(Store).where(Store.kind == "main")) if cfg["oidc_login"] else None
    checks = await run_diagnostics(cfg, token, username, main)
    ok = all(x["status"] != "fail" for x in checks)
    record_integration(session, admin, "telegram.tested", "telegram", {"ok": ok})
    await session.commit()
    return {"ok": ok, "checks": checks}
