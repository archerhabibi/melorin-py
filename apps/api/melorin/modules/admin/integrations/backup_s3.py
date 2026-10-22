"""Optional S3 off-site backup copy. Disabled until an admin turns it on."""

import asyncio
import os

from fastapi import APIRouter

from melorin.core import integrations
from melorin.core.deps import AdminUser, Session
from melorin.core.errors import AppError
from melorin.modules.admin.integrations._audit import record_integration
from melorin.modules.admin.integrations.schemas import BackupS3In

router = APIRouter(prefix="/integrations", tags=["admin-integrations"])


@router.put("/backup-s3")
async def update_backup_s3(body: BackupS3In, admin: AdminUser, session: Session):
    cur = await integrations.get_backup_s3(session)
    new = {
        "enabled": body.enabled,
        "endpoint": body.endpoint.strip(),
        "region": body.region.strip(),
        "bucket": body.bucket.strip(),
        "prefix": body.prefix.strip().strip("/"),
        "access_key": body.access_key.strip(),
        "secret_key_enc": integrations.merge_secret(cur.get("secret_key_enc"), body.secret_key),
    }
    if body.enabled and not (new["bucket"] and new["access_key"] and new["secret_key_enc"]):
        raise AppError("S3_CONFIG_INCOMPLETE", "برای فعال‌سازی، Bucket و کلیدهای دسترسی الزامی است.", 400)
    await integrations.save(session, integrations.BACKUP_S3_KEY, new)
    record_integration(
        session,
        admin,
        "backup_s3.updated",
        "backup_s3",
        {"enabled": new["enabled"], "bucket": new["bucket"], "endpoint": new["endpoint"], "prefix": new["prefix"]},
    )
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
            "rclone",
            "lsf",
            "--max-depth",
            "1",
            integrations.rclone_uri(cfg),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
        )
        _, stderr = await asyncio.wait_for(proc.communicate(), timeout=30)
        ok = proc.returncode == 0
        error = None if ok else stderr.decode(errors="replace")[-300:]
    except FileNotFoundError:
        error = "rclone در این کانتینر نصب نیست."
    except TimeoutError:
        error = "اتصال به S3 بیش از ۳۰ ثانیه طول کشید."
    record_integration(session, admin, "backup_s3.tested", "backup_s3", {"ok": ok})
    await session.commit()
    return {"ok": ok, "error": error}
