"""Admin: optional SMTP e-mail and S3 off-site backup. Both are disabled until an admin turns them on."""
import asyncio
import ipaddress
import os
from typing import Literal
from urllib.parse import urlparse

import httpx
from fastapi import APIRouter
from pydantic import BaseModel, EmailStr, Field

from sqlalchemy import select

from melorin.core import audit, integrations
from melorin.core.config import get_settings
from melorin.core.context import client_ip
from melorin.core.crypto import decrypt
from melorin.core.deps import AdminUser, Session, ip_allowed
from melorin.core.email import send_with_config
from melorin.core.errors import AppError
from melorin.modules.identity import telegram_oidc
from melorin.modules.stores.models import Store

router = APIRouter(prefix="/integrations", tags=["admin-integrations"])


class EmailIn(BaseModel):
    enabled: bool
    host: str = Field("", max_length=253)
    port: int = Field(587, ge=1, le=65535)
    username: str = Field("", max_length=200)
    password: str | None = Field(None, max_length=500)  # None keeps the stored password, "" clears it
    from_addr: str = Field("", max_length=254)
    security: Literal["starttls", "ssl", "none"] = "starttls"


class AdminAccessIn(BaseModel):
    enabled: bool
    ips: list[str] = Field(default_factory=list, max_length=50)


class GoogleIn(BaseModel):
    enabled: bool
    client_id: str = Field("", max_length=200)
    admin_login: bool = True
    store_login: bool = True


class TelegramIn(BaseModel):
    enabled: bool
    store_login: bool = True
    bot_login: bool = True
    number_match: bool = True
    ttl_seconds: int = Field(180, ge=integrations.TELEGRAM_TTL_MIN, le=integrations.TELEGRAM_TTL_MAX)
    oidc_login: bool = False
    client_id: str = Field("", max_length=30)
    client_secret: str | None = Field(None, max_length=200)  # None keeps the stored secret, "" clears it


class EmailTestIn(BaseModel):
    to: EmailStr


class BackupS3In(BaseModel):
    enabled: bool
    endpoint: str = Field("", max_length=300)
    region: str = Field("", max_length=60)
    bucket: str = Field("", max_length=100)
    prefix: str = Field("melorin", max_length=200)
    access_key: str = Field("", max_length=200)
    secret_key: str | None = Field(None, max_length=500)  # None keeps, "" clears


def _origin(url: str) -> str | None:
    """Reduce a URL to ``scheme://host[:port]`` - the only form Google accepts as an Authorized JavaScript origin."""
    p = urlparse((url or "").strip())
    return f"{p.scheme}://{p.netloc}" if p.scheme in ("http", "https") and p.netloc else None


def _google_public(cfg: dict) -> dict:
    s = get_settings()
    origins = list(dict.fromkeys(o for u in [s.store_web_url, s.public_api_url, *s.cors_origins] if (o := _origin(u))))
    return {
        "enabled": bool(cfg["enabled"]), "client_id": cfg["client_id"], "admin_login": bool(cfg["admin_login"]),
        "store_login": bool(cfg["store_login"]), "source": cfg["source"], "suggested_origins": origins,
    }


async def _main_bot(session: Session) -> tuple[str, str]:
    """(bot token, @username) of the main store's bot; the env token is the fallback. Never leaves this module."""
    main = await session.scalar(select(Store).where(Store.kind == "main"))
    token = (decrypt(main.bot_token_enc) if main and main.bot_token_enc else "") or get_settings().main_bot_token or ""
    return token, (main.bot_username or "").lstrip("@") if main else ""


async def _telegram_public(session: Session, cfg: dict) -> dict:
    token, username = await _main_bot(session)
    main = await session.scalar(select(Store).where(Store.kind == "main"))
    domains = (await session.scalars(select(Store.domain).where(Store.kind == "reseller", Store.status == "active", Store.domain.is_not(None)))).all()
    origins = list(dict.fromkeys([telegram_oidc.callback_origin(main), *(f"https://{d.strip().lower()}" for d in domains if d)]))
    return {
        "enabled": bool(cfg["enabled"]), "store_login": bool(cfg["store_login"]), "bot_login": bool(cfg["bot_login"]),
        "number_match": bool(cfg["number_match"]), "ttl_seconds": integrations.telegram_ttl(cfg),
        "oidc_login": bool(cfg["oidc_login"]), "client_id": cfg["client_id"], "client_secret_set": bool(cfg.get("client_secret_enc")),
        "source": cfg["source"], "main_bot_username": username, "suggested_client_id": telegram_oidc.bot_id_of(token) or "",
        "origins": origins, "redirect_uris": [telegram_oidc.redirect_uri(o) for o in origins],
        "ttl_min": integrations.TELEGRAM_TTL_MIN, "ttl_max": integrations.TELEGRAM_TTL_MAX,
    }


@router.get("")
async def get_integrations(_: AdminUser, session: Session):
    s = get_settings()
    return {
        "google": _google_public(await integrations.get_google(session)),
        "telegram": await _telegram_public(session, await integrations.get_telegram(session)),
        "admin_access": {**await integrations.get_admin_access(session), "your_ip": client_ip.get()},
        "email": integrations.public_email(await integrations.get_email(session)),
        "backup": {
            "local": {"enabled": True, "dir": s.backup_dir, "retention_days": s.backup_retention_days},
            "s3": integrations.public_backup_s3(await integrations.get_backup_s3(session)),
        },
    }


@router.put("/admin-access")
async def update_admin_access(body: AdminAccessIn, admin: AdminUser, session: Session):
    ips: list[str] = []
    for raw in body.ips:
        value = raw.strip()
        if not value:
            continue
        try:
            ips.append(str(ipaddress.ip_network(value, strict=False)))
        except ValueError:
            raise AppError("ADMIN_IP_INVALID", f"آدرس IP یا CIDR نامعتبر است: {value}", 400) from None
    ips = list(dict.fromkeys(ips))
    if body.enabled:
        if not ips:
            raise AppError("ADMIN_IP_EMPTY", "برای فعال‌سازی، حداقل یک IP یا CIDR لازم است.", 400)
        if not ip_allowed(client_ip.get(), ips):
            raise AppError("ADMIN_IP_LOCKOUT", "IP فعلی شما در فهرست نیست؛ با این تنظیم از پنل بیرون می‌افتید. IP خودتان را هم اضافه کنید.", 400)
    new = {"enabled": body.enabled, "ips": ips}
    await integrations.save(session, integrations.ADMIN_ACCESS_KEY, new)
    audit.record(session, "integration.admin_access.updated", actor_id=admin.id, actor_type="admin", entity_type="integration",
                 entity_id="admin_access", data=new)
    await session.commit()
    return {**new, "your_ip": client_ip.get()}


@router.put("/google")
async def update_google(body: GoogleIn, admin: AdminUser, session: Session):
    client_id = body.client_id.strip()
    if client_id and not integrations.GOOGLE_CLIENT_ID_RE.match(client_id):
        raise AppError("GOOGLE_CLIENT_ID_INVALID", "فرمت Client ID درست نیست؛ باید مانند 123456789-abc.apps.googleusercontent.com باشد.", 400)
    if body.enabled and not client_id:
        raise AppError("GOOGLE_CONFIG_INCOMPLETE", "برای فعال‌سازی، Client ID الزامی است.", 400)
    if body.enabled and not (body.admin_login or body.store_login):
        raise AppError("GOOGLE_NO_SURFACE", "حداقل یکی از ورود ادمین یا ورود مشتریان باید فعال باشد.", 400)
    new = {"enabled": body.enabled, "client_id": client_id, "admin_login": body.admin_login, "store_login": body.store_login}
    await integrations.save(session, integrations.GOOGLE_KEY, new)
    audit.record(session, "integration.google.updated", actor_id=admin.id, actor_type="admin", entity_type="integration", entity_id="google", data=new)
    await session.commit()
    return _google_public({**new, "source": "panel"})


@router.post("/google/test")
async def test_google(admin: AdminUser, session: Session):
    """Checks the saved Client ID format and that this server can fetch Google's public signing keys (egress/DNS/firewall)."""
    cfg = await integrations.get_google(session)
    ok, error = False, None
    if not cfg["client_id"]:
        error = "ابتدا Client ID را ذخیره کنید."
    elif not integrations.GOOGLE_CLIENT_ID_RE.match(cfg["client_id"]):
        error = "فرمت Client ID نامعتبر است."
    else:
        try:
            async with httpx.AsyncClient(timeout=10) as c:
                r = await c.get("https://www.googleapis.com/oauth2/v3/certs")
            # These are the public keys the server verifies Google ID tokens with: reachable + well-formed is all we test.
            ok = r.status_code == 200 and bool(r.json().get("keys"))
            error = None if ok else f"پاسخ غیرمنتظره از Google: HTTP {r.status_code}"
        except (httpx.HTTPError, ValueError) as exc:
            error = f"سرور به Google وصل نشد ({type(exc).__name__}). دسترسی خروجی HTTPS به www.googleapis.com را بررسی کنید."
    audit.record(session, "integration.google.tested", actor_id=admin.id, actor_type="admin", entity_type="integration", entity_id="google", data={"ok": ok})
    await session.commit()
    return {"ok": ok, "error": error}


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
        "enabled": body.enabled, "store_login": body.store_login, "bot_login": body.bot_login, "number_match": body.number_match,
        "ttl_seconds": body.ttl_seconds, "oidc_login": body.oidc_login, "client_id": client_id, "client_secret_enc": secret,
    }
    await integrations.save(session, integrations.TELEGRAM_KEY, new)
    audit.record(session, "integration.telegram.updated", actor_id=admin.id, actor_type="admin", entity_type="integration", entity_id="telegram",
                 data={k: v for k, v in new.items() if k != "client_secret_enc"} | {"client_secret_set": bool(secret)})
    await session.commit()
    return await _telegram_public(session, {**new, "source": "panel"})


def _check(key: str, status: str, message: str) -> dict:
    return {"key": key, "status": status, "message": message}  # status: ok | warn | fail


@router.post("/telegram/test")
async def test_telegram(admin: AdminUser, session: Session):
    """Read-only diagnostics on the SAVED config: Telegram OIDC reachability, key set, Client ID vs. the main bot, bot username."""
    cfg = await integrations.get_telegram(session)
    token, username = await _main_bot(session)
    checks: list[dict] = []
    if not cfg["enabled"]:
        checks.append(_check("enabled", "warn", "کلید اصلی «ورود با تلگرام» خاموش است؛ دکمه‌ای در فروشگاه نمایش داده نمی‌شود."))
    elif not cfg["store_login"]:
        checks.append(_check("store_login", "warn", "«ورود مشتریان (فروشگاه)» خاموش است؛ دکمه‌ای در فروشگاه نمایش داده نمی‌شود."))
    if cfg["oidc_login"]:
        origin = telegram_oidc.callback_origin(await session.scalar(select(Store).where(Store.kind == "main")))
        host = origin.split("://", 1)[1]
        if not origin.startswith("https://") or host.split(":")[0] in ("localhost", "127.0.0.1"):
            checks.append(_check("site_url", "fail" if not get_settings().is_dev else "warn",
                                 f"آدرس فروشگاه ({origin}) https عمومی نیست. تلگرام فقط به آدرس‌های https ثبت‌شده برمی‌گرداند؛ MELORIN_STORE_WEB_URL را در .env اصلاح کنید."))
        else:
            checks.append(_check("site_url", "ok", f"آدرس بازگشت: {telegram_oidc.redirect_uri(origin)} (باید در Allowed URLs ثبت شده باشد)."))
    async with httpx.AsyncClient(timeout=10) as c:
        if cfg["oidc_login"]:
            try:
                doc = (await c.get(telegram_oidc.DISCOVERY_URL)).json()
                ok = doc.get("issuer") == telegram_oidc.ISSUER
                checks.append(_check("discovery", "ok" if ok else "fail", "سرور به oauth.telegram.org دسترسی دارد." if ok else "پاسخ Discovery تلگرام غیرمنتظره بود."))
            except (httpx.HTTPError, ValueError) as exc:
                checks.append(_check("discovery", "fail", f"سرور به oauth.telegram.org وصل نشد ({type(exc).__name__}). دسترسی خروجی HTTPS/DNS/فایروال را بررسی کنید."))
            try:
                keys = (await c.get(telegram_oidc.JWKS_URL)).json().get("keys", [])
                checks.append(_check("jwks", "ok" if keys else "fail", f"{len(keys)} کلید امضا از تلگرام دریافت شد." if keys else "کلید امضایی از تلگرام دریافت نشد."))
            except (httpx.HTTPError, ValueError) as exc:
                checks.append(_check("jwks", "fail", f"دریافت کلیدهای امضا ناموفق بود ({type(exc).__name__})."))
            cid = cfg["client_id"]
            if not cid:
                checks.append(_check("client_id", "fail", "Client ID ذخیره نشده است."))
            else:
                bot_id = telegram_oidc.bot_id_of(token)
                if bot_id and bot_id != cid:
                    checks.append(_check("client_id", "warn", f"Client ID با شناسهٔ ربات اصلی ({bot_id}) یکی نیست. اگر عمداً از ربات دیگری استفاده می‌کنید مشکلی نیست."))
                else:
                    checks.append(_check("client_id", "ok", "Client ID با ربات اصلی هم‌خوان است." if bot_id else "Client ID ذخیره شده است."))
            if not cfg.get("client_secret_enc") or not cid:
                checks.append(_check("credentials", "fail", "Client Secret ذخیره نشده است."))
            else:
                try:
                    r = await c.post(telegram_oidc.TOKEN_URL, auth=(cid, integrations.telegram_client_secret(cfg)),
                                     data={"grant_type": "authorization_code", "code": "melorin-connectivity-check", "client_id": cid,
                                           "redirect_uri": telegram_oidc.redirect_uri(telegram_oidc.callback_origin(None)), "code_verifier": "x" * 43})
                    err = telegram_oidc._oauth_error(r)
                    if r.status_code == 401 or err == "invalid_client":
                        checks.append(_check("credentials", "fail", "تلگرام Client ID/Secret را نپذیرفت. هر دو را دوباره از BotFather کپی کنید."))
                    elif r.status_code >= 500:
                        checks.append(_check("credentials", "warn", "سرور تلگرام خطا داد؛ بررسی اعتبارنامه انجام نشد. کمی بعد دوباره تست کنید."))
                    else:
                        checks.append(_check("credentials", "ok", "تلگرام اعتبارنامه را رد نکرد (درستی نهایی با یک ورود واقعی مشخص می‌شود)."))
                except (httpx.HTTPError, ValueError) as exc:
                    checks.append(_check("credentials", "warn", f"بررسی اعتبارنامه انجام نشد ({type(exc).__name__})."))
        if cfg["bot_login"]:
            if not token:
                checks.append(_check("bot", "fail", "توکن ربات اصلی تنظیم نشده است."))
            else:
                try:
                    r = await c.get(f"https://api.telegram.org/bot{token}/getMe")
                    me = (r.json() or {}).get("result") or {}
                    if r.status_code != 200 or not me:
                        checks.append(_check("bot", "fail", "تلگرام توکن ربات اصلی را نپذیرفت (توکن ابطال یا اشتباه است)."))
                    elif not username:
                        checks.append(_check("bot", "fail", f"نام کاربری ربات روی فروشگاه ثبت نشده است (ربات واقعی: @{me.get('username')}). بدون آن لینک ورود ساخته نمی‌شود؛ آن را در تنظیمات فروشگاه وارد کنید."))
                    elif (me.get("username") or "").lower() != username.lower():
                        checks.append(_check("bot", "warn", f"نام کاربری ربات در فروشگاه (@{username}) با ربات واقعی (@{me.get('username')}) یکی نیست."))
                    else:
                        checks.append(_check("bot", "ok", f"ربات @{me.get('username')} در دسترس است."))
                except (httpx.HTTPError, ValueError) as exc:
                    checks.append(_check("bot", "fail", f"سرور به api.telegram.org وصل نشد ({type(exc).__name__})."))
    if not checks:
        checks.append(_check("none", "warn", "هیچ روشی برای تست فعال نیست."))
    ok = all(x["status"] != "fail" for x in checks)
    audit.record(session, "integration.telegram.tested", actor_id=admin.id, actor_type="admin", entity_type="integration", entity_id="telegram", data={"ok": ok})
    await session.commit()
    return {"ok": ok, "checks": checks}


@router.put("/email")
async def update_email(body: EmailIn, admin: AdminUser, session: Session):
    cur = await integrations.get_email(session)
    new = {
        "enabled": body.enabled, "host": body.host.strip(), "port": body.port, "username": body.username.strip(),
        "password_enc": integrations.merge_secret(cur.get("password_enc"), body.password),
        "from_addr": body.from_addr.strip(), "security": body.security,
    }
    if body.enabled and not (new["host"] and new["from_addr"]):
        raise AppError("EMAIL_CONFIG_INCOMPLETE", "برای فعال‌سازی، میزبان SMTP و آدرس فرستنده الزامی است.", 400)
    await integrations.save(session, integrations.EMAIL_KEY, new)
    audit.record(session, "integration.email.updated", actor_id=admin.id, actor_type="admin", entity_type="integration", entity_id="email",
                 data={"enabled": new["enabled"], "host": new["host"], "port": new["port"], "security": new["security"]})
    await session.commit()
    return integrations.public_email(new)


@router.post("/email/test")
async def test_email(body: EmailTestIn, admin: AdminUser, session: Session):
    cfg = await integrations.get_email(session)
    if not (cfg["host"] and cfg["from_addr"]):
        raise AppError("EMAIL_CONFIG_INCOMPLETE", "ابتدا میزبان SMTP و آدرس فرستنده را ذخیره کنید.", 400)
    smtp_cfg = {"host": cfg["host"], "port": int(cfg["port"]), "username": cfg["username"],
                "password": integrations.email_password(cfg), "from_addr": cfg["from_addr"], "security": cfg["security"]}
    try:
        await send_with_config(smtp_cfg, str(body.to), "تست ایمیل Melorin", "اگر این پیام را می‌بینید، تنظیمات SMTP درست است.")
        ok, error = True, None
    except Exception as exc:  # report the reason to the admin; never include credentials
        ok, error = False, f"{type(exc).__name__}: {str(exc)[:200]}"
    audit.record(session, "integration.email.tested", actor_id=admin.id, actor_type="admin", entity_type="integration", entity_id="email", data={"ok": ok})
    await session.commit()
    return {"ok": ok, "error": error}


@router.put("/backup-s3")
async def update_backup_s3(body: BackupS3In, admin: AdminUser, session: Session):
    cur = await integrations.get_backup_s3(session)
    new = {
        "enabled": body.enabled, "endpoint": body.endpoint.strip(), "region": body.region.strip(), "bucket": body.bucket.strip(),
        "prefix": body.prefix.strip().strip("/"), "access_key": body.access_key.strip(),
        "secret_key_enc": integrations.merge_secret(cur.get("secret_key_enc"), body.secret_key),
    }
    if body.enabled and not (new["bucket"] and new["access_key"] and new["secret_key_enc"]):
        raise AppError("S3_CONFIG_INCOMPLETE", "برای فعال‌سازی، Bucket و کلیدهای دسترسی الزامی است.", 400)
    await integrations.save(session, integrations.BACKUP_S3_KEY, new)
    audit.record(session, "integration.backup_s3.updated", actor_id=admin.id, actor_type="admin", entity_type="integration", entity_id="backup_s3",
                 data={"enabled": new["enabled"], "bucket": new["bucket"], "endpoint": new["endpoint"], "prefix": new["prefix"]})
    await session.commit()
    return integrations.public_backup_s3(new)


@router.post("/backup-s3/test")
async def test_backup_s3(admin: AdminUser, session: Session):
    cfg = await integrations.get_backup_s3(session)
    if not (cfg["bucket"] and cfg["access_key"] and cfg["secret_key_enc"]):
        raise AppError("S3_CONFIG_INCOMPLETE", "ابتدا Bucket و کلیدهای دسترسی را ذخیره کنید.", 400)
    env = {**os.environ, **integrations.rclone_env(cfg)}
    ok, error = False, None
    try:
        proc = await asyncio.create_subprocess_exec(
            "rclone", "lsf", "--max-depth", "1", integrations.rclone_uri(cfg),
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE, env=env,
        )
        _, stderr = await asyncio.wait_for(proc.communicate(), timeout=30)
        ok = proc.returncode == 0
        error = None if ok else stderr.decode(errors="replace")[-300:]
    except FileNotFoundError:
        error = "rclone در این کانتینر نصب نیست."
    except TimeoutError:
        error = "اتصال به S3 بیش از ۳۰ ثانیه طول کشید."
    audit.record(session, "integration.backup_s3.tested", actor_id=admin.id, actor_type="admin", entity_type="integration", entity_id="backup_s3", data={"ok": ok})
    await session.commit()
    return {"ok": ok, "error": error}
