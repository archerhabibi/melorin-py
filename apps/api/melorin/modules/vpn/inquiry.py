"""Account inquiry (استعلام): the ONE place that decides how accounts are searched, scoped and summarised.

Bot, website and the store owner's views all go through it, so the privacy rule is written once:

* a customer only ever sees and searches HIS OWN accounts IN THE STORE HE IS USING (``core.scope.StoreScope`` puts both
  ``user_id`` and ``store_id`` into every query; what he bought in another store or bot is invisible and not renewable here);
* a reseller's LIST shows only the accounts they made themselves in their store; their SEARCH also finds the accounts of
  THEIR OWN store's customers and never another store's accounts (not even their own personal ones from another store);
* the numbers shown (remaining days, usage) come from the panel-synced account row; the bot and website never
  compute their own version of them.
"""

from __future__ import annotations

import datetime as dt
import time
import uuid

from sqlalchemy import and_, case, func, or_, select

from melorin.core import audit
from melorin.core.db import utcnow
from melorin.core.errors import NotFound
from melorin.core.scope import OwnerScope, StoreScope
from melorin.modules.vpn import renewal
from melorin.modules.vpn.models import VpnAccount
from melorin.modules.vpn.schemas import OwnerAccountOut, VpnAccountOut

OWN_LABEL = "اکانت خودتان"
RESELLER_LIST_NOTE = (
    "این فهرست فقط اکانت‌هایی است که خودتان ساخته‌اید. اکانت مشتریان‌تان را با جستجو (نام اکانت، نام یا ایمیل مشتری) پیدا کنید."
)
PAYER_NOTE = "مبلغ از کیف پول صاحب اکانت در همین فروشگاه کسر می‌شود."
MAX_QUERY_LEN = 64
EXPIRING_SOON_DAYS = 3
_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")


def clean_query(q: str | None) -> str | None:
    """Trim, fold Persian/Arabic digits to ASCII, cap the length; ``None`` when nothing searchable is left."""
    if not q:
        return None
    q = q.translate(_DIGITS).strip()[:MAX_QUERY_LEN]
    return q or None


def _like(q: str) -> str:
    return "%" + q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"


def username_clause(q: str):
    return VpnAccount.username.ilike(_like(q), escape="\\")


def owner_clause(q: str, user_model):
    """Store owner search: account username, or the customer's name / email."""
    like = _like(q)
    return or_(
        VpnAccount.username.ilike(like, escape="\\"),
        user_model.display_name.ilike(like, escape="\\"),
        user_model.email.ilike(like, escape="\\"),
    )


def reseller_visible(store_id: uuid.UUID):
    """Search scope of a reseller: every account of THEIR OWN store (his own and his customers'), and nothing outside it."""
    return VpnAccount.store_id == store_id


def days_left(a: VpnAccount, now: dt.datetime | None = None) -> int | None:
    expires = renewal._aware(a.expires_at)
    if expires is None:
        return None
    now = renewal._aware(now) or utcnow()
    return (expires - now).days if expires > now else 0


def usage_percent(a: VpnAccount) -> int | None:
    if not a.traffic_limit_bytes:
        return None  # unlimited
    return min(100, int((a.traffic_used_bytes or 0) * 100 / a.traffic_limit_bytes))


def health(a: VpnAccount, now: dt.datetime | None = None) -> str:
    """One word for list badges: active | expiring | expired | depleted | disabled."""
    now = renewal._aware(now) or utcnow()
    expires = renewal._aware(a.expires_at)
    if expires is not None and expires <= now:
        return "expired"
    if a.traffic_limit_bytes and (a.traffic_used_bytes or 0) >= a.traffic_limit_bytes:
        return "depleted"
    if a.status != "active":
        return "disabled"
    if expires is not None and (expires - now).days < EXPIRING_SOON_DAYS:
        return "expiring"
    return "active"


def account_out(a: VpnAccount, now: dt.datetime | None = None) -> VpnAccountOut:
    state = renewal.eligibility(a, now=now)
    return VpnAccountOut(
        can_renew=state.ok,
        renew_until=state.renew_until,
        id=a.id,
        username=a.username,
        status=a.status,
        is_test=a.is_test,
        expires_at=a.expires_at,
        traffic_limit_bytes=a.traffic_limit_bytes,
        traffic_used_bytes=a.traffic_used_bytes,
        renew_note=None if state.ok else state.message,
        subscription_url=a.subscription_url,
        links=a.links,
        server_id=a.server_id,
        store_id=a.store_id,
        days_left=days_left(a, now),
        usage_percent=usage_percent(a),
        health=health(a, now),
        created_at=a.created_at,
        updated_at=a.updated_at,
    )


def owner_account_out(a: VpnAccount, user, now: dt.datetime | None = None, *, owner_id: uuid.UUID | None = None) -> OwnerAccountOut:
    base = account_out(a, now).model_dump()
    name = user.display_name or user.email
    own = owner_id is not None and a.user_id == owner_id
    return OwnerAccountOut(
        **base, customer_id=a.user_id, customer_name=name, is_own=own, holder_label=OWN_LABEL if own else f"مشتری: {name}"
    )


# ---------------------------------------------------------------- list filters + counters
STATES = ("active", "expiring", "expired")  # the filter chips every channel offers (besides "all")


def state_clause(state: str | None, now: dt.datetime | None = None):
    """SQL twin of :func:`health` for the list filter chips; ``None`` (or an unknown word) means no filter."""
    now = now or utcnow()
    soon = now + dt.timedelta(days=EXPIRING_SOON_DAYS)
    exp = VpnAccount.expires_at
    if state == "expired":
        return and_(exp.is_not(None), exp <= now)
    if state == "expiring":
        return and_(exp.is_not(None), exp > now, exp < soon)
    if state == "active":
        return and_(or_(exp.is_(None), exp > now), VpnAccount.status == "active")
    return None


async def summary(session, *conds) -> dict[str, int]:
    """Counters for the chips (all / active / expiring / expired) over the accounts selected by ``conds``.

    The caller passes the scope (``user_id`` for a customer, ``store_id`` for the owner): this function never widens it.
    """
    now = utcnow()
    cols = [func.count(VpnAccount.id)] + [func.coalesce(func.sum(case((state_clause(st, now), 1), else_=0)), 0) for st in STATES]
    row = (await session.execute(select(*cols).where(*conds))).one()
    return {"total": int(row[0]), **{st: int(v) for st, v in zip(STATES, row[1:], strict=True)}}


# ---------------------------------------------------------------- live data from the panel
REFRESH_TTL_SECONDS = 15.0
_last_refresh: dict[uuid.UUID, float] = {}


async def refresh_from_panel(session, account: VpnAccount) -> bool:
    """Ask the VPN panel for the account's current expiry / usage / links and store them (the panel is the source of truth).

    Rate-limited per account so a tapped button can never hammer a panel; returns ``True`` when the panel was asked now.
    A panel that is down leaves the last synced numbers in place (the reconcile job records the issue).
    """
    if not account.panel_id:
        return False
    now = time.monotonic()
    if now - _last_refresh.get(account.id, -REFRESH_TTL_SECONDS) < REFRESH_TTL_SECONDS:
        return False
    if len(_last_refresh) > 5000:
        _last_refresh.clear()
    _last_refresh[account.id] = now
    from melorin.modules.vpn import service  # lazy: service imports this package's models/renewal

    await service.reconcile(session, account.id)
    await session.refresh(account)
    return True


# ================================================================ the scopes (every channel goes through these)
def _apply(cond: list, *, term: str | None, state: str | None, term_clause) -> None:
    if term:
        cond.append(term_clause(term))
    if (state_cond := state_clause(state)) is not None:
        cond.append(state_cond)


def _customer_conds(scope: StoreScope) -> list:
    return [*scope.where(VpnAccount), VpnAccount.archived_at.is_(None)]


async def customer_accounts(session, scope: StoreScope, *, q=None, state=None, limit=100, offset=0):
    """A customer's list AND search: only HIS OWN accounts IN THIS STORE, whatever the filters are. Returns ``(accounts, total)``."""
    cond = _customer_conds(scope)
    _apply(cond, term=clean_query(q), state=state, term_clause=username_clause)
    total = await session.scalar(select(func.count()).select_from(VpnAccount).where(*cond))
    rows = await session.scalars(select(VpnAccount).where(*cond).order_by(VpnAccount.created_at.desc()).limit(limit).offset(offset))
    return rows.all(), int(total or 0)


async def customer_summary(session, scope: StoreScope) -> dict:
    return await summary(session, *_customer_conds(scope))


async def customer_account(session, scope: StoreScope, account_id: uuid.UUID) -> VpnAccount:
    """One account of this customer in this store (another user's or another store's: 404, like a missing id)."""
    return scope.require(await session.get(VpnAccount, account_id), "اکانت VPN")


async def reseller_accounts(session, owner_id: uuid.UUID, store_id: uuid.UUID, *, q=None, state=None, limit=50, offset=0):
    """A reseller's inquiry. The LIST (no search term) is only the accounts he made himself in his store; a SEARCH also finds
    the accounts of THIS store's customers (never another store's). Returns ``([(account, holder)], total)``."""
    term = clean_query(q)
    scope = OwnerScope(store_id=store_id, owner_id=owner_id)
    cond = [VpnAccount.archived_at.is_(None)]
    cond += [*scope.where(VpnAccount)] if term else [*scope.own(VpnAccount)]
    _apply(cond, term=term, state=state, term_clause=lambda t: owner_clause(t, _user_model()))
    base = select(VpnAccount, _user_model()).join(_user_model(), _user_model().id == VpnAccount.user_id).where(*cond)
    total = await session.scalar(select(func.count()).select_from(base.subquery()))
    rows = (await session.execute(base.order_by(VpnAccount.created_at.desc()).limit(limit).offset(offset))).all()
    return rows, int(total or 0)


async def reseller_summary(session, owner_id: uuid.UUID, store_id: uuid.UUID) -> dict:
    """Chip counters over the reseller's list scope (his OWN accounts in his store) + Core's note explaining that scope."""
    own = OwnerScope(store_id=store_id, owner_id=owner_id).own(VpnAccount)
    return {**await summary(session, *own, VpnAccount.archived_at.is_(None)), "note": RESELLER_LIST_NOTE}


async def reseller_find(session, owner_id: uuid.UUID, store_id: uuid.UUID, account_id: uuid.UUID):
    """One account the reseller may act on: one of THIS store's accounts, his own or a customer's (anything else: 404)."""
    user = _user_model()
    row = (
        await session.execute(
            select(VpnAccount, user)
            .join(user, user.id == VpnAccount.user_id)
            .where(VpnAccount.id == account_id, reseller_visible(store_id))
        )
    ).first()
    if not row:
        raise NotFound("اکانت VPN")
    return row


async def admin_accounts(session, *, q=None, store_id=None, state=None, limit=100, offset=0):
    """The platform owner's inquiry: every store, searchable and paged. Returns ``([(account, holder)], total)``."""
    user = _user_model()
    cond = [VpnAccount.archived_at.is_(None)]
    if store_id:
        cond.append(VpnAccount.store_id == store_id)
    _apply(cond, term=clean_query(q), state=state, term_clause=lambda t: owner_clause(t, user))
    base = select(VpnAccount, user).join(user, user.id == VpnAccount.user_id).where(*cond)
    total = await session.scalar(select(func.count()).select_from(base.subquery()))
    rows = (await session.execute(base.order_by(VpnAccount.updated_at.desc()).limit(limit).offset(offset))).all()
    return rows, int(total or 0)


def _user_model():
    from melorin.modules.identity.models import User  # lazy: identity imports the vpn package

    return User


# ================================================================ renewal by a reseller (own accounts + own customers)
async def _holder_context(session, account: VpnAccount, holder):
    """The holder's own context in the store the account lives in: a renewal then runs through exactly the same core
    rules as one started by the holder himself (ownership, window, package, price, wallet)."""
    from melorin.core.deps import resolve_store_context  # lazy: deps imports models of this package

    return await resolve_store_context(session, account.store_id, holder)


async def reseller_renewal_offer(session, owner_id: uuid.UUID, store_id: uuid.UUID, account_id: uuid.UUID):
    """What renewing this account would be: the answer the holder would get, plus who pays."""
    from melorin.modules.catalog.router import renewal_info  # lazy: catalog imports the vpn package
    from melorin.modules.reseller.schemas import OwnerRenewalOut

    account, holder = await reseller_find(session, owner_id, store_id, account_id)
    offer = (await renewal_info(account.id, await _holder_context(session, account, holder), session)).model_dump()
    return OwnerRenewalOut(**offer, payer_note=None if account.user_id == owner_id else PAYER_NOTE)


async def reseller_renew(session, owner_id: uuid.UUID, store_id: uuid.UUID, account_id: uuid.UUID, *, idempotency_key: str, channel: str):
    """Renew one of the reseller's OWN accounts or one of THIS store's customers' accounts with the account's own package at
    its current price. The order belongs to the account's holder and is paid from the holder's wallet in the store; every
    renewal rule stays in :mod:`renewal` / ``orders.create_order``. Returns the order."""
    from melorin.modules.orders import service as orders  # lazy: orders imports the vpn package

    account, holder = await reseller_find(session, owner_id, store_id, account_id)
    product_id, is_own = account.product_id, account.user_id == owner_id
    order = await orders.create_order(
        session,
        await _holder_context(session, account, holder),
        product_id=product_id,
        idempotency_key=idempotency_key,
        kind="renewal",
        vpn_account_id=account_id,
        channel=channel,
    )
    if not is_own:
        audit.record(
            session,
            "order.renewed_by_owner",
            actor_id=owner_id,
            entity_type="order",
            entity_id=order.id,
            store_id=order.store_id,
            data={"vpn_account_id": str(account_id), "customer_id": str(order.user_id)},
        )
        await session.commit()
    return order
