"""Admin: optional SMTP e-mail and S3 off-site backup. Both are disabled until an admin turns them on."""
import asyncio
import ipaddress
import os
from typing import Literal
from urllib.parse import urlparse

import httpx
from fastapi import APIRouter
from pydantic import BaseModel, EmailStr, Field

from melorin.core import audit, integrations
from melorin.core.config import get_settings
from melorin.core.context import client_ip
from melorin.core.deps import AdminUser, Session, ip_allowed
from melorin.core.email import send_with_config
from melorin.core.errors import AppError

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


@router.get("")
async def get_integrations(_: AdminUser, session: Session):
    s = get_settings()
    return {
        "google": _google_public(await integrations.get_google(session)),
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
    """Checks the saved Client ID format and that this server can reach Google's token verifier (egress/DNS/firewall)."""
    cfg = await integrations.get_google(session)
    ok, error = False, None
    if not cfg["client_id"]:
        error = "ابتدا Client ID را ذخیره کنید."
    elif not integrations.GOOGLE_CLIENT_ID_RE.match(cfg["client_id"]):
        error = "فرمت Client ID نامعتبر است."
    else:
        try:
            async with httpx.AsyncClient(timeout=10) as c:
                r = await c.get("https://oauth2.googleapis.com/tokeninfo", params={"id_token": "melorin-connectivity-check"})
            # Google answers 400 invalid_token for a bogus token: the verifier is reachable, which is all we test here.
            ok = r.status_code in (200, 400)
            error = None if ok else f"پاسخ غیرمنتظره از Google: HTTP {r.status_code}"
        except httpx.HTTPError as exc:
            error = f"سرور به Google وصل نشد ({type(exc).__name__}). دسترسی خروجی HTTPS به oauth2.googleapis.com را بررسی کنید."
    audit.record(session, "integration.google.tested", actor_id=admin.id, actor_type="admin", entity_type="integration", entity_id="google", data={"ok": ok})
    await session.commit()
    return {"ok": ok, "error": error}


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
