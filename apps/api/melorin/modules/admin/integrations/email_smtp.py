"""Optional SMTP e-mail. Disabled until an admin turns it on."""

from fastapi import APIRouter

from melorin.core import integrations
from melorin.core.deps import AdminUser, Session
from melorin.core.email import send_with_config
from melorin.core.errors import AppError
from melorin.modules.admin.integrations._audit import record_integration
from melorin.modules.admin.integrations.schemas import EmailIn, EmailTestIn

router = APIRouter(prefix="/integrations", tags=["admin-integrations"])


@router.put("/email")
async def update_email(body: EmailIn, admin: AdminUser, session: Session):
    cur = await integrations.get_email(session)
    new = {
        "enabled": body.enabled,
        "host": body.host.strip(),
        "port": body.port,
        "username": body.username.strip(),
        "password_enc": integrations.merge_secret(cur.get("password_enc"), body.password),
        "from_addr": body.from_addr.strip(),
        "security": body.security,
    }
    if body.enabled and not (new["host"] and new["from_addr"]):
        raise AppError("EMAIL_CONFIG_INCOMPLETE", "برای فعال‌سازی، میزبان SMTP و آدرس فرستنده الزامی است.", 400)
    await integrations.save(session, integrations.EMAIL_KEY, new)
    record_integration(
        session,
        admin,
        "email.updated",
        "email",
        {"enabled": new["enabled"], "host": new["host"], "port": new["port"], "security": new["security"]},
    )
    await session.commit()
    return integrations.public_email(new)


@router.post("/email/test")
async def test_email(body: EmailTestIn, admin: AdminUser, session: Session):
    cfg = await integrations.get_email(session)
    if not (cfg["host"] and cfg["from_addr"]):
        raise AppError("EMAIL_CONFIG_INCOMPLETE", "ابتدا میزبان SMTP و آدرس فرستنده را ذخیره کنید.", 400)
    smtp_cfg = {
        "host": cfg["host"],
        "port": int(cfg["port"]),
        "username": cfg["username"],
        "password": integrations.email_password(cfg),
        "from_addr": cfg["from_addr"],
        "security": cfg["security"],
    }
    try:
        await send_with_config(smtp_cfg, str(body.to), "تست ایمیل Melorin", "اگر این پیام را می‌بینید، تنظیمات SMTP درست است.")
        ok, error = True, None
    except Exception as exc:  # report the reason to the admin; never include credentials
        ok, error = False, f"{type(exc).__name__}: {str(exc)[:200]}"
    record_integration(session, admin, "email.tested", "email", {"ok": ok})
    await session.commit()
    return {"ok": ok, "error": error}
