"""Sign in with Google: Client ID settings and a connectivity test."""

from urllib.parse import urlparse

import httpx
from fastapi import APIRouter

from melorin.core import integrations
from melorin.core.config import get_settings
from melorin.core.deps import AdminUser, Session
from melorin.core.errors import AppError
from melorin.modules.admin.integrations._audit import record_integration
from melorin.modules.admin.integrations.schemas import GoogleIn

router = APIRouter(prefix="/integrations", tags=["admin-integrations"])


def _origin(url: str) -> str | None:
    """Reduce a URL to ``scheme://host[:port]`` - the only form Google accepts as an Authorized JavaScript origin."""
    p = urlparse((url or "").strip())
    return f"{p.scheme}://{p.netloc}" if p.scheme in ("http", "https") and p.netloc else None


def google_public(cfg: dict) -> dict:
    s = get_settings()
    origins = list(dict.fromkeys(o for u in [s.store_web_url, s.public_api_url, *s.cors_origins] if (o := _origin(u))))
    return {
        "enabled": bool(cfg["enabled"]),
        "client_id": cfg["client_id"],
        "admin_login": bool(cfg["admin_login"]),
        "store_login": bool(cfg["store_login"]),
        "source": cfg["source"],
        "suggested_origins": origins,
    }


@router.put("/google")
async def update_google(body: GoogleIn, admin: AdminUser, session: Session):
    client_id = body.client_id.strip()
    if client_id and not integrations.GOOGLE_CLIENT_ID_RE.match(client_id):
        raise AppError(
            "GOOGLE_CLIENT_ID_INVALID", "فرمت Client ID درست نیست؛ باید مانند 123456789-abc.apps.googleusercontent.com باشد.", 400
        )
    if body.enabled and not client_id:
        raise AppError("GOOGLE_CONFIG_INCOMPLETE", "برای فعال‌سازی، Client ID الزامی است.", 400)
    if body.enabled and not (body.admin_login or body.store_login):
        raise AppError("GOOGLE_NO_SURFACE", "حداقل یکی از ورود ادمین یا ورود مشتریان باید فعال باشد.", 400)
    new = {"enabled": body.enabled, "client_id": client_id, "admin_login": body.admin_login, "store_login": body.store_login}
    await integrations.save(session, integrations.GOOGLE_KEY, new)
    record_integration(session, admin, "google.updated", "google", new)
    await session.commit()
    return google_public({**new, "source": "panel"})


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
    record_integration(session, admin, "google.tested", "google", {"ok": ok})
    await session.commit()
    return {"ok": ok, "error": error}
