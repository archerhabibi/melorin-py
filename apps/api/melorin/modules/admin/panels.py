"""Admin API - panels routes (split from the former 1,900-line router; paths unchanged)."""

import logging
import uuid
from fastapi import APIRouter
from sqlalchemy import func, select
from melorin.core import audit
from melorin.core.config import get_settings
from melorin.core.crypto import encrypt
from melorin.core.deps import AdminUser, Session
from melorin.core.errors import AppError, NotFound
from melorin.kernel.models.catalog import Product
from melorin.kernel.models.orders import Order
from melorin.kernel.models.vpn import Panel, Server, VpnAccount
from melorin.kernel.models.bundles import Bundle, BundleMember
from melorin.modules.eventcenter import rules as event_center_rules
from melorin.modules.admin.schemas import (
    CreatePanel,
    CreateServer,
    PanelOut,
    PanelState,
    ServerOut,
    UpdateServer,
)
from melorin.modules.admin._common import (
    _commit_or_conflict,
    _count,
)

router = APIRouter(prefix="/admin", tags=["admin"])
log = logging.getLogger("melorin.admin")


# ----- Panels / servers -----
def _panel_out(p: Panel) -> PanelOut:
    out = PanelOut.model_validate(p, from_attributes=True)
    out.has_credentials = bool(p.credentials_enc)
    return out


@router.post("/panels", response_model=PanelOut, status_code=201)
async def create_panel(body: CreatePanel, admin: AdminUser, session: Session):
    from urllib.parse import urlparse

    parsed = urlparse(body.base_url)
    if get_settings().env in {"staging", "production"} and parsed.scheme != "https":
        raise AppError("PANEL_HTTPS_REQUIRED", "آدرس پنل در محیط عملیاتی باید HTTPS باشد.", 400)
    if get_settings().env in {"staging", "production"} and body.config.get("verify_tls") is False:
        raise AppError("PANEL_TLS_VERIFY_REQUIRED", "TLS verification در محیط عملیاتی قابل خاموش‌کردن نیست.", 400)
    if body.kind == "pasarguard" and not body.credentials:
        raise AppError("PANEL_CREDENTIALS_REQUIRED", "اعتبارنامه پنل پاسارگارد لازم است.", 400)
    p = Panel(
        name=body.name,
        kind=body.kind,
        base_url=body.base_url,
        credentials_enc=encrypt(__import__("json").dumps(body.credentials)),
        config=body.config,
    )
    session.add(p)
    await session.flush()
    audit.record(
        session,
        "panel.created",
        actor_id=admin.id,
        actor_type="admin",
        entity_type="panel",
        entity_id=p.id,
        data={"kind": p.kind, "url": p.base_url},
    )
    await session.commit()
    await session.refresh(p)
    return _panel_out(p)


@router.get("/panels", response_model=list[PanelOut])
async def panels(_: AdminUser, session: Session):
    rows = (await session.scalars(select(Panel).order_by(Panel.created_at))).all()
    return [_panel_out(p) for p in rows]


@router.patch("/panels/{panel_id}")
async def update_panel(panel_id: uuid.UUID, body: CreatePanel, admin: AdminUser, session: Session):
    p = await session.get(Panel, panel_id)
    if not p:
        raise NotFound("پنل")
    from urllib.parse import urlparse

    parsed = urlparse(body.base_url)
    if get_settings().env in {"staging", "production"} and (parsed.scheme != "https" or body.config.get("verify_tls") is False):
        raise AppError("PANEL_TLS_VERIFY_REQUIRED", "پنل production باید HTTPS و TLS verification فعال داشته باشد.", 400)
    changed = [
        k
        for k, new in (("name", body.name), ("kind", body.kind), ("base_url", body.base_url), ("config", body.config))
        if getattr(p, k) != new
    ]
    p.name, p.base_url, p.kind, p.config = body.name, body.base_url, body.kind, body.config
    if body.credentials:
        p.credentials_enc = encrypt(__import__("json").dumps(body.credentials))
        changed.append("credentials")
    if set(changed) - {"name"}:
        # Connection details changed: the previous health result no longer describes this panel.
        p.health_status, p.last_health_at, p.last_health_error = "unknown", None, None
    audit.record(
        session,
        "panel.updated",
        actor_id=admin.id,
        actor_type="admin",
        entity_type="panel",
        entity_id=p.id,
        data={"kind": p.kind, "url": p.base_url, "changed": changed},
    )
    await session.commit()
    return {"ok": True}


@router.post("/panels/{panel_id}/state")
async def set_panel_state(panel_id: uuid.UUID, body: PanelState, admin: AdminUser, session: Session):
    p = await session.get(Panel, panel_id)
    if not p:
        raise NotFound("پنل")
    if p.is_enabled != body.is_enabled:
        p.is_enabled = body.is_enabled
        audit.record(
            session,
            "panel.enabled" if body.is_enabled else "panel.disabled",
            actor_id=admin.id,
            actor_type="admin",
            entity_type="panel",
            entity_id=p.id,
            data={"kind": p.kind, "url": p.base_url},
        )
        await session.commit()
    return {"ok": True, "is_enabled": p.is_enabled}


async def _clean_product_codes(session, raw: list[str] | None) -> list[str] | None:
    """Normalise a server's product-code allow-list; None means "all products". Unknown codes are rejected."""
    codes = sorted({c.strip() for c in (raw or []) if c and c.strip()})
    if codes:
        known = set((await session.scalars(select(Product.code).where(Product.code.in_(codes)))).all())
        unknown = [c for c in codes if c not in known]
        if unknown:
            raise AppError("UNKNOWN_PRODUCT_CODES", "کد محصول نامعتبر است: " + "، ".join(unknown), 422)
    return codes or None


def _server_out(s: Server, panel_name: str, active: int = 0, total: int = 0) -> ServerOut:
    return ServerOut(
        id=s.id,
        name=s.name,
        panel_id=s.panel_id,
        panel_name=panel_name,
        location=s.location,
        capacity=s.capacity,
        product_codes=list(s.product_codes) if s.product_codes else None,
        allow_test=bool(s.allow_test),
        is_enabled=bool(s.is_enabled),
        active_accounts=active,
        total_accounts=total,
        created_at=s.created_at,
        updated_at=s.updated_at,
    )


async def _server_counts(session, server_ids: list[uuid.UUID]) -> dict[uuid.UUID, tuple[int, int]]:
    """server_id -> (active accounts, all accounts) in one grouped query."""
    from melorin.domain.order_state import VpnStatus

    if not server_ids:
        return {}
    rows = await session.execute(
        select(VpnAccount.server_id, func.count(), func.count().filter(VpnAccount.status == VpnStatus.ACTIVE))
        .where(VpnAccount.server_id.in_(server_ids))
        .group_by(VpnAccount.server_id)
    )
    return {sid: (int(active), int(total)) for sid, total, active in rows.all()}


@router.get("/servers", response_model=list[ServerOut])
async def servers(_: AdminUser, session: Session):
    rows = (await session.execute(select(Server, Panel.name).join(Panel, Panel.id == Server.panel_id).order_by(Server.created_at))).all()
    counts = await _server_counts(session, [s.id for s, _ in rows])
    return [_server_out(s, pname, *counts.get(s.id, (0, 0))) for s, pname in rows]


@router.post("/servers", response_model=dict, status_code=201)
async def create_server(body: CreateServer, admin: AdminUser, session: Session):
    if not await session.get(Panel, body.panel_id):
        raise NotFound("پنل")
    body = body.model_copy(update={"product_codes": await _clean_product_codes(session, body.product_codes)})
    s = Server(**body.model_dump())
    session.add(s)
    await session.flush()
    audit.record(session, "server.created", actor_id=admin.id, actor_type="admin", entity_type="server", entity_id=s.id)
    await session.commit()
    return {"id": s.id}


@router.patch("/servers/{server_id}", response_model=ServerOut)
async def update_server(server_id: uuid.UUID, body: UpdateServer, admin: AdminUser, session: Session):
    s = await session.get(Server, server_id)
    if not s:
        raise NotFound("سرور")
    patch = body.model_dump(exclude_unset=True)
    for required in ("name", "panel_id", "capacity", "allow_test"):
        if required in patch and patch[required] is None:
            raise AppError("VALIDATION_ERROR", "این فیلد نمی‌تواند خالی باشد.", 422, {"field": required})
    if "product_codes" in patch:
        patch["product_codes"] = await _clean_product_codes(session, patch["product_codes"])
    if "location" in patch and patch["location"] is not None:
        patch["location"] = patch["location"].strip() or None
    if "name" in patch:
        patch["name"] = patch["name"].strip()
        if not patch["name"]:
            raise AppError("VALIDATION_ERROR", "نام سرور نمی‌تواند خالی باشد.", 422, {"field": "name"})
    if "panel_id" in patch and patch["panel_id"] != s.panel_id:
        if not await session.get(Panel, patch["panel_id"]):
            raise NotFound("پنل")
        # Accounts keep the panel they were created on; moving the server would orphan them.
        if await session.scalar(select(func.count()).select_from(VpnAccount).where(VpnAccount.server_id == s.id)):
            raise AppError(
                "SERVER_HAS_ACCOUNTS", "این سرور اکانت دارد و پنل آن قابل تغییر نیست. سرور جدید بسازید و این را غیرفعال کنید.", 409
            )
    changed = [k for k, v in patch.items() if getattr(s, k) != v]
    for k in changed:
        setattr(s, k, patch[k])
    if changed:
        audit.record(
            session,
            "server.updated",
            actor_id=admin.id,
            actor_type="admin",
            entity_type="server",
            entity_id=s.id,
            data={"changed": changed},
        )
    await session.commit()
    await session.refresh(s)
    pname = await session.scalar(select(Panel.name).where(Panel.id == s.panel_id))
    return _server_out(s, pname or "", *(await _server_counts(session, [s.id])).get(s.id, (0, 0)))


@router.post("/servers/{server_id}/state")
async def set_server_state(server_id: uuid.UUID, body: PanelState, admin: AdminUser, session: Session):
    s = await session.get(Server, server_id)
    if not s:
        raise NotFound("سرور")
    if s.is_enabled != body.is_enabled:
        s.is_enabled = body.is_enabled
        audit.record(
            session,
            "server.enabled" if body.is_enabled else "server.disabled",
            actor_id=admin.id,
            actor_type="admin",
            entity_type="server",
            entity_id=s.id,
        )
        await session.commit()
    return {"ok": True, "is_enabled": s.is_enabled}


@router.delete("/panels/{panel_id}")
async def delete_panel(panel_id: uuid.UUID, admin: AdminUser, session: Session):
    p = await session.get(Panel, panel_id)
    if not p:
        raise NotFound("پنل")
    servers = (await session.scalars(select(Server).where(Server.panel_id == p.id))).all()
    server_ids = [s.id for s in servers]
    accounts = await _count(
        session,
        VpnAccount,
        (VpnAccount.panel_id == p.id) | (VpnAccount.server_id.in_(server_ids)) if server_ids else VpnAccount.panel_id == p.id,
    )
    orders = await _count(session, Order, Order.selected_panel_id == p.id)
    if accounts or orders:
        raise AppError(
            "PANEL_HAS_HISTORY",
            f"روی این پنل {accounts} اکانت ساخته شده و {orders} سفارش به آن وصل است؛ حذفش اکانت‌ها را بی‌پنل می‌کند. به‌جای حذف، پنل را غیرفعال کنید.",
            409,
            {"accounts": accounts, "orders": orders},
        )
    members = (await session.scalars(select(BundleMember).where(BundleMember.panel_id == p.id))).all()
    for m in members:
        g = await session.get(Bundle, m.bundle_id)
        if g and g.selection_mode == "manual" and await _count(session, BundleMember, BundleMember.bundle_id == g.id) <= 1:
            raise AppError(
                "PANEL_LAST_IN_MANUAL_GROUP",
                f"این پنل تنها بسته فروش دستی «{g.name}» است. ابتدا پنل دیگری به آن گروه اضافه کنید یا گروه را حذف کنید.",
                409,
                {"group": g.name},
            )
    for m in members:
        await session.delete(m)
    for s in servers:
        await session.delete(s)
    audit.record(
        session,
        "panel.deleted",
        actor_id=admin.id,
        actor_type="admin",
        entity_type="panel",
        entity_id=p.id,
        data={"kind": p.kind, "url": p.base_url, "name": p.name, "servers_deleted": len(servers), "groups_left": len(members)},
    )
    await session.delete(p)
    await _commit_or_conflict(session, "این پنل")
    return {"ok": True, "servers_deleted": len(servers), "groups_left": len(members)}


@router.delete("/servers/{server_id}")
async def delete_server(server_id: uuid.UUID, admin: AdminUser, session: Session):
    s = await session.get(Server, server_id)
    if not s:
        raise NotFound("سرور")
    accounts = await _count(session, VpnAccount, VpnAccount.server_id == s.id)
    if accounts:
        raise AppError(
            "SERVER_HAS_ACCOUNTS",
            f"روی این سرور {accounts} اکانت ساخته شده؛ حذفش آن‌ها را بی‌سرور می‌کند. به‌جای حذف، سرور را غیرفعال کنید.",
            409,
            {"accounts": accounts},
        )
    audit.record(
        session,
        "server.deleted",
        actor_id=admin.id,
        actor_type="admin",
        entity_type="server",
        entity_id=s.id,
        data={"name": s.name, "panel_id": str(s.panel_id)},
    )
    await session.delete(s)
    await _commit_or_conflict(session, "این سرور")
    return {"ok": True}


@router.post("/panels/{panel_id}/health")
async def panel_health(panel_id: uuid.UUID, _: AdminUser, session: Session):
    from melorin.modules.vpn.adapters.registry import build_adapter
    from melorin.core.db import utcnow

    p = await session.get(Panel, panel_id)
    if not p:
        raise NotFound("پنل")
    adapter = None
    error: str | None = None
    try:
        adapter = build_adapter(p)
        ok = await adapter.health_check()
        if not ok:
            error = "پنل پاسخ سالم نداد."
    except Exception as exc:
        ok = False
        error = (getattr(exc, "message", None) or str(exc) or exc.__class__.__name__)[:300]
    finally:
        if adapter is not None:
            try:
                await adapter.close()
            except Exception:
                log.warning("panel adapter close failed panel=%s", p.id, exc_info=True)
    previous = p.health_status
    p.health_status, p.last_health_at, p.last_health_error = "healthy" if ok else "unhealthy", utcnow(), (None if ok else error)
    await event_center_rules.notify_panel_health(session, p, previous)
    await session.commit()
    return {"healthy": ok, "error": None if ok else error}
