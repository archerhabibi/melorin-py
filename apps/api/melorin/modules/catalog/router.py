import uuid

from fastapi import APIRouter
from sqlalchemy import select

from melorin.core import audit
from melorin.core.deps import OwnerCtx, Session, StoreCtx, main_store
from melorin.core.errors import AppError, NotFound
from melorin.domain import coupon as cdom
from melorin.modules.catalog import service
from melorin.modules.catalog.models import Coupon, CouponRedemption
from melorin.modules.catalog.schemas import CatalogItem, CouponIn, CouponPatch, CouponValidateIn, BundleOut, BundlePanelOut, QuoteRequest, QuoteWalletOut, StoreOut
from melorin.modules.stores.models import Store
from melorin.modules.vpn import allocation
from melorin.modules.vpn.models import VpnAccount
from melorin.modules.wallet import service as wallet

public = APIRouter(tags=["catalog"])


def _store_out(s: Store) -> StoreOut:
    return StoreOut(id=s.id, kind=s.kind, name=s.name, slug=s.slug, currency=s.currency, branding=s.branding, bot_username=s.bot_username, domain=s.domain)


@public.get("/stores/main", response_model=StoreOut)
async def get_main_store(session: Session):
    return _store_out(await main_store(session))


@public.get("/stores/by-slug/{slug}", response_model=StoreOut)
async def store_by_slug(slug: str, session: Session):
    s = await session.scalar(select(Store).where(Store.slug == slug, Store.status == "active"))
    if not s:
        raise NotFound("فروشگاه")
    return _store_out(s)


@public.get("/stores/by-domain/{domain}", response_model=StoreOut)
async def store_by_domain(domain: str, session: Session):
    s = await session.scalar(select(Store).where(Store.domain == domain.strip().lower().rstrip("."), Store.status == "active"))
    if not s:
        raise NotFound("فروشگاه")
    return _store_out(s)


@public.get("/tls/ask", include_in_schema=False)
async def tls_ask(domain: str, session: Session):
    """Caddy on-demand TLS gate: 200 only for the hostname of an active reseller store, 404 for everything else,
    so certificates are never issued for arbitrary names pointed at this server."""
    host = (domain or "").strip().lower().rstrip(".")
    if not host or len(host) > 253 or not await session.scalar(select(Store.id).where(Store.domain == host, Store.status == "active")):
        raise NotFound("فروشگاه")
    return {"ok": True}


@public.get("/stores/{store_id}", response_model=StoreOut)
async def get_store(store_id: uuid.UUID, session: Session):
    s = await session.get(Store, store_id)
    if not s or s.status != "active":
        raise NotFound("فروشگاه")
    return _store_out(s)


@public.get("/stores/{store_id}/catalog", response_model=list[CatalogItem])
async def catalog(store_id: uuid.UUID, session: Session):
    store = await session.get(Store, store_id)
    if not store or store.status != "active":
        raise NotFound("فروشگاه")
    rows = await allocation.sellable_products_priced(session, store)  # reseller: the lowest valid bundle price ("from")
    return [
        CatalogItem(
            product_id=p.id, code=p.code, name=p.name, description=p.description, category=p.category, duration_days=p.duration_days,
            traffic_gb=p.traffic_gb, max_devices=p.max_devices, currency=store.currency, price=price,
        )
        for p, _sp, price in rows
    ]


def _item(p, price: int, currency: str) -> CatalogItem:
    return CatalogItem(
        product_id=p.id, code=p.code, name=p.name, description=p.description, category=p.category, duration_days=p.duration_days,
        traffic_gb=p.traffic_gb, max_devices=p.max_devices, currency=currency, price=price,
    )


@public.get("/stores/{store_id}/bundles", response_model=list[BundleOut])
async def bundles(store_id: uuid.UUID, session: Session):
    """What a customer chooses first: the sales bundles open to this store (each has packages to sell)."""
    store = await session.get(Store, store_id)
    if not store or store.status != "active":
        raise NotFound("فروشگاه")
    return [
        BundleOut(
            id=v.group.id, name=v.group.name, kind_label=v.group.kind_label, selection_mode=v.group.selection_mode,
            naming_mode=v.group.naming_mode, panels=[BundlePanelOut(id=pid, label=label) for pid, label in v.panels],
        )
        for v in await allocation.sellable_bundles(session, store)
    ]


@public.get("/stores/{store_id}/bundles/{bundle_id}/packages", response_model=list[CatalogItem])
async def bundle_packages(store_id: uuid.UUID, bundle_id: uuid.UUID, session: Session):
    store = await session.get(Store, store_id)
    if not store or store.status != "active":
        raise NotFound("فروشگاه")
    return [_item(p, price, store.currency) for p, _sp, _pp, price in await allocation.packages_for_bundle(session, store, bundle_id)]


async def _owned_account(session, ctx, account_id) -> VpnAccount:
    account = await session.get(VpnAccount, account_id)
    if not account or account.user_id != ctx.user.id or account.store_id != ctx.store.id:
        raise NotFound("اکانت")
    return account


@public.get("/stores/{store_id}/accounts/{account_id}/renewal-packages", response_model=list[CatalogItem])
async def renewal_packages(account_id: uuid.UUID, ctx: StoreCtx, session: Session):
    """Renewal offers the packages of the bundle the account was sold through, at that bundle's prices."""
    account = await _owned_account(session, ctx, account_id)
    return [_item(p, price, ctx.store.currency) for p, price in await allocation.renewal_offers(session, ctx.store, account)]


async def _quote(session, ctx, product_id, code, *, bundle_id=None, selected_panel_id=None, vpn_account_id=None, enforce=False):
    product, sp = await service.get_sellable(session, ctx.store, product_id)
    account = await _owned_account(session, ctx, vpn_account_id) if vpn_account_id else None
    # Same core rule the order will apply, so a quote never promises what checkout would refuse.
    plan = await allocation.plan_sale(
        session, store=ctx.store, product=product, sp=sp, kind="renewal" if account else "purchase", account=account,
        bundle_id=bundle_id, selected_panel_id=selected_panel_id, enforce=enforce,
    )
    coupon, disc = await service.resolve_coupon(session, ctx.store, ctx.user.id, product, plan.unit_price, code, lock=False)
    main = await main_store(session)
    return await service.build_quote(session, ctx.store, product, sp, coupon, disc, main_currency=main.currency, prices=plan.prices, customer_price=plan.unit_price if ctx.store.kind == "reseller" else None), product


@public.post("/stores/{store_id}/checkout/quote", response_model=QuoteWalletOut)
async def checkout_quote(body: QuoteRequest, ctx: StoreCtx, session: Session):
    """Core-side quote: store, price, coupon and wallet balance. Purchases are wallet-only (v1.1)."""
    q, product = await _quote(session, ctx, body.product_id, body.coupon_code, bundle_id=body.bundle_id, selected_panel_id=body.selected_panel_id, vpn_account_id=body.vpn_account_id, enforce=True)
    w = await wallet.get_wallet(session, ctx.user.id, ctx.store.id, currency=ctx.store.currency)
    await session.commit()
    return QuoteWalletOut(product_id=product.id, unit_price=q.unit_price, discount=q.discount, total=q.total, currency=q.currency, coupon_code=q.coupon_code, wallet_balance=w.balance, sufficient_funds=w.balance >= q.total)


@public.post("/stores/{store_id}/coupons/validate")
async def validate_coupon(body: CouponValidateIn, ctx: StoreCtx, session: Session):
    q, _ = await _quote(session, ctx, body.product_id, body.code)
    return {"valid": True, "code": q.coupon_code, "discount": q.discount, "total": q.total, "currency": q.currency}


# ---------------- store-scoped coupon management (reseller owner of the store, or Admin) ----------------
def _rule_from_in(body: CouponIn, store: Store, creator_type: str) -> cdom.CouponRule:
    return cdom.CouponRule(
        code=service.norm_code(body.code), status=body.status, creator_type=creator_type, scope="store", store_id=str(store.id),
        product_ids=tuple(str(x) for x in body.product_ids or []), percent_bp=body.percent_bp, fixed=body.fixed, max_discount=body.max_discount,
        min_amount=body.min_amount, starts_at=body.starts_at, ends_at=body.ends_at, max_redemptions=body.max_redemptions,
        per_customer_limit=body.per_customer_limit, currency=store.currency,
    )


@public.get("/stores/{store_id}/coupons")
async def list_coupons(ctx: OwnerCtx, session: Session):
    rows = (await session.scalars(select(Coupon).where(Coupon.owner_key == str(ctx.store.id)).order_by(Coupon.created_at.desc()))).all()
    return [service.coupon_out(c) for c in rows]


@public.post("/stores/{store_id}/coupons", status_code=201)
async def create_coupon(body: CouponIn, ctx: OwnerCtx, session: Session):
    creator = "admin" if ctx.is_admin and not ctx.is_owner else "reseller"
    rule = _rule_from_in(body, ctx.store, creator)
    try:
        cdom.validate_definition(rule, creator_store_id=str(ctx.store.id))
    except cdom.CouponError as e:
        raise AppError(e.code, e.message, 400) from e
    if await session.scalar(select(Coupon.id).where(Coupon.owner_key == str(ctx.store.id), Coupon.code == rule.code)):
        raise AppError("COUPON_EXISTS", "این کد تخفیف قبلاً ساخته شده است.", 409)
    c = Coupon(
        code=rule.code, owner_key=str(ctx.store.id), store_id=ctx.store.id, scope="store", creator_type=creator, creator_id=ctx.user.id,
        funded_by="store", percent_bp=rule.percent_bp, fixed=rule.fixed, max_discount=rule.max_discount, min_amount=rule.min_amount,
        currency=ctx.store.currency, starts_at=rule.starts_at, ends_at=rule.ends_at, max_redemptions=rule.max_redemptions,
        per_customer_limit=rule.per_customer_limit, product_ids=[str(x) for x in body.product_ids or []] or None, status=rule.status,
    )
    session.add(c)
    await session.flush()
    audit.record(session, "coupon.created", actor_id=ctx.user.id, actor_type="admin" if creator == "admin" else "reseller", entity_type="coupon", entity_id=c.id, store_id=ctx.store.id, data={"code": c.code})
    await session.commit()
    return service.coupon_out(c)


@public.patch("/stores/{store_id}/coupons/{coupon_id}")
async def patch_coupon(coupon_id: uuid.UUID, body: CouponPatch, ctx: OwnerCtx, session: Session):
    c = await session.get(Coupon, coupon_id, with_for_update=True)
    if not c or c.owner_key != str(ctx.store.id):
        raise NotFound("کد تخفیف")
    for k, v in body.model_dump(exclude_none=True).items():
        setattr(c, k, v)
    audit.record(session, "coupon.updated", actor_id=ctx.user.id, actor_type="admin" if ctx.is_admin and not ctx.is_owner else "reseller", entity_type="coupon", entity_id=c.id, store_id=ctx.store.id, data=body.model_dump(exclude_none=True, mode="json"))
    await session.commit()
    return service.coupon_out(c)


@public.get("/stores/{store_id}/coupons/redemptions")
async def coupon_redemptions(ctx: OwnerCtx, session: Session):
    rows = (await session.scalars(select(CouponRedemption).where(CouponRedemption.store_id == ctx.store.id).order_by(CouponRedemption.created_at.desc()).limit(500))).all()
    return [{"id": r.id, "coupon_id": r.coupon_id, "order_id": r.order_id, "user_id": r.user_id, "amount": r.amount, "currency": r.currency, "status": r.status, "created_at": r.created_at} for r in rows]
