"""Admin integrations API (``/admin/integrations``): login providers, admin IP allow-list, SMTP e-mail, S3 backup.

Split by integration from one 600-line module; paths, methods, schemas and operation ids are unchanged. The family
modules carry their own ``/integrations`` prefix and tag, so their routes are attached to this package's router
directly (the overview route has an empty sub-path, which ``include_router`` would refuse).
"""

import httpx  # noqa: F401  (tests patch ``admin_integrations.httpx.AsyncClient``)
from fastapi import APIRouter

from melorin.core import integrations
from melorin.core.config import get_settings
from melorin.core.context import client_ip
from melorin.core.deps import AdminUser, Session
from melorin.modules.admin.integrations import admin_access, backup_s3, email_smtp, google_login, receipt_ocr, telegram_login
from melorin.modules.admin.integrations.admin_access import update_admin_access
from melorin.modules.admin.integrations.backup_s3 import test_backup_s3, update_backup_s3
from melorin.modules.admin.integrations.email_smtp import test_email, update_email
from melorin.modules.admin.integrations.google_login import google_public, test_google, update_google
from melorin.modules.admin.integrations.schemas import (  # noqa: F401
    AdminAccessIn,
    BackupS3In,
    EmailIn,
    EmailTestIn,
    GoogleIn,
    MainBotIn,
    ReceiptOcrIn,
    TelegramIn,
)
from melorin.modules.admin.integrations.telegram_login import set_main_bot_username, telegram_public, test_telegram, update_telegram

overview = APIRouter(prefix="/integrations", tags=["admin-integrations"])


@overview.get("")
async def get_integrations(_: AdminUser, session: Session):
    s = get_settings()
    return {
        "google": google_public(await integrations.get_google(session)),
        "telegram": await telegram_public(session, await integrations.get_telegram(session)),
        "admin_access": {**await integrations.get_admin_access(session), "your_ip": client_ip.get()},
        "receipt_ocr": receipt_ocr.receipt_ocr_public(await integrations.get_receipt_ocr(session)),
        "email": integrations.public_email(await integrations.get_email(session)),
        "backup": {
            "local": {"enabled": True, "dir": s.backup_dir, "retention_days": s.backup_retention_days},
            "s3": integrations.public_backup_s3(await integrations.get_backup_s3(session)),
        },
    }


router = APIRouter()
for _family in (
    overview,
    admin_access.router,
    google_login.router,
    telegram_login.router,
    receipt_ocr.router,
    email_smtp.router,
    backup_s3.router,
):
    router.routes.extend(_family.routes)

__all__ = [
    "router",
    "get_integrations",
    "update_admin_access",
    "update_google",
    "test_google",
    "update_telegram",
    "set_main_bot_username",
    "test_telegram",
    "update_email",
    "test_email",
    "update_backup_s3",
    "test_backup_s3",
]
