import csv
import io
import uuid

from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response, StreamingResponse
from sqlalchemy import delete, func, select

from melorin.core import audit, flags, settings_store
from melorin.core.config import get_settings
from melorin.core.crypto import encrypt
from melorin.core.deps import AdminUser, Session
from melorin.core.errors import AppError, NotFound
from melorin.core.pagination import Page, PageParams
from melorin.core.security import new_opaque_token, token_hash
from melorin.modules.admin.schemas import *  # noqa: F403
from melorin.modules.catalog.schemas import AdminCouponIn, CouponPatch
from melorin.modules.catalog.models import Coupon, CouponRedemption, Product, StoreProduct
from melorin.modules.identity.models import IdentityLinkReview, User
from melorin.modules.orders import service as order_service
from melorin.modules.orders.models import Order
from melorin.modules.payments import service as payment_service
from melorin.modules.payments.models import Payment
from melorin.modules.stores.models import BotStoreBinding, ResellerApplication, ResellerProfile, Store, StoreMembership
from melorin.modules.admin import bot_bindings
from melorin.modules.admin.integrations import router as integrations_router
from melorin.modules.system.models import AuditEvent, BackupRun, FeatureFlag, SystemSetting
from melorin.modules.webhooks import service as webhook_service
from melorin.modules.tickets.models import Ticket
from melorin.modules.vpn.models import Panel, Server, VpnAccount
from melorin.modules.vpn.panel_groups import PanelGroup, PanelGroupMember, StorePanelGroup

router = APIRouter(prefix="/admin", tags=["admin"])
router.include_router(integrations_router)


@router.get("/bot-store-bindings")
async def list_bot_store_bindings(_: AdminUser, session: Session):
    return [bot_bindings.out(row) for row in await bot_bindings.list_bindings(session)]


@router.post("/bot-store-bindings", status_code=201)
async def create_bot_store_binding(body: CreateBotStoreBinding, admin: AdminUser, session: Session):
    row = await bot_bindings.create_binding(session, body, admin)
    return bot_bindings.out(row)


@router.get("/health")
async def health(_: AdminUser, session: Session):
    from sqlalchemy import text
    from melorin.core.redis import get_redis

    await session.execute(text("SELECT 1"))
    redis = get_redis()
    worker = False
    if redis is not None:
        try:
            await redis.ping()
            worker = bool(await redis.get("melorin:worker:last_tick"))
        except Exception:
            pass
    return {"api": "ok", "database": "ok", "redis": "ok" if redis else "unavailable", "worker": "ok" if worker else "unavailable"}


@router.get("/dashboard")
async def dashboard(_: AdminUser, session: Session):
    from melorin.modules.orders.service import count_by_status

    return {"orders": await count_by_status(session), "active_users": await session.scalar(select(func.count()).select_from(User).where(User.is_active.is_(True))), "open_tickets": await session.scalar(select(func.count()).select_from(Ticket).where(Ticket.status == "open")) or 0}


@router.get("/reports/summary")
async def report_summary(_: AdminUser, session: Session):
    """Only successful payments count as sales, grouped by currency."""
    rows = (await session.execute(
        select(Payment.currency, func.count(Payment.id), func.sum(Payment.amount))
        .where(Payment.status == "succeeded")
        .group_by(Payment.currency)
    )).all()
    return {
        "payments": [{"currency": c, "count": n, "amount": total or 0} for c, n, total in rows],
        "orders": [{"status": k, "count": v} for k, v in (await order_service.count_by_status(session)).items()],
        "open_tickets": await session.scalar(select(func.count()).select_from(Ticket).where(Ticket.status == "open")) or 0,
        "currency_safe": True,
    }


@router.get("/reports/timeseries")
async def report_timeseries(_: AdminUser, session: Session, days: int = Query(default=30, ge=7, le=90)):
    """Zero-filled daily orders + per-currency sales for the dashboard chart."""
    from melorin.modules.admin.timeseries import build_timeseries

    return await build_timeseries(session, days)


@router.get("/reports/orders.csv")
async def export_orders(_: AdminUser, session: Session, status: str | None = Query(default=None)):
    q = select(Order).order_by(Order.created_at.desc()).limit(5000)
    if status:
        q = q.where(Order.status == status)
    rows = (await session.scalars(q)).all()
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["id", "number", "store_id", "status", "total", "currency", "created_at"])
    for o in rows:
        writer.writerow([o.id, o.number, o.store_id, o.status, o.total, o.currency, o.created_at.isoformat()])
    return StreamingResponse(iter([buf.getvalue().encode("utf-8-sig")]), media_type="text/csv", headers={"Content-Disposition": "attachment; filename=melorin-orders.csv"})


@router.get("/operations/backups", response_model=list[dict])
async def backup_status(_: AdminUser, session: Session):
    """Read-only backup status for the Admin Web operations panel."""
    rows = (
        await session.scalars(
            select(BackupRun)
            .order_by(BackupRun.created_at.desc())
            .limit(100)
        )
    ).all()
    return [
        {
            "id": row.id,
            "status": row.status,
            "location": row.location,
            "size": row.size,
            "details": row.details,
            "created_at": row.created_at,
        }
        for row in rows
    ]


# ----- Catalog -----
async def _check_default_group(session, group_id) -> None:
    """A product's default group is applied by the core to every channel, so it must be usable without any choice by the buyer."""
    group = await session.get(PanelGroup, group_id)
    if not group: raise NotFound("گروه پنل")
    if not group.is_enabled: raise AppError("DEFAULT_GROUP_DISABLED", "گروه پیش‌فرض محصول باید فعال باشد.", 422)
    if group.selection_mode != "automatic":
        raise AppError("DEFAULT_GROUP_MANUAL", "گروه پیش‌فرض محصول باید انتخاب خودکار باشد؛ ربات و سایت پنل را انتخاب نمی‌کنند.", 422)


@router.post("/products", response_model=ProductOut, status_code=201)
async def create_product(body: CreateProduct, admin: AdminUser, session: Session):
    if await session.scalar(select(Product.id).where(Product.code == body.code)):
        raise AppError("PRODUCT_CODE_EXISTS", "کد محصول تکراری است.", 409)
    if body.default_panel_group_id is not None: await _check_default_group(session, body.default_panel_group_id)
    p = Product(**body.model_dump())
    session.add(p); await session.flush()
    main = await session.scalar(select(Store).where(Store.kind == "main", Store.status == "active"))
    if main:
        session.add(StoreProduct(
            product_id=p.id,
            store_id=main.id,
            is_enabled=True,
            is_listed=True,
            customer_price=None,
        ))
    audit.record(session, "product.created", actor_id=admin.id, actor_type="admin", entity_type="product", entity_id=p.id, data=body.model_dump(mode="json"))
    await session.commit()
    return p


@router.get("/products", response_model=list[ProductOut])
async def list_products(_: AdminUser, session: Session):
    return (await session.scalars(select(Product).order_by(Product.sort, Product.created_at.desc()))).all()


@router.patch("/products/{product_id}", response_model=ProductOut)
async def update_product(product_id: uuid.UUID, body: ProductPatch, admin: AdminUser, session: Session):
    p = await session.get(Product, product_id)
    if not p: raise NotFound("محصول")
    before = {"main_price": p.main_price, "reseller_price": p.reseller_price, "duration_days": p.duration_days, "traffic_gb": p.traffic_gb, "is_active": p.is_active, "default_panel_group_id": str(p.default_panel_group_id) if p.default_panel_group_id else None}
    # Explicit null clears these optional fields (e.g. "unlimited devices"); other fields ignore null.
    changes = {k: v for k, v in body.model_dump(exclude_unset=True).items() if v is not None or k in {"max_devices", "description", "category", "default_panel_group_id"}}
    if changes.get("default_panel_group_id") is not None: await _check_default_group(session, changes["default_panel_group_id"])
    if "code" in changes and changes["code"] != p.code and await session.scalar(select(Product.id).where(Product.code == changes["code"])):
        raise AppError("PRODUCT_CODE_EXISTS", "کد محصول تکراری است.", 409)
    for k, v in changes.items(): setattr(p, k, v)
    audit.record(session, "product.updated", actor_id=admin.id, actor_type="admin", entity_type="product", entity_id=p.id, data={"before": before, "after": {k: (str(v) if isinstance(v, uuid.UUID) else v) for k, v in changes.items()}})
    await session.commit(); return p


@router.post("/products/{product_id}/availability", response_model=dict)
async def set_availability(product_id: uuid.UUID, body: Availability, admin: AdminUser, session: Session):
    p = await session.get(Product, product_id); st = await session.get(Store, body.store_id)
    if not p or not st: raise NotFound("محصول یا فروشگاه")
    row = await session.scalar(select(StoreProduct).where(StoreProduct.product_id == p.id, StoreProduct.store_id == st.id))
    if not row: row = StoreProduct(product_id=p.id, store_id=st.id); session.add(row)
    row.is_enabled, row.customer_price, row.is_listed = body.enabled, body.customer_price, body.listed
    audit.record(session, "catalog.availability_updated", actor_id=admin.id, actor_type="admin", entity_type="product", entity_id=p.id, store_id=st.id)
    await session.commit(); return {"ok": True}


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
    p = Panel(name=body.name, kind=body.kind, base_url=body.base_url, credentials_enc=encrypt(__import__("json").dumps(body.credentials)), config=body.config)
    session.add(p); await session.flush(); audit.record(session, "panel.created", actor_id=admin.id, actor_type="admin", entity_type="panel", entity_id=p.id, data={"kind": p.kind, "url": p.base_url}); await session.commit(); await session.refresh(p); return _panel_out(p)


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
    changed = [k for k, new in (("name", body.name), ("kind", body.kind), ("base_url", body.base_url), ("config", body.config)) if getattr(p, k) != new]
    p.name, p.base_url, p.kind, p.config = body.name, body.base_url, body.kind, body.config
    if body.credentials:
        p.credentials_enc = encrypt(__import__("json").dumps(body.credentials))
        changed.append("credentials")
    if set(changed) - {"name"}:
        # Connection details changed: the previous health result no longer describes this panel.
        p.health_status, p.last_health_at, p.last_health_error = "unknown", None, None
    audit.record(session, "panel.updated", actor_id=admin.id, actor_type="admin", entity_type="panel", entity_id=p.id, data={"kind": p.kind, "url": p.base_url, "changed": changed})
    await session.commit()
    return {"ok": True}


@router.post("/panels/{panel_id}/state")
async def set_panel_state(panel_id: uuid.UUID, body: PanelState, admin: AdminUser, session: Session):
    p = await session.get(Panel, panel_id)
    if not p:
        raise NotFound("پنل")
    if p.is_enabled != body.is_enabled:
        p.is_enabled = body.is_enabled
        audit.record(session, "panel.enabled" if body.is_enabled else "panel.disabled", actor_id=admin.id, actor_type="admin", entity_type="panel", entity_id=p.id, data={"kind": p.kind, "url": p.base_url})
        await session.commit()
    return {"ok": True, "is_enabled": p.is_enabled}


@router.post("/servers", response_model=dict, status_code=201)
async def create_server(body: CreateServer, admin: AdminUser, session: Session):
    if not await session.get(Panel, body.panel_id): raise NotFound("پنل")
    codes = sorted({c.strip() for c in (body.product_codes or []) if c and c.strip()})
    if codes:
        known = set((await session.scalars(select(Product.code).where(Product.code.in_(codes)))).all())
        unknown = [c for c in codes if c not in known]
        if unknown: raise AppError("UNKNOWN_PRODUCT_CODES", "کد محصول نامعتبر است: " + "، ".join(unknown), 422)
    body = body.model_copy(update={"product_codes": codes or None})
    s = Server(**body.model_dump()); session.add(s); await session.flush(); audit.record(session, "server.created", actor_id=admin.id, actor_type="admin", entity_type="server", entity_id=s.id); await session.commit(); return {"id": s.id}


def _panel_group_out(b, panels):
    return {"id": b.id, "name": b.name, "selection_mode": b.selection_mode, "naming_mode": b.naming_mode,
            "is_enabled": b.is_enabled, "reseller_enabled": b.reseller_enabled, "sales_limit": b.sales_limit,
            "sold_count": b.sold_count, "panels": [{"id": p.id, "panel_id": p.panel_id, "is_enabled": p.is_enabled,
            "sales_limit": p.sales_limit, "sold_count": p.sold_count, "sort": p.sort} for p in panels]}


@router.get("/panel-groups")
async def list_panel_groups(_: AdminUser, session: Session):
    panel_groups = (await session.scalars(select(PanelGroup).order_by(PanelGroup.created_at.desc()))).all()
    result = []
    for b in panel_groups:
        rows = (await session.scalars(select(PanelGroupMember).where(PanelGroupMember.panel_group_id == b.id).order_by(PanelGroupMember.sort))).all()
        result.append(_panel_group_out(b, rows))
    return result


@router.post("/panel-groups", status_code=201)
async def create_panel_group(body: CreatePanelGroup, admin: AdminUser, session: Session):
    if body.selection_mode == "manual" and not body.panel_ids:
        raise AppError("PANEL_GROUP_PANELS_REQUIRED", "گروه دستی باید حداقل یک پنل داشته باشد.", 400)
    valid = (await session.scalars(select(Panel.id).where(Panel.id.in_(body.panel_ids)))).all()
    if len(valid) != len(set(body.panel_ids)): raise NotFound("پنل گروه")
    b = PanelGroup(name=body.name, selection_mode=body.selection_mode, naming_mode=body.naming_mode,
                    is_enabled=body.is_enabled, reseller_enabled=body.reseller_enabled, sales_limit=body.sales_limit)
    session.add(b); await session.flush()
    for i, pid in enumerate(body.panel_ids): session.add(PanelGroupMember(panel_group_id=b.id, panel_id=pid, sort=i))
    audit.record(session, "panel_group.created", actor_id=admin.id, actor_type="admin", entity_type="panel_group", entity_id=b.id)
    await session.commit()
    rows = (await session.scalars(select(PanelGroupMember).where(PanelGroupMember.panel_group_id == b.id))).all()
    return _panel_group_out(b, rows)


@router.patch("/panel-groups/{panel_group_id}")
async def update_panel_group(panel_group_id: uuid.UUID, body: UpdatePanelGroup, admin: AdminUser, session: Session):
    b = await session.get(PanelGroup, panel_group_id)
    if not b: raise NotFound("گروه پنل")
    if body.selection_mode == "manual" and b.selection_mode != "manual" and await session.scalar(select(func.count()).select_from(Product).where(Product.default_panel_group_id == b.id)):
        raise AppError("DEFAULT_GROUP_IN_USE", "این گروه پیش‌فرض یک یا چند محصول است و نمی‌تواند دستی شود؛ ابتدا گروه پیش‌فرض آن محصولات را تغییر دهید.", 409)
    # Explicit null is meaningful only for sales_limit (= unlimited); other fields ignore null.
    for k, v in body.model_dump(exclude_unset=True, exclude={"panel_ids"}).items():
        if v is not None or k == "sales_limit": setattr(b, k, v)
    if body.panel_ids is not None:
        valid = (await session.scalars(select(Panel.id).where(Panel.id.in_(body.panel_ids)))).all()
        if len(valid) != len(set(body.panel_ids)): raise NotFound("پنل گروه")
        if b.selection_mode == "manual" and not body.panel_ids:
            raise AppError("PANEL_GROUP_PANELS_REQUIRED", "گروه دستی باید حداقل یک پنل داشته باشد.", 400)
        # Sync instead of delete+insert so per-panel sold_count / limits survive edits.
        existing = {m.panel_id: m for m in (await session.scalars(select(PanelGroupMember).where(PanelGroupMember.panel_group_id == b.id))).all()}
        wanted = list(dict.fromkeys(body.panel_ids))
        for pid, m in existing.items():
            if pid not in wanted: await session.delete(m)
        for i, pid in enumerate(wanted):
            if pid in existing: existing[pid].sort = i
            else: session.add(PanelGroupMember(panel_group_id=b.id, panel_id=pid, sort=i))
    audit.record(session, "panel_group.updated", actor_id=admin.id, actor_type="admin", entity_type="panel_group", entity_id=b.id)
    await session.commit()
    rows = (await session.scalars(select(PanelGroupMember).where(PanelGroupMember.panel_group_id == b.id).order_by(PanelGroupMember.sort))).all()
    return _panel_group_out(b, rows)


@router.put("/panel-groups/{panel_group_id}/stores/{store_id}")
async def set_panel_group_store(panel_group_id: uuid.UUID, store_id: uuid.UUID, body: dict, admin: AdminUser, session: Session):
    if not await session.get(PanelGroup, panel_group_id) or not await session.get(Store, store_id): raise NotFound("گروه یا فروشگاه")
    row = await session.scalar(select(StorePanelGroup).where(StorePanelGroup.panel_group_id == panel_group_id, StorePanelGroup.store_id == store_id))
    if not row:
        row = StorePanelGroup(panel_group_id=panel_group_id, store_id=store_id); session.add(row)
    row.is_enabled = bool(body.get("is_enabled", True))
    await session.commit()
    return {"ok": True, "is_enabled": row.is_enabled}


@router.post("/panels/{panel_id}/health")
async def panel_health(panel_id: uuid.UUID, _: AdminUser, session: Session):
    from melorin.modules.vpn.adapters.registry import build_adapter
    from melorin.core.db import utcnow
    p = await session.get(Panel, panel_id)
    if not p: raise NotFound("پنل")
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
            try: await adapter.close()
            except Exception: pass
    p.health_status, p.last_health_at, p.last_health_error = "healthy" if ok else "unhealthy", utcnow(), (None if ok else error)
    await session.commit(); return {"healthy": ok, "error": None if ok else error}


# ----- Payments, orders, manual recovery -----
@router.get("/payments", response_model=list[dict])
async def payments(_: AdminUser, session: Session, status: str | None = Query(default=None)):
    q = select(Payment).order_by(Payment.created_at.desc()).limit(200)
    if status: q = q.where(Payment.status == status)
    return [{"id": p.id, "user_id": p.user_id, "store_id": p.store_id, "amount": p.amount, "currency": p.currency, "provider": p.provider, "status": p.status, "has_receipt": bool(p.receipt_file_id), "created_at": p.created_at} for p in (await session.scalars(q)).all()]


@router.get("/payments/{payment_id}/receipt")
async def payment_receipt(payment_id: uuid.UUID, admin: AdminUser, session: Session):
    """Admin-only receipt download. Files stay private; every view is audited."""
    from melorin.core.storage import get_storage
    from melorin.modules.system.models import FileObject
    p = await session.get(Payment, payment_id)
    if not p or not p.receipt_file_id: raise NotFound("رسید")
    fo = await session.get(FileObject, p.receipt_file_id)
    if not fo: raise NotFound("رسید")
    data = await get_storage().get(fo.storage_key)
    audit.record(session, "payment.receipt_viewed", actor_id=admin.id, actor_type="admin", entity_type="payment", entity_id=p.id); await session.commit()
    return Response(content=data, media_type=fo.content_type, headers={"Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff", "Content-Disposition": "inline"})


@router.post("/payments/{payment_id}/review")
async def review_payment(payment_id: uuid.UUID, body: ReviewPayment, admin: AdminUser, session: Session):
    p = await session.get(Payment, payment_id)
    if not p: raise NotFound("پرداخت")
    if body.approve: await payment_service.mark_succeeded(session, p.id, actor_id=admin.id, actor_type="admin", note=body.reason)
    else: await payment_service.mark_failed(session, p.id, actor_id=admin.id, reason=body.reason)
    audit.record(session, "payment.reviewed", actor_id=admin.id, actor_type="admin", entity_type="payment", entity_id=p.id, data={"approve": body.approve, "reason": body.reason})
    await session.commit(); return {"ok": True, "status": p.status}


@router.post("/payments/{payment_id}/refund")
async def refund_payment(payment_id: uuid.UUID, body: OrderAction, admin: AdminUser, session: Session):
    p = await payment_service.refund_payment(session, payment_id, actor_id=admin.id, reason=body.reason)
    return {"ok": True, "status": p.status, "payment_id": p.id}


@router.get("/orders", response_model=list[dict])
async def orders(_: AdminUser, session: Session, status: str | None = Query(default=None), store_id: uuid.UUID | None = Query(default=None)):
    q = select(Order).order_by(Order.created_at.desc()).limit(200)
    if status: q = q.where(Order.status == status)
    if store_id: q = q.where(Order.store_id == store_id)
    return [{"id": o.id, "number": o.number, "user_id": o.user_id, "store_id": o.store_id, "status": o.status, "total": o.total, "currency": o.currency, "needs_review": o.needs_review, "created_at": o.created_at} for o in (await session.scalars(q)).all()]


@router.get("/users", response_model=list[dict])
async def users(_: AdminUser, session: Session):
    rows = (await session.scalars(select(User).order_by(User.created_at.desc()).limit(500))).all()
    return [{"id": u.id, "email": u.email, "display_name": u.display_name, "is_active": u.is_active, "is_super_admin": u.is_super_admin, "created_at": u.created_at} for u in rows]


@router.get("/stores", response_model=list[dict])
async def stores(_: AdminUser, session: Session):
    rows = (await session.scalars(select(Store).order_by(Store.created_at.desc()).limit(500))).all()
    return [{"id": s.id, "name": s.name, "slug": s.slug, "kind": s.kind, "status": s.status, "currency": s.currency, "owner_user_id": s.owner_user_id} for s in rows]


@router.get("/tickets", response_model=list[dict])
async def tickets(_: AdminUser, session: Session):
    from melorin.modules.tickets.models import Ticket
    rows = (await session.scalars(select(Ticket).order_by(Ticket.updated_at.desc()).limit(500))).all()
    return [{"id": t.id, "user_id": t.user_id, "store_id": t.store_id, "subject": t.subject, "status": t.status, "updated_at": t.updated_at} for t in rows]


@router.get("/vpn-accounts", response_model=list[dict])
async def vpn_accounts(_: AdminUser, session: Session):
    rows = (await session.scalars(select(VpnAccount).order_by(VpnAccount.updated_at.desc()).limit(500))).all()
    return [{"id": a.id, "user_id": a.user_id, "store_id": a.store_id, "username": a.username, "status": a.status, "expires_at": a.expires_at, "traffic_limit_bytes": a.traffic_limit_bytes, "traffic_used_bytes": a.traffic_used_bytes} for a in rows]


@router.post("/orders/{order_id}/retry")
async def retry_order(order_id: uuid.UUID, admin: AdminUser, session: Session):
    o = await session.get(Order, order_id)
    if not o: raise NotFound("سفارش")
    await order_service.admin_retry(session, o, admin); return {"ok": True}


@router.post("/orders/{order_id}/manual-review")
async def review_order(order_id: uuid.UUID, body: OrderAction, admin: AdminUser, session: Session):
    o = await session.get(Order, order_id)
    if not o: raise NotFound("سفارش")
    await order_service.admin_mark_review(session, o, admin, body.reason); return {"ok": True}


@router.post("/orders/{order_id}/refund")
async def refund_order(order_id: uuid.UUID, body: OrderAction, admin: AdminUser, session: Session):
    o = await session.get(Order, order_id)
    if not o: raise NotFound("سفارش")
    await order_service.refund(session, o, admin, body.reason); return {"ok": True}


@router.post("/orders/{order_id}/attach-account")
async def attach_account(order_id: uuid.UUID, body: AttachExistingAccount, admin: AdminUser, session: Session):
    o = await session.get(Order, order_id, with_for_update=True)
    s = await session.get(Server, body.server_id)
    if not o or not s: raise NotFound("سفارش یا سرور")
    if o.status not in ("provisioning_failed", "manual_review"): raise AppError("INVALID_ORDER_STATE", "سفارش در وضعیت بررسی دستی نیست.", 409)
    product = await session.get(Product, o.product_id)
    if not product:
        raise NotFound("محصول")
    a = VpnAccount(username=body.username, user_id=o.user_id, store_id=o.store_id, order_id=o.id, product_id=o.product_id, server_id=s.id, panel_id=s.panel_id, panel_ref=body.panel_ref, subscription_url=body.subscription_url, status="active", expires_at=__import__("datetime").datetime.now(__import__("datetime").UTC) + __import__("datetime").timedelta(days=product.duration_days), traffic_limit_bytes=product.traffic_gb * 1024**3)
    session.add(a); await session.flush(); o.vpn_account_id, o.status, o.needs_review = a.id, "completed", False
    audit.record(session, "provisioning.account_attached", actor_id=admin.id, actor_type="admin", entity_type="vpn_account", entity_id=a.id, store_id=o.store_id, data={"reason": body.reason}); await session.commit(); return {"ok": True, "vpn_account_id": a.id}


# ----- Resellers, flags, audit -----
@router.get("/reseller-applications")
async def applications(_: AdminUser, session: Session):
    return [{"id": x.id, "user_id": x.user_id, "target_store_id": x.target_store_id, "store_name": x.store_name, "message": x.message, "status": x.status, "created_at": x.created_at} for x in (await session.scalars(select(ResellerApplication).order_by(ResellerApplication.created_at))).all()]


@router.post("/reseller-applications/{application_id}/review")
async def review_application(application_id: uuid.UUID, body: ResellerApproval, admin: AdminUser, session: Session):
    a = await session.get(ResellerApplication, application_id, with_for_update=True)
    if not a or a.status != "pending": raise NotFound("درخواست نمایندگی")
    if body.approve:
        target = await session.get(Store, a.target_store_id)
        if not target or target.status != "active":
            raise AppError("TARGET_STORE_INVALID", "فروشگاه مقصد نمایندگی فعال نیست.", 409)
        existing_store = await session.scalar(select(Store).where(Store.owner_user_id == a.user_id, Store.kind == "reseller", Store.parent_store_id == target.id))
        if existing_store:
            raise AppError("RESELLER_EXISTS", "این کاربر برای این فروشگاه قبلاً نمایندگی دارد.", 409)
        member = await session.scalar(select(StoreMembership).where(StoreMembership.store_id == target.id, StoreMembership.user_id == a.user_id, StoreMembership.status == "active"))
        if not member:
            raise AppError("STORE_MEMBERSHIP_REQUIRED", "متقاضی دیگر عضو فعال فروشگاه مقصد نیست.", 409)
    a.status = "approved" if body.approve else "rejected"; a.reviewed_by, a.reviewed_at = admin.id, __import__("datetime").datetime.now(__import__("datetime").UTC)
    if body.approve:
        slug = f"reseller-{str(a.id)[:8]}"
        st = Store(kind="reseller", name=a.store_name, slug=slug, owner_user_id=a.user_id, parent_store_id=target.id, currency=target.currency)
        session.add(st); await session.flush(); a.store_id = st.id
        session.add(ResellerProfile(store_id=st.id, user_id=a.user_id, debt_limit=body.debt_limit, api_enabled=True))
        session.add(StoreMembership(store_id=st.id, user_id=a.user_id, role="owner"))
    audit.record(session, "reseller.application_reviewed", actor_id=admin.id, actor_type="admin", entity_type="reseller_application", entity_id=a.id, data={"approve": body.approve, "reason": body.reason})
    await session.commit(); return {"ok": True, "status": a.status, "store_id": a.store_id}


@router.get("/feature-flags")
async def list_flags(_: AdminUser, session: Session): return [{"id": f.id, "key": f.key, "scope_type": f.scope_type, "scope_id": f.scope_id, "enabled": f.enabled, "note": f.note} for f in (await session.scalars(select(FeatureFlag))).all()]


@router.put("/feature-flags/{key}")
async def update_flag(key: str, body: FeatureUpdate, admin: AdminUser, session: Session):
    f = await session.scalar(select(FeatureFlag).where(FeatureFlag.key == key, FeatureFlag.scope_type == body.scope_type, FeatureFlag.scope_id == body.scope_id))
    if not f: f = FeatureFlag(key=key, scope_type=body.scope_type, scope_id=body.scope_id); session.add(f)
    f.enabled, f.note = body.enabled, body.note
    audit.record(session, "feature_flag.updated", actor_id=admin.id, actor_type="admin", entity_type="feature_flag", entity_id=f.id, data=body.model_dump()); await session.commit(); return {"ok": True}


@router.get("/settings")
async def settings(_: AdminUser, session: Session): return await settings_store.all_settings(session)


@router.put("/settings/{key:path}")
async def update_setting(key: str, body: SettingUpdate, admin: AdminUser, session: Session):
    if key.startswith("integration."):
        raise AppError("SETTING_RESERVED", "این تنظیم فقط از بخش یکپارچه‌سازی‌ها قابل تغییر است.", 400)
    await settings_store.set_value(session, key, body.value); audit.record(session, "system_setting.updated", actor_id=admin.id, actor_type="admin", entity_type="system_setting", entity_id=key, data={"value": body.value}); await session.commit(); return {"ok": True}


@router.get("/audit", response_model=list[dict])
async def audit_log(_: AdminUser, session: Session, action: str | None = None):
    q = select(AuditEvent).order_by(AuditEvent.created_at.desc()).limit(500)
    if action: q = q.where(AuditEvent.action == action)
    return [{"id": x.id, "actor_id": x.actor_id, "action": x.action, "entity_type": x.entity_type, "entity_id": x.entity_id, "store_id": x.store_id, "data": x.data, "ip": x.ip, "created_at": x.created_at} for x in (await session.scalars(q)).all()]


# ----- Coupon administration: Admin may create Store or explicit domain coupons -----
@router.get("/coupons")
async def list_coupons(_: AdminUser, session: Session, store_id: uuid.UUID | None = None):
    q = select(Coupon).order_by(Coupon.created_at.desc())
    if store_id:
        q = q.where(Coupon.store_id == store_id)
    from melorin.modules.catalog.service import coupon_out
    return [coupon_out(c) for c in (await session.scalars(q)).all()]


@router.post("/coupons", status_code=201)
async def create_admin_coupon(body: AdminCouponIn, admin: AdminUser, session: Session):
    from melorin.domain import coupon as cdom
    from melorin.modules.catalog.service import norm_code
    code = norm_code(body.code)
    if body.scope == "store" and not body.store_id:
        raise AppError("COUPON_SCOPE_FORBIDDEN", "برای Coupon فروشگاه باید store_id مشخص شود.", 400)
    if body.scope == "domain" and not (body.allowed_store_ids or body.allowed_store_kinds):
        raise AppError("COUPON_SCOPE_FORBIDDEN", "دامنه Coupon خالی است.", 400)
    rule = cdom.CouponRule(code=code, creator_type="admin", scope=body.scope, store_id=str(body.store_id) if body.store_id else None, allowed_store_ids=tuple(str(x) for x in body.allowed_store_ids or []), allowed_store_kinds=tuple(body.allowed_store_kinds or []), percent_bp=body.percent_bp, fixed=body.fixed, max_discount=body.max_discount, min_amount=body.min_amount, starts_at=body.starts_at, ends_at=body.ends_at, max_redemptions=body.max_redemptions, per_customer_limit=body.per_customer_limit, currency=body.currency, status=body.status)
    try:
        cdom.validate_definition(rule)
    except cdom.CouponError as e:
        raise AppError(e.code, e.message, 400) from e
    owner_key = "admin" if body.scope == "domain" else str(body.store_id)
    if await session.scalar(select(Coupon.id).where(Coupon.owner_key == owner_key, Coupon.code == code)):
        raise AppError("COUPON_EXISTS", "این کد تخفیف قبلاً ساخته شده است.", 409)
    c = Coupon(code=code, owner_key=owner_key, store_id=body.store_id, scope=body.scope, allowed_store_ids=[str(x) for x in body.allowed_store_ids or []] or None, allowed_store_kinds=body.allowed_store_kinds, creator_type="admin", creator_id=admin.id, funded_by=body.funded_by, percent_bp=body.percent_bp, fixed=body.fixed, max_discount=body.max_discount, min_amount=body.min_amount, currency=body.currency, starts_at=body.starts_at, ends_at=body.ends_at, max_redemptions=body.max_redemptions, per_customer_limit=body.per_customer_limit, product_ids=[str(x) for x in body.product_ids or []] or None, status=body.status)
    session.add(c)
    audit.record(session, "admin.coupon.created", actor_id=admin.id, actor_type="admin", entity_type="coupon", entity_id=c.id, store_id=body.store_id, data={"code": code, "scope": body.scope, "funded_by": body.funded_by})
    await session.commit()
    from melorin.modules.catalog.service import coupon_out
    return coupon_out(c)


@router.patch("/coupons/{coupon_id}")
async def patch_admin_coupon(coupon_id: uuid.UUID, body: CouponPatch, admin: AdminUser, session: Session):
    c = await session.get(Coupon, coupon_id, with_for_update=True)
    if not c:
        raise NotFound("کد تخفیف")
    for k, v in body.model_dump(exclude_none=True).items():
        setattr(c, k, v)
    audit.record(session, "admin.coupon.updated", actor_id=admin.id, actor_type="admin", entity_type="coupon", entity_id=c.id, store_id=c.store_id)
    await session.commit()
    from melorin.modules.catalog.service import coupon_out
    return coupon_out(c)


# ----- verified-email identity conflicts -----
@router.get("/identity-link-reviews")
async def identity_link_reviews(_: AdminUser, session: Session, status: str = "open"):
    rows = (await session.scalars(select(IdentityLinkReview).where(IdentityLinkReview.status == status).order_by(IdentityLinkReview.created_at))).all()
    return [{"id": r.id, "email": r.email, "source_user_id": r.source_user_id, "candidate_user_ids": r.candidate_user_ids, "provider": r.provider, "reason": r.reason, "status": r.status, "created_at": r.created_at} for r in rows]


@router.post("/identity-link-reviews/{review_id}/dismiss")
async def dismiss_identity_review(review_id: uuid.UUID, admin: AdminUser, session: Session):
    r = await session.get(IdentityLinkReview, review_id, with_for_update=True)
    if not r or r.status != "open":
        raise NotFound("درخواست اتصال هویت")
    r.status = "dismissed"; r.resolved_by = admin.id
    audit.record(session, "identity_link_review.dismissed", actor_id=admin.id, actor_type="admin", entity_type="identity_link_review", entity_id=r.id, data={"email": r.email})
    await session.commit()
    return {"ok": True}


@router.put("/reseller-stores/{store_id}/api")
async def toggle_reseller_api(store_id: uuid.UUID, enabled: bool, admin: AdminUser, session: Session):
    p = await session.scalar(select(ResellerProfile).where(ResellerProfile.store_id == store_id))
    if not p:
        raise NotFound("فروشگاه نماینده")
    p.api_enabled = enabled
    audit.record(session, "reseller.api_toggled", actor_id=admin.id, actor_type="admin", entity_type="reseller_store", entity_id=store_id, store_id=store_id, data={"enabled": enabled})
    await session.commit()
    return {"store_id": store_id, "api_enabled": enabled}
