"""Admin panel IP allow-list."""

import ipaddress

from fastapi import APIRouter

from melorin.core import integrations
from melorin.core.context import client_ip
from melorin.core.deps import AdminUser, Session, ip_allowed
from melorin.core.errors import AppError
from melorin.modules.admin.integrations._audit import record_integration
from melorin.modules.admin.integrations.schemas import AdminAccessIn

router = APIRouter(prefix="/integrations", tags=["admin-integrations"])


def _normalise_networks(raw_values: list[str]) -> list[str]:
    ips: list[str] = []
    for raw in raw_values:
        value = raw.strip()
        if not value:
            continue
        try:
            ips.append(str(ipaddress.ip_network(value, strict=False)))
        except ValueError:
            raise AppError("ADMIN_IP_INVALID", f"آدرس IP یا CIDR نامعتبر است: {value}", 400) from None
    return list(dict.fromkeys(ips))


@router.put("/admin-access")
async def update_admin_access(body: AdminAccessIn, admin: AdminUser, session: Session):
    ips = _normalise_networks(body.ips)
    if body.enabled:
        if not ips:
            raise AppError("ADMIN_IP_EMPTY", "برای فعال‌سازی، حداقل یک IP یا CIDR لازم است.", 400)
        if not ip_allowed(client_ip.get(), ips):
            raise AppError(
                "ADMIN_IP_LOCKOUT", "IP فعلی شما در فهرست نیست؛ با این تنظیم از پنل بیرون می‌افتید. IP خودتان را هم اضافه کنید.", 400
            )
    new = {"enabled": body.enabled, "ips": ips}
    await integrations.save(session, integrations.ADMIN_ACCESS_KEY, new)
    record_integration(session, admin, "admin_access.updated", "admin_access", new)
    await session.commit()
    return {**new, "your_ip": client_ip.get()}
