import json
import uuid

from fastapi import APIRouter, Query, Response
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from melorin.core import audit, settings_store
from melorin.core.crypto import encrypt
from melorin.core.deps import CurrentUser, OwnerCtx, Session, main_store
from melorin.core.errors import AppError, NotFound
from melorin.modules.identity.models import User
from melorin.modules.orders.models import Order
from melorin.modules.payments import service as payments
from melorin.modules.payments.models import Payment
from melorin.modules.payments.schemas import payment_out
from melorin.modules.reseller import api_keys, identity
from melorin.modules.reseller.schemas import (
    ApiCredentialIn,
    ApplicationDetailsIn,
    ApplicationIn,
    PriceBatchIn,
    PriceIn,
    CustomerOut,
    CustomerWalletAdjustment,
    PaymentConfigIn,
    PaymentReview,
    StoreBrandingUpdate,
    WebhookEndpointIn,
    WebhookEndpointPatch,
)
from melorin.modules.stores.models import ApiCredential, ResellerApplication, ResellerProfile, StoreMembership, StorePaymentConfiguration
from melorin.modules.wallet import service as wallet
from melorin.modules.webhooks import service as webhooks
from fastapi import Header
from types import SimpleNamespace
from melorin.modules.vpn import allocation, inquiry
from melorin.modules.vpn.models import VpnAccount
from melorin.modules.vpn.schemas import OwnerAccountOut
from melorin.modules.stores.models import Store
from melorin.modules.vpn.bundles import Bundle, StoreBundle

router = APIRouter(tags=["reseller"])


async def application_target_store(session, user_id, target_store_id):
    """Resolve the represented store and require active membership in that store.

    Missing target is kept backwards-compatible by selecting Main Store. New
    clients should always send target_store_id so a user can apply to several
    stores independently.
    """
    target = await session.get(Store, target_store_id) if target_store_id else await main_store(session)
    if not target or target.status != "active":
        raise NotFound("فروشگاه مقصد نمایندگی")
    membership = await session.scalar(
        select(StoreMembership).where(
            StoreMembership.store_id == target.id,
            StoreMembership.user_id == user_id,
            StoreMembership.status == "active",
        )
    )
    if not membership:
        raise AppError("STORE_MEMBERSHIP_REQUIRED", "برای درخواست نمایندگی باید عضو فعال همان فروشگاه باشید.", 403)
    return target


def application_out(a: ResellerApplication) -> dict:
    """Applicant-facing view. The bot token is never included."""
    return {
        "id": a.id,
        "target_store_id": a.target_store_id,
        "store_name": a.store_name,
        "message": a.message,
        "status": a.status,
        "needs_details": a.status == "awaiting_details",
        "domain": a.domain,
        "bot_username": a.bot_username,
        "bot_verified": a.bot_verified,
        "review_reason": a.review_reason if a.status == "rejected" else None,
        "store_id": a.store_id,
        "created_at": a.created_at,
    }


@router.post("/reseller/applications")
async def apply(body: ApplicationIn, user: CurrentUser, session: Session):
    target = await application_target_store(session, user.id, body.target_store_id)
    if await session.scalar(
        select(ResellerProfile.id).where(
            ResellerProfile.user_id == user.id, ResellerProfile.store_id.in_(select(Store.id).where(Store.parent_store_id == target.id))
        )
    ):
        raise AppError("ALREADY_RESELLER", "شما برای این فروشگاه قبلاً نماینده هستید.", 409)
    if await session.scalar(
        select(ResellerApplication).where(
            ResellerApplication.user_id == user.id,
            ResellerApplication.target_store_id == target.id,
            ResellerApplication.status.in_(("pending", "awaiting_details")),
        )
    ):
        raise AppError("APPLICATION_EXISTS", "یک درخواست در حال بررسی دارید.", 409)
    domain = bot_key = username = token = None
    if body.domain is not None:  # one-step (web form): identity is validated now
        domain = identity.normalize_domain(body.domain)
        token, bot_key = identity.parse_bot_token(body.bot_token)
        await identity.ensure_identity_free(session, domain=domain, bot_key=bot_key)
        username = await identity.verify_bot(token)
        if username:
            await identity.ensure_identity_free(session, domain=domain, bot_key=bot_key, bot_username=username)
    a = ResellerApplication(
        user_id=user.id,
        target_store_id=target.id,
        store_name=body.store_name.strip(),
        message=body.message,
        domain=domain,
        bot_token_enc=encrypt(token) if token else None,
        bot_key=bot_key,
        bot_username=username,
        bot_verified=username is not None,
    )
    session.add(a)
    audit.record(
        session,
        "reseller.applied",
        actor_id=user.id,
        entity_type="reseller_application",
        entity_id=a.id,
        data={"domain": domain, "bot_key": bot_key, "two_step": domain is None},
    )
    await session.commit()
    return application_out(a)


@router.get("/reseller/applications")
async def my_applications(user: CurrentUser, session: Session):
    rows = (
        await session.scalars(
            select(ResellerApplication)
            .where(ResellerApplication.user_id == user.id)
            .order_by(ResellerApplication.created_at.desc())
            .limit(50)
        )
    ).all()
    return [application_out(a) for a in rows]


@router.post("/reseller/applications/{application_id}/cancel")
async def cancel_application(application_id: uuid.UUID, user: CurrentUser, session: Session):
    a = await session.get(ResellerApplication, application_id, with_for_update=True)
    if not a or a.user_id != user.id:
        raise NotFound("درخواست نمایندگی")
    if a.status not in ("pending", "awaiting_details"):
        raise AppError("APPLICATION_NOT_PENDING", "فقط درخواست در حال بررسی قابل لغو است.", 409)
    a.status, a.bot_token_enc = "cancelled", None
    audit.record(session, "reseller.application_cancelled", actor_id=user.id, entity_type="reseller_application", entity_id=a.id)
    await session.commit()
    return application_out(a)


@router.post("/reseller/applications/{application_id}/details")
async def submit_details(application_id: uuid.UUID, body: ApplicationDetailsIn, user: CurrentUser, session: Session):
    """Second step of a request the admin already approved: the applicant sends the store domain and the bot token,
    both are validated, and the reseller store is created right away (the admin approval is the authorisation)."""
    from melorin.modules.reseller.provisioning import create_reseller_store

    a = await session.get(ResellerApplication, application_id, with_for_update=True)
    if not a or a.user_id != user.id:
        raise NotFound("درخواست نمایندگی")
    if a.status != "awaiting_details":
        raise AppError("APPLICATION_NOT_AWAITING_DETAILS", "این درخواست در مرحلهٔ دریافت اطلاعات نیست.", 409)
    target = await application_target_store(session, user.id, a.target_store_id)
    if await session.scalar(
        select(Store.id).where(Store.owner_user_id == user.id, Store.kind == "reseller", Store.parent_store_id == target.id)
    ):
        raise AppError("ALREADY_RESELLER", "شما برای این فروشگاه قبلاً نماینده هستید.", 409)
    domain = identity.normalize_domain(body.domain)
    token, bot_key = identity.parse_bot_token(body.bot_token)
    await identity.ensure_identity_free(session, domain=domain, bot_key=bot_key, exclude_application_id=a.id)
    username = await identity.verify_bot(token)
    if username is None:  # Telegram unreachable: a store must not be created for a bot nobody has verified
        # 424 (not 5xx): the bot runner replays an update on 5xx, which would hammer Telegram while it is unreachable.
        raise AppError("TELEGRAM_UNREACHABLE", "ارتباط با تلگرام برقرار نشد؛ کمی بعد دوباره تلاش کنید.", 424)
    await identity.ensure_identity_free(session, domain=domain, bot_key=bot_key, bot_username=username, exclude_application_id=a.id)
    a.domain, a.bot_key, a.bot_username, a.bot_verified = domain, bot_key, username, True
    a.status = "approved"
    await create_reseller_store(session, a, target, token_enc=encrypt(token), debt_limit=a.approved_debt_limit or 0)
    audit.record(
        session,
        "reseller.application_details_submitted",
        actor_id=user.id,
        entity_type="reseller_application",
        entity_id=a.id,
        data={"domain": domain, "bot_key": bot_key, "bot_username": username},
    )
    try:
        await session.commit()
    except IntegrityError:  # another applicant took the same domain/bot between the check and the commit
        await session.rollback()
        raise AppError("IDENTITY_TAKEN", "این دامنه یا ربات همین الان برای فروشگاه دیگری ثبت شد؛ مقدار دیگری بفرستید.", 409) from None
    return application_out(a)


@router.get("/stores/{store_id}/reseller/profile")
async def profile(ctx: OwnerCtx, session: Session):
    p = await session.scalar(select(ResellerProfile).where(ResellerProfile.store_id == ctx.store.id))
    main = await main_store(session)
    w = await wallet.get_wallet(session, ctx.store.owner_user_id, main.id, currency=main.currency)
    await session.commit()
    near = float(await settings_store.get(session, "debt.near_ratio") or 0.8)
    from melorin.domain import debt

    return {
        "store_id": ctx.store.id,
        "store_name": ctx.store.name,
        "store_currency": ctx.store.currency,
        "debt_limit": p.debt_limit if p else 0,
        "sales_enabled": p.sales_enabled if p else False,
        "api_enabled": p.api_enabled if p else False,
        "main_wallet": {"balance": w.balance, "currency": w.currency, "debt_state": debt.state(w.balance, p.debt_limit if p else 0, near)},
    }


@router.get("/stores/{store_id}/reseller/bundles")
async def reseller_bundles(ctx: OwnerCtx, session: Session):
    rows = (
        await session.execute(
            select(Bundle, StoreBundle)
            .join(StoreBundle, StoreBundle.bundle_id == Bundle.id, isouter=True)
            .where(Bundle.is_enabled.is_(True), Bundle.reseller_enabled.is_(True))
            .order_by(Bundle.created_at.desc())
        )
    ).all()
    return [
        {
            "id": b.id,
            "name": b.name,
            "selection_mode": b.selection_mode,
            "naming_mode": b.naming_mode,
            "is_enabled": access.is_enabled if access else True,
            "sales_limit": b.sales_limit,
            "sold_count": b.sold_count,
        }
        for b, access in rows
    ]


@router.put("/stores/{store_id}/reseller/bundles/{bundle_id}")
async def toggle_reseller_bundle(bundle_id: uuid.UUID, body: dict, ctx: OwnerCtx, session: Session):
    b = await session.get(Bundle, bundle_id)
    if not b or not b.is_enabled or not b.reseller_enabled:
        raise NotFound("بسته فروش")
    row = await session.scalar(select(StoreBundle).where(StoreBundle.store_id == ctx.store.id, StoreBundle.bundle_id == b.id))
    if not row:
        row = StoreBundle(store_id=ctx.store.id, bundle_id=b.id)
        session.add(row)
    row.is_enabled = bool(body.get("is_enabled", True))
    audit.record(
        session,
        "reseller.bundle_toggled",
        actor_id=ctx.user.id,
        actor_type="reseller",
        entity_type="bundle",
        entity_id=b.id,
        store_id=ctx.store.id,
        data={"enabled": row.is_enabled},
    )
    await session.commit()
    return {"ok": True, "is_enabled": row.is_enabled}


@router.get("/stores/{store_id}/reseller/prices")
async def reseller_prices(ctx: OwnerCtx, session: Session):
    """Products this store may sell. Per product: the store-wide retail price and, per sales bundle, the cost
    (reseller price), the store's own price in that bundle, the price actually charged and its state."""
    return await allocation.reseller_price_table(session, ctx.store)


@router.put("/stores/{store_id}/reseller/prices/{product_id}")
async def set_reseller_price(product_id: uuid.UUID, body: PriceIn, ctx: OwnerCtx, session: Session):
    """The reseller sets the retail price of one product for THIS store only. The core enforces the cost floor."""
    sp = await allocation.set_customer_price(session, ctx.store, product_id, body.customer_price)
    audit.record(
        session,
        "reseller.price_set",
        actor_id=ctx.user.id,
        actor_type="reseller",
        entity_type="product",
        entity_id=product_id,
        store_id=ctx.store.id,
        data={"customer_price": sp.customer_price},
    )
    await session.commit()
    return {"ok": True, "product_id": product_id, "customer_price": sp.customer_price}


@router.put("/stores/{store_id}/reseller/bundles/{bundle_id}/prices/{product_id}")
async def set_reseller_bundle_price(bundle_id: uuid.UUID, product_id: uuid.UUID, body: PriceIn, ctx: OwnerCtx, session: Session):
    """The reseller sets the retail price of one package in ONE sales bundle of THIS store. Null or 0 removes it and the
    bundle uses the store-wide price again. The core refuses a price below that bundle's reseller price (the cost)."""
    price = await allocation.set_bundle_price(session, ctx.store, bundle_id, product_id, body.customer_price)
    audit.record(
        session,
        "reseller.bundle_price_set",
        actor_id=ctx.user.id,
        actor_type="reseller",
        entity_type="product",
        entity_id=product_id,
        store_id=ctx.store.id,
        data={"bundle_id": str(bundle_id), "customer_price": price},
    )
    await session.commit()
    return {"ok": True, "bundle_id": bundle_id, "product_id": product_id, "customer_price": price}


@router.post("/stores/{store_id}/reseller/prices/batch")
async def set_reseller_prices_batch(body: PriceBatchIn, ctx: OwnerCtx, session: Session):
    """Save many prices at once (the pricing table of the panel), all or nothing: store-wide and per-bundle prices share
    one request. Returns the fresh price table. A refused item lists every problem and nothing is saved."""
    changed = await allocation.set_prices_batch(session, ctx.store, [(i.bundle_id, i.product_id, i.customer_price) for i in body.items])
    for bundle_id, product_id, price in changed:
        action = "reseller.price_set" if bundle_id is None else "reseller.bundle_price_set"
        audit.record(
            session,
            action,
            actor_id=ctx.user.id,
            actor_type="reseller",
            entity_type="product",
            entity_id=product_id,
            store_id=ctx.store.id,
            data={"bundle_id": str(bundle_id) if bundle_id else None, "customer_price": price, "batch": True},
        )
    await session.commit()
    return {"ok": True, "changed": len(changed), "prices": await allocation.reseller_price_table(session, ctx.store)}


@router.patch("/stores/{store_id}/reseller/branding")
async def branding(body: StoreBrandingUpdate, ctx: OwnerCtx, session: Session):
    if body.branding is not None:
        ctx.store.branding = body.branding
    if body.bot_messages is not None:
        ctx.store.bot_messages = body.bot_messages
    audit.record(
        session, "reseller.branding_updated", actor_id=ctx.user.id, entity_type="store", entity_id=ctx.store.id, store_id=ctx.store.id
    )
    await session.commit()
    return {"ok": True}


@router.get("/stores/{store_id}/reseller/customers", response_model=list[CustomerOut])
async def customers(ctx: OwnerCtx, session: Session):
    q = (
        select(User, StoreMembership)
        .join(StoreMembership, StoreMembership.user_id == User.id)
        .where(StoreMembership.store_id == ctx.store.id, StoreMembership.role == "customer")
        .order_by(StoreMembership.created_at.desc())
    )
    return [
        CustomerOut(user_id=u.id, display_name=u.display_name, email=u.email, status=m.status, joined_at=m.created_at)
        for u, m in (await session.execute(q)).all()
    ]


@router.get("/stores/{store_id}/reseller/accounts", response_model=list[OwnerAccountOut])
async def store_accounts(
    ctx: OwnerCtx,
    session: Session,
    response: Response,
    q: str | None = Query(None, max_length=200, description="account name, customer name or e-mail"),
    state: str | None = Query(None, pattern="^(active|expiring|expired)$", description="filter chip"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    """The reseller's inquiry. The LIST (no search) is only the accounts they made themselves; a SEARCH also finds the
    accounts of THEIR OWN store's customers (never another store's)."""
    term = inquiry.clean_query(q)
    cond = [VpnAccount.archived_at.is_(None)]
    if term:
        cond += [inquiry.reseller_visible(ctx.user.id, ctx.store.id), inquiry.owner_clause(term, User)]
    else:
        cond.append(VpnAccount.user_id == ctx.user.id)
    state_cond = inquiry.state_clause(state)
    if state_cond is not None:
        cond.append(state_cond)
    base = select(VpnAccount, User).join(User, User.id == VpnAccount.user_id).where(*cond)
    total = await session.scalar(select(func.count()).select_from(base.subquery()))
    response.headers["X-Total-Count"] = str(total or 0)
    rows = (await session.execute(base.order_by(VpnAccount.created_at.desc()).limit(limit).offset(offset))).all()
    return [inquiry.owner_account_out(a, u, owner_id=ctx.user.id) for a, u in rows]


@router.get("/stores/{store_id}/reseller/accounts/summary")
async def store_accounts_summary(ctx: OwnerCtx, session: Session):
    """Chip counters over the list scope: the reseller's OWN accounts."""
    return await inquiry.summary(session, VpnAccount.user_id == ctx.user.id, VpnAccount.archived_at.is_(None))


async def _store_account(session, ctx, account_id: uuid.UUID):
    """One account the reseller may act on: their own, or one of THEIR OWN store's customers' (never another store's)."""
    row = (
        await session.execute(
            select(VpnAccount, User)
            .join(User, User.id == VpnAccount.user_id)
            .where(VpnAccount.id == account_id, inquiry.reseller_visible(ctx.user.id, ctx.store.id))
        )
    ).first()
    if not row:
        raise NotFound("اکانت VPN")
    return row


async def _account_context(session, a: VpnAccount, holder: User):
    """The account holder's own context in the store the account lives in: the renewal then runs through exactly the
    same core rules as a renewal started by the holder (ownership, window, package, price, wallet)."""
    from melorin.core.deps import resolve_store_context  # lazy: deps imports this package's models

    return await resolve_store_context(session, a.store_id, holder)


@router.get("/stores/{store_id}/reseller/accounts/{account_id}", response_model=OwnerAccountOut)
async def store_account(account_id: uuid.UUID, ctx: OwnerCtx, session: Session):
    a, u = await _store_account(session, ctx, account_id)
    return inquiry.owner_account_out(a, u, owner_id=ctx.user.id)


@router.post("/stores/{store_id}/reseller/accounts/{account_id}/refresh", response_model=OwnerAccountOut)
async def store_account_refresh(account_id: uuid.UUID, ctx: OwnerCtx, session: Session, response: Response):
    """Owner's live view: re-read one of the store's accounts from its VPN panel."""
    a, u = await _store_account(session, ctx, account_id)
    response.headers["X-Panel-Synced"] = "1" if await inquiry.refresh_from_panel(session, a) else "0"
    return inquiry.owner_account_out(a, u, owner_id=ctx.user.id)


@router.get("/stores/{store_id}/reseller/accounts/{account_id}/renewal")
async def store_account_renewal(account_id: uuid.UUID, ctx: OwnerCtx, session: Session):
    """What a renewal of this account would be (package, price, new expiry) — the same answer the account's holder gets."""
    from melorin.modules.catalog.router import renewal_info  # lazy: catalog imports reseller-side models

    a, u = await _store_account(session, ctx, account_id)
    return await renewal_info(a.id, await _account_context(session, a, u), session)


class OwnerRenewIn(BaseModel):
    channel: str = Field(default="web", pattern="^(web|telegram)$")


@router.post("/stores/{store_id}/reseller/accounts/{account_id}/renew", status_code=201)
async def store_account_renew(
    account_id: uuid.UUID,
    body: OwnerRenewIn,
    ctx: OwnerCtx,
    session: Session,
    idempotency_key: str = Header(..., alias="Idempotency-Key", min_length=8, max_length=100),
):
    """Renew one of the reseller's OWN accounts, or one of THEIR OWN store's customers' accounts, with the account's own
    package at its current price. The order belongs to the account's holder and is paid from that holder's wallet in the
    store (the reseller can top it up); every renewal rule stays in the core. Customers of other stores: 404."""
    from melorin.modules.orders import service as orders  # lazy: orders imports the vpn package
    from melorin.modules.orders.router import out as order_out

    a, u = await _store_account(session, ctx, account_id)
    product_id, actor_id, is_own = a.product_id, ctx.user.id, a.user_id == ctx.user.id
    order = await orders.create_order(
        session,
        await _account_context(session, a, u),
        product_id=product_id,
        idempotency_key=idempotency_key,
        kind="renewal",
        vpn_account_id=account_id,
        channel=body.channel,
    )
    if not is_own:
        audit.record(
            session,
            "order.renewed_by_owner",
            actor_id=actor_id,
            entity_type="order",
            entity_id=order.id,
            store_id=order.store_id,
            data={"vpn_account_id": str(account_id), "customer_id": str(order.user_id)},
        )
        await session.commit()
    return order_out(order)


@router.get("/stores/{store_id}/reseller/accounts/{account_id}/qr.png", response_class=Response, responses={200: {"content": {"image/png": {}}}})
async def store_account_qr(account_id: uuid.UUID, ctx: OwnerCtx, session: Session):
    a, _ = await _store_account(session, ctx, account_id)
    link = a.subscription_url or (a.links[0] if isinstance(a.links, list) and a.links else None)
    if not link:
        raise NotFound("لینک اشتراک")
    from melorin.modules.orders.delivery import render_qr_png  # lazy: avoids a vpn <-> orders import cycle

    return Response(render_qr_png(link), media_type="image/png", headers={"Cache-Control": "private, no-store"})


async def adjust_customer_wallet_core(
    session, ctx, customer_id: uuid.UUID, body: CustomerWalletAdjustment, actor_type: str = "reseller"
) -> dict:
    """Reseller tops up its own customer's wallet in its own store. The cash went to the reseller, so the
    contra account is the store's reseller_cash account (never Main Store, never another store)."""
    membership = await session.scalar(
        select(StoreMembership).where(
            StoreMembership.store_id == ctx.store.id, StoreMembership.user_id == customer_id, StoreMembership.role == "customer"
        )
    )
    if not membership or membership.status != "active":
        raise NotFound("مشتری")
    if body.amount == 0:
        raise AppError("BAD_AMOUNT", "مبلغ نامعتبر است.", 400)
    cap = await settings_store.get(session, "reseller.manual_topup_max")
    if cap and abs(body.amount) > int(cap):
        raise AppError("BAD_AMOUNT", "مبلغ از سقف مجاز شارژ دستی بیشتر است.", 400)
    w = await wallet.get_wallet(session, customer_id, ctx.store.id, currency=ctx.store.currency)
    # Lock before checking a negative correction. The check and ledger post
    # must observe one serialized balance, not two concurrent snapshots.
    await wallet.lock_wallets(session, [w])
    if body.amount < 0 and w.balance + body.amount < 0:
        raise AppError("INSUFFICIENT_FUNDS", "اصلاح موجودی نمی‌تواند کیف پول را منفی کند.", 409)
    postings = [
        wallet.Posting(body.amount, wallet=w, min_balance=0),
        wallet.Posting(-body.amount, account=wallet.acc_reseller_cash(ctx.store.id)),
    ]
    tx, created = await wallet.post(
        session,
        kind="reseller_manual_topup" if body.amount > 0 else "reseller_manual_correction",
        key=f"reseller-adjust:{ctx.store.id}:{body.idempotency_key}",
        currency=ctx.store.currency,
        store_id=ctx.store.id,
        postings=postings,
        actor_id=ctx.user.id,
        memo=(body.reason + (f" | ref: {body.reference}" if body.reference else ""))[:500],
    )
    if created:
        audit.record(
            session,
            "reseller.customer_wallet_adjusted",
            actor_id=ctx.user.id,
            actor_type=actor_type,
            entity_type="wallet",
            entity_id=w.id,
            store_id=ctx.store.id,
            data={
                "customer_id": str(customer_id),
                "amount": body.amount,
                "reason": body.reason,
                "reference": body.reference,
                "tx": str(tx.id),
            },
        )
    await session.commit()
    return {"ok": True, "balance": w.balance, "transaction_id": tx.id}


@router.post("/stores/{store_id}/reseller/customers/{customer_id}/wallet")
async def adjust_customer_wallet(customer_id: uuid.UUID, body: CustomerWalletAdjustment, ctx: OwnerCtx, session: Session):
    return await adjust_customer_wallet_core(session, ctx, customer_id, body)


@router.get("/stores/{store_id}/reseller/reports")
async def report(ctx: OwnerCtx, session: Session):
    rows = (
        await session.execute(
            select(Order.status, func.count(), func.coalesce(func.sum(Order.total), 0), func.coalesce(func.sum(Order.reseller_cost), 0))
            .where(Order.store_id == ctx.store.id)
            .group_by(Order.status)
        )
    ).all()
    return {
        "store_id": ctx.store.id,
        "currency": ctx.store.currency,
        "orders": [{"status": s, "count": n, "total": total, "reseller_cost": cost} for s, n, total, cost in rows],
    }


# ---------------- store-owned payment destination ----------------
@router.get("/stores/{store_id}/reseller/payment-config")
async def get_payment_config(ctx: OwnerCtx, session: Session):
    rows = (await session.scalars(select(StorePaymentConfiguration).where(StorePaymentConfiguration.store_id == ctx.store.id))).all()
    return [
        {"provider": r.provider, "is_enabled": r.is_enabled, "public_config": r.public_config, "has_secret": bool(r.secret_enc)}
        for r in rows
    ]


@router.put("/stores/{store_id}/reseller/payment-config/{provider}")
async def put_payment_config(provider: str, body: PaymentConfigIn, ctx: OwnerCtx, session: Session):
    from melorin.modules.payments.adapters.registry import get_adapter

    get_adapter(provider)
    row = await session.scalar(
        select(StorePaymentConfiguration).where(
            StorePaymentConfiguration.store_id == ctx.store.id, StorePaymentConfiguration.provider == provider
        )
    )
    if not row:
        row = StorePaymentConfiguration(store_id=ctx.store.id, provider=provider)
        session.add(row)
    row.is_enabled, row.public_config, row.updated_by = body.is_enabled, body.public_config, ctx.user.id
    if body.secret is not None:
        row.secret_enc = encrypt(json.dumps(body.secret))
    audit.record(
        session,
        "store.payment_config_updated",
        actor_id=ctx.user.id,
        actor_type="reseller",
        entity_type="store",
        entity_id=ctx.store.id,
        store_id=ctx.store.id,
        data={"provider": provider, "enabled": body.is_enabled, "secret_changed": body.secret is not None},
    )
    await session.commit()
    return {"ok": True}


@router.get("/stores/{store_id}/reseller/payments")
async def store_payments(ctx: OwnerCtx, session: Session, status: str | None = None):
    q = select(Payment).where(Payment.store_id == ctx.store.id).order_by(Payment.created_at.desc()).limit(200)
    if status:
        q = q.where(Payment.status == status)
    return [payment_out(p) for p in (await session.scalars(q)).all()]


@router.post("/stores/{store_id}/reseller/payments/{payment_id}/review")
async def review_store_payment(payment_id: uuid.UUID, body: PaymentReview, ctx: OwnerCtx, session: Session):
    p = await session.get(Payment, payment_id)
    if not p or p.store_id != ctx.store.id:
        raise NotFound("پرداخت")
    if p.provider != "manual_card":
        raise AppError("PAYMENT_REVIEW_FORBIDDEN", "تأیید پرداخت‌های درگاه فقط پس از callback معتبر انجام می‌شود.", 403)
    if body.approve:
        p = await payments.mark_succeeded(session, p.id, actor_id=ctx.user.id, actor_type="reseller", note=body.note)
    else:
        p = await payments.mark_failed(session, p.id, actor_id=ctx.user.id, reason=body.note)
    return payment_out(p)


# ---------------- Reseller API credentials ----------------
@router.get("/stores/{store_id}/reseller/api-credentials")
async def list_credentials(ctx: OwnerCtx, session: Session):
    rows = (
        await session.scalars(select(ApiCredential).where(ApiCredential.store_id == ctx.store.id).order_by(ApiCredential.created_at.desc()))
    ).all()
    return [api_keys.out(c) for c in rows]


@router.post("/stores/{store_id}/reseller/api-credentials", status_code=201)
async def create_credential(body: ApiCredentialIn, ctx: OwnerCtx, session: Session):
    cred, raw = await api_keys.create(session, ctx.store, ctx.user, body)
    return {**api_keys.out(cred), "api_key": raw, "warning": "این کلید فقط یک بار نمایش داده می‌شود."}


@router.post("/stores/{store_id}/reseller/api-credentials/{cred_id}/{action}")
async def credential_action(cred_id: uuid.UUID, action: str, ctx: OwnerCtx, session: Session):
    cred = await session.get(ApiCredential, cred_id, with_for_update=True)
    if not cred or cred.store_id != ctx.store.id:
        raise NotFound("کلید API")
    if action == "rotate":
        new, raw = await api_keys.rotate(session, cred, ctx.user)
        return {**api_keys.out(new), "api_key": raw, "warning": "این کلید فقط یک بار نمایش داده می‌شود."}
    await api_keys.set_status(session, cred, action, ctx.user)
    return api_keys.out(cred)


# ---------------- Outgoing webhooks ----------------
@router.get("/stores/{store_id}/reseller/webhooks")
async def list_webhooks(ctx: OwnerCtx, session: Session):
    return [webhooks.endpoint_out(e) for e in await webhooks.list_endpoints(session, ctx.store.id)]


@router.post("/stores/{store_id}/reseller/webhooks", status_code=201)
async def create_webhook(body: WebhookEndpointIn, ctx: OwnerCtx, session: Session):
    ep, secret = await webhooks.create_endpoint(session, ctx.store.id, str(body.url), body.events, body.description, ctx.user.id)
    return {**webhooks.endpoint_out(ep), "secret": secret, "warning": "این secret فقط یک بار نمایش داده می‌شود."}


@router.patch("/stores/{store_id}/reseller/webhooks/{endpoint_id}")
async def patch_webhook(endpoint_id: uuid.UUID, body: WebhookEndpointPatch, ctx: OwnerCtx, session: Session):
    ep = await webhooks.get_endpoint(session, ctx.store.id, endpoint_id)
    ep = await webhooks.update_endpoint(
        session,
        ep,
        url=str(body.url) if body.url else None,
        events=body.events,
        description=body.description,
        status=body.status,
        actor_id=ctx.user.id,
    )
    return webhooks.endpoint_out(ep)


@router.post("/stores/{store_id}/reseller/webhooks/{endpoint_id}/rotate-secret")
async def rotate_webhook_secret(endpoint_id: uuid.UUID, ctx: OwnerCtx, session: Session):
    ep = await webhooks.get_endpoint(session, ctx.store.id, endpoint_id)
    secret = await webhooks.rotate_secret(session, ep, ctx.user.id)
    return {"secret": secret, "warning": "secret قبلی تا ۲۴ ساعت همچنان برای امضای دوم معتبر است."}


@router.delete("/stores/{store_id}/reseller/webhooks/{endpoint_id}")
async def delete_webhook(endpoint_id: uuid.UUID, ctx: OwnerCtx, session: Session):
    ep = await webhooks.get_endpoint(session, ctx.store.id, endpoint_id)
    await webhooks.update_endpoint(session, ep, status="disabled", actor_id=ctx.user.id)
    return {"ok": True}


@router.get("/stores/{store_id}/reseller/webhooks/{endpoint_id}/deliveries")
async def webhook_deliveries(endpoint_id: uuid.UUID, ctx: OwnerCtx, session: Session):
    ep = await webhooks.get_endpoint(session, ctx.store.id, endpoint_id)
    return [webhooks.delivery_out(d) for d in await webhooks.list_deliveries(session, ep.id)]


@router.post("/stores/{store_id}/reseller/webhooks/{endpoint_id}/deliveries/{delivery_id}/redeliver")
async def redeliver(endpoint_id: uuid.UUID, delivery_id: uuid.UUID, ctx: OwnerCtx, session: Session):
    ep = await webhooks.get_endpoint(session, ctx.store.id, endpoint_id)
    await webhooks.redeliver(session, ep, delivery_id, ctx.user.id)
    return {"ok": True}


@router.post("/stores/{store_id}/reseller/webhooks/{endpoint_id}/test")
async def test_webhook(endpoint_id: uuid.UUID, ctx: OwnerCtx, session: Session):
    ep = await webhooks.get_endpoint(session, ctx.store.id, endpoint_id)
    d = await webhooks.enqueue_test(session, ep)
    return {"ok": True, "delivery_id": d.id}


# ---------------- Versioned reseller API ----------------


async def _api_ctx(session, store_id, raw_key, scope):
    cred = await api_keys.authenticate(session, raw_key, store_id=store_id, scope=scope)
    store = await session.get(Store, store_id)
    profile = await session.scalar(select(ResellerProfile).where(ResellerProfile.store_id == store_id))
    if not store or store.kind != "reseller" or not profile or not profile.api_enabled:
        raise AppError("API_DISABLED", "Reseller API برای این فروشگاه فعال نیست.", 403)
    owner = await session.get(User, store.owner_user_id)
    return cred, SimpleNamespace(store=store, user=owner)


api_router = APIRouter(prefix="/reseller-api/v1", tags=["reseller-api"])


@api_router.get("/stores/{store_id}/catalog")
async def api_catalog(store_id: uuid.UUID, session: Session, x_api_key: str = Header(..., alias="X-API-Key")):
    _, ctx = await _api_ctx(session, store_id, x_api_key, "catalog:read")
    rows = await allocation.sellable_products_priced(session, ctx.store)
    own = await allocation.store_bundle_prices(session, ctx.store.id)
    return [
        {
            "product_id": p.id,
            "code": p.code,
            "name": p.name,
            "price": price,
            "currency": ctx.store.currency,
            "duration_days": p.duration_days,
            "traffic_gb": p.traffic_gb,
            "bundle_prices": [{"bundle_id": gid, "price": v} for (gid, pid), v in own.items() if pid == p.id],
        }
        for p, sp, price in rows
    ]


@api_router.get("/stores/{store_id}/customers")
async def api_customers(store_id: uuid.UUID, session: Session, x_api_key: str = Header(..., alias="X-API-Key")):
    _, ctx = await _api_ctx(session, store_id, x_api_key, "customers:read")
    q = (
        select(User, StoreMembership)
        .join(StoreMembership, StoreMembership.user_id == User.id)
        .where(StoreMembership.store_id == ctx.store.id, StoreMembership.role == "customer")
    )
    return [
        CustomerOut(user_id=u.id, display_name=u.display_name, email=u.email, status=m.status, joined_at=m.created_at)
        for u, m in (await session.execute(q)).all()
    ]


@api_router.get("/stores/{store_id}/orders")
async def api_orders(store_id: uuid.UUID, session: Session, x_api_key: str = Header(..., alias="X-API-Key")):
    _, ctx = await _api_ctx(session, store_id, x_api_key, "orders:read")
    rows = (await session.scalars(select(Order).where(Order.store_id == ctx.store.id).order_by(Order.created_at.desc()).limit(200))).all()
    return [
        {
            "id": o.id,
            "number": o.number,
            "user_id": o.user_id,
            "product_id": o.product_id,
            "status": o.status,
            "total": o.total,
            "currency": o.currency,
            "created_at": o.created_at,
        }
        for o in rows
    ]


@api_router.post("/stores/{store_id}/customers/{customer_id}/wallet")
async def api_customer_wallet(
    store_id: uuid.UUID,
    customer_id: uuid.UUID,
    body: CustomerWalletAdjustment,
    session: Session,
    x_api_key: str = Header(..., alias="X-API-Key"),
):
    _, ctx = await _api_ctx(session, store_id, x_api_key, "customers:wallet:write")
    return await adjust_customer_wallet_core(session, ctx, customer_id, body, actor_type="api")


@api_router.get("/stores/{store_id}/reports")
async def api_reports(store_id: uuid.UUID, session: Session, x_api_key: str = Header(..., alias="X-API-Key")):
    _, ctx = await _api_ctx(session, store_id, x_api_key, "reports:read")
    rows = (
        await session.execute(
            select(Order.status, func.count(), func.coalesce(func.sum(Order.total), 0))
            .where(Order.store_id == ctx.store.id)
            .group_by(Order.status)
        )
    ).all()
    return {
        "store_id": ctx.store.id,
        "currency": ctx.store.currency,
        "orders": [{"status": s, "count": n, "total": total} for s, n, total in rows],
    }
