"""E-mail sending. SMTP is optional: configured in the Admin panel (or legacy env), disabled by default.

Resolution order: Admin-panel SMTP (enabled) -> env ``MELORIN_EMAIL_BACKEND=smtp`` -> development console
-> otherwise e-mail is unavailable and callers get ``EMAIL_DISABLED``.
"""

import asyncio
import logging
import smtplib
from email.message import EmailMessage

from melorin.core import integrations
from melorin.core.config import get_settings
from melorin.core.db import session_factory
from melorin.core.errors import AppError

log = logging.getLogger("melorin.email")


async def _resolve() -> dict | None:
    async with session_factory()() as session:
        cfg = await integrations.get_email(session)
    if integrations.email_ready(cfg):
        return {
            "host": cfg["host"],
            "port": int(cfg["port"]),
            "username": cfg["username"],
            "password": integrations.email_password(cfg),
            "from_addr": cfg["from_addr"],
            "security": cfg["security"],
        }
    s = get_settings()
    if s.email_backend == "smtp" and s.smtp_host:
        return {
            "host": s.smtp_host,
            "port": s.smtp_port,
            "username": s.smtp_user,
            "password": s.smtp_password,
            "from_addr": s.smtp_from,
            "security": "starttls",
        }
    return None


async def email_available() -> bool:
    """True when a message can actually be delivered (or, in development only, printed to the log)."""
    return get_settings().is_dev or await _resolve() is not None


def _smtp_send(cfg: dict, to: str, subject: str, body: str) -> None:
    msg = EmailMessage()
    msg["From"], msg["To"], msg["Subject"] = cfg["from_addr"], to, subject
    msg.set_content(body)
    if cfg["security"] == "ssl":
        client = smtplib.SMTP_SSL(cfg["host"], cfg["port"], timeout=15)
    else:
        client = smtplib.SMTP(cfg["host"], cfg["port"], timeout=15)
    with client as smtp:
        if cfg["security"] == "starttls":
            smtp.starttls()
        if cfg["username"]:
            smtp.login(cfg["username"], cfg["password"])
        smtp.send_message(msg)


async def send_email(to: str, subject: str, body: str) -> None:
    cfg = await _resolve()
    if cfg is None:
        if get_settings().is_dev:
            log.info("[console-email] to=%s subject=%s body=%s", to, subject, body)
            return
        raise AppError("EMAIL_DISABLED", "ارسال ایمیل در این سامانه فعال نیست.", 503)
    await asyncio.to_thread(_smtp_send, cfg, to, subject, body)


async def send_with_config(cfg: dict, to: str, subject: str, body: str) -> None:
    """Used by the Admin 'send test e-mail' action (does not depend on the enabled flag)."""
    await asyncio.to_thread(_smtp_send, cfg, to, subject, body)
