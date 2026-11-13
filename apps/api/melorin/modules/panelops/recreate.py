"""PG-04 "re-create on panel": put an account back on the panel when its panel user is gone (``missing_on_panel``).

Used only on an admin's explicit action. It builds the same request a new order would (the store's own panel admin as owner, the
server's group target, the package the customer bought) and writes nothing about the panel's *state* into Melorin afterwards
except through the normal sync, which the caller runs right after.

What is re-created is the **sold entitlement**: Melorin's own record of time and volume. If that time is already over, the account
is not brought back as a free extension: the admin must renew it through the normal renewal flow instead (money stays in the order
flow, never in an issue action). Nothing here deletes anything on the panel, and a name that already exists there is never reused:
the admin is pointed at "link to existing panel user".
"""

from __future__ import annotations

import logging

from sqlalchemy.ext.asyncio import AsyncSession

from melorin.core.db import utcnow
from melorin.core.errors import AppError
from melorin.domain.order_state import VpnStatus
from melorin.kernel.models.catalog import Product
from melorin.kernel.models.orders import Order
from melorin.kernel.models.vpn import Panel, Server, VpnAccount
from melorin.modules.vpn import sync
from melorin.modules.panelops import panel_admins
from melorin.modules.panel_integrations.adapters.base import AccountSpec, ErrorKind, PanelError
from melorin.modules.panel_integrations.adapters.registry import build_adapter

log = logging.getLogger("melorin.panelops.recreate")

RECREATABLE = (VpnStatus.ACTIVE, VpnStatus.SUSPENDED, VpnStatus.LIMITED)


async def recreate_on_panel(session: AsyncSession, account: VpnAccount) -> str:
    """Create the panel user again for ``account`` and sync it. Returns the new panel reference. The caller audits and commits."""
    if account.archived_at is not None or account.status not in RECREATABLE or not account.panel_id or not account.server_id:
        raise AppError("CANNOT_RECREATE", "این اکانت در وضعیتی نیست که بتوان آن را دوباره روی پنل ساخت.", 409)
    now = utcnow()
    expires = sync.aware(account.sold_expires_at)  # the entitlement Melorin sold: the new panel user gets exactly that
    if expires is not None and expires <= now:
        raise AppError("ENTITLEMENT_OVER", "زمان این اکانت تمام شده است؛ آن را از مسیر تمدید معمولی فعال کنید، نه با ساخت دوباره.", 409)
    panel = await session.get(Panel, account.panel_id)
    server = await session.get(Server, account.server_id)
    if panel is None or server is None:
        raise AppError("CANNOT_RECREATE", "پنل یا مقصد این اکانت پیدا نشد.", 409)
    product = await session.get(Product, account.product_id) if account.product_id else None
    order = await session.get(Order, account.order_id) if account.order_id else None
    adapter = None
    try:
        adapter = build_adapter(panel, server)  # a NEW user carries the server's group target, like a first provisioning
        if await adapter.get_account(account.username) is not None:
            raise AppError("ALREADY_ON_PANEL", "این نام روی پنل وجود دارد؛ به‌جای ساخت دوباره، «اتصال به کاربر موجود» را بزنید.", 409)
        owner = await panel_admins.owner_for(session, panel, account.store_id, adapter)
        spec = AccountSpec(
            account.username,
            expires,
            int(account.sold_traffic_bytes or 0),
            getattr(product, "max_devices", None),
            getattr(order, "number", None),
            owner=owner,
        )
        created = await adapter.create_account(spec)
    except PanelError as exc:
        if exc.kind == ErrorKind.PERMANENT:
            raise AppError("PANEL_REJECTED", f"پنل ساخت کاربر را نپذیرفت: {exc.message[:200]}", 409) from exc
        raise AppError("PANEL_UNAVAILABLE", "پنل در حال حاضر پاسخ نمی‌دهد؛ چند لحظه بعد دوباره تلاش کنید.", 503) from exc
    finally:
        if adapter is not None:
            try:
                await adapter.close()
            except Exception:
                log.warning("adapter close failed account=%s", account.id, exc_info=True)
    account.panel_ref = str(created.ref) if created.ref is not None else None
    account.sync_error_count = 0
    await sync.apply_remote(session, account, created, now=now, notify=False)
    account.delivery_snapshot = sync.delivery_snapshot(created, now=now)  # a NEW panel user has a new link: that is what is handed out now
    return str(account.panel_ref or "")
