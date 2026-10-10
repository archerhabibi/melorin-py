import asyncio
import logging
import smtplib
from email.message import EmailMessage

from melorin.core.config import get_settings

log = logging.getLogger("melorin.email")


async def send_email(to: str, subject: str, body: str) -> None:
    s = get_settings()
    if s.email_backend != "smtp":
        log.info("[console-email] to=%s subject=%s body=%s", to, subject, body)
        return

    def _send():
        msg = EmailMessage()
        msg["From"], msg["To"], msg["Subject"] = s.smtp_from, to, subject
        msg.set_content(body)
        with smtplib.SMTP(s.smtp_host, s.smtp_port, timeout=15) as smtp:
            smtp.starttls()
            if s.smtp_user:
                smtp.login(s.smtp_user, s.smtp_password)
            smtp.send_message(msg)

    await asyncio.to_thread(_send)
