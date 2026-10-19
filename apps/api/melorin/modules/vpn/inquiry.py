"""Account inquiry (استعلام): the ONE place that decides how accounts are searched, scoped and summarised.

Bot, website and the store owner's views all go through it, so the privacy rule is written once:

* a customer only ever sees and searches HIS OWN accounts (``user_id`` is always part of the query);
* the owner of a reseller store sees and searches every account sold in THAT store (``store_id`` is always part of
  the query) and never another store's accounts;
* the numbers shown (remaining days, usage) come from the panel-synced account row; the bot and website never
  compute their own version of them.
"""

from __future__ import annotations

import datetime as dt
import time
import uuid

from sqlalchemy import and_, case, func, or_, select

from melorin.core.db import utcnow
from melorin.modules.vpn import renewal
from melorin.modules.vpn.models import VpnAccount
from melorin.modules.vpn.schemas import OwnerAccountOut, VpnAccountOut

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


def owner_account_out(a: VpnAccount, user, now: dt.datetime | None = None) -> OwnerAccountOut:
    base = account_out(a, now).model_dump()
    return OwnerAccountOut(**base, customer_id=a.user_id, customer_name=user.display_name or user.email)


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
    cols = [func.count(VpnAccount.id)] + [
        func.coalesce(func.sum(case((state_clause(st, now), 1), else_=0)), 0) for st in STATES
    ]
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
