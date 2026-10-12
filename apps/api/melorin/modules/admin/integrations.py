"""Admin: optional SMTP e-mail and S3 off-site backup. Both are disabled until an admin turns them on."""
import asyncio
import os
from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel, EmailStr, Field

from melorin.core import audit, integrations
from melorin.core.config import get_settings
from melorin.core.deps import AdminUser, Session
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


@router.get("")
async def get_integrations(_: AdminUser, session: Session):
    s = get_settings()
    return {
        "email": integrations.public_email(await integrations.get_email(session)),
        "backup": {
            "local": {"enabled": True, "dir": s.backup_dir, "retention_days": s.backup_retention_days},
            "s3": integrations.public_backup_s3(await integrations.get_backup_s3(session)),
        },
    }


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
