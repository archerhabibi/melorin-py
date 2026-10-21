"""Renewal (تمدید): the ONE place that decides what a renewal is. Bot, website and worker all go through it.

Rules (business):

* Only an account that exists, belongs to the buyer in this store, is not a test account and is not revoked/archived
  can be renewed, and only until ``GRACE_DAYS`` (10) days after its expiry date. After that a new account must be bought.
* A renewal behaves exactly like the package the account was created from: after it the account shows the package's
  own time and volume (``now + duration_days`` and ``traffic_gb`` of unused volume). Nothing is added to what was
  left; the traffic counter starts again from zero. Because the result is absolute, a retried renewal is idempotent.
* The customer pays the package's CURRENT price inside the bundle the account was originally sold through (the
  bundle/price decision stays in ``allocation.plan_sale``; a renewal never picks another bundle, panel or package).
"""

from __future__ import annotations

import dataclasses
import datetime as dt
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from melorin.core.db import utcnow
from melorin.core.errors import AppError
from melorin.domain.order_state import OrderStatus, VpnStatus

GRACE_DAYS = 10
GIB = 1024**3

_NOT_RENEWABLE_STATUSES = (VpnStatus.REVOKED, VpnStatus.ARCHIVED, VpnStatus.PENDING, VpnStatus.PROVISIONING)
# An order in one of these states is finished: it no longer blocks a new renewal of the same account.
_FINISHED_ORDER_STATUSES = (OrderStatus.COMPLETED, OrderStatus.CANCELLED, OrderStatus.REFUNDED, OrderStatus.PAYMENT_FAILED)


def _aware(d: dt.datetime | None) -> dt.datetime | None:
    """SQLite hands back naive datetimes, PostgreSQL aware ones: compare everything in UTC."""
    if d is None:
        return None
    return d if d.tzinfo else d.replace(tzinfo=dt.UTC)


@dataclasses.dataclass(frozen=True)
class Eligibility:
    ok: bool
    code: str | None = None
    message: str | None = None
    renew_until: dt.datetime | None = None  # last moment a renewal is accepted (None = account has no expiry)

    def raise_if_not_ok(self) -> None:
        if not self.ok:
            raise AppError(self.code or "ACCOUNT_NOT_RENEWABLE", self.message or "این اکانت قابل تمدید نیست.", 409)


def eligibility(account, *, now: dt.datetime | None = None) -> Eligibility:
    """Pure rule: may ``account`` be renewed right now? (Ownership/store checks belong to the caller.)"""
    now = _aware(now) or utcnow()
    expires = _aware(account.expires_at)
    until = expires + dt.timedelta(days=GRACE_DAYS) if expires else None
    if account.is_test:
        return Eligibility(False, "ACCOUNT_NOT_RENEWABLE", "اکانت تست قابل تمدید نیست.", until)
    if account.status in _NOT_RENEWABLE_STATUSES or getattr(account, "archived_at", None) is not None:
        return Eligibility(False, "ACCOUNT_NOT_RENEWABLE", "این اکانت قابل تمدید نیست.", until)
    if until is not None and now > until:
        return Eligibility(
            False,
            "RENEWAL_WINDOW_PASSED",
            f"مهلت تمدید این اکانت ({GRACE_DAYS} روز پس از انقضا) تمام شده است؛ لطفاً اکانت جدید تهیه کنید.",
            until,
        )
    return Eligibility(True, renew_until=until)


@dataclasses.dataclass(frozen=True)
class Target:
    """What the account must look like after the renewal (identical to a freshly created account of the package)."""

    expires_at: dt.datetime
    traffic_bytes: int  # 0 = unlimited
    duration_days: int
    traffic_gb: int


def target(product, *, now: dt.datetime | None = None) -> Target:
    now = _aware(now) or utcnow()
    gb = int(product.traffic_gb or 0)
    return Target(now + dt.timedelta(days=product.duration_days), gb * GIB, int(product.duration_days), gb)


async def has_open_renewal(session: AsyncSession, account_id: uuid.UUID) -> bool:
    from melorin.kernel.models.orders import Order

    return (
        await session.scalar(
            select(Order.id)
            .where(Order.vpn_account_id == account_id, Order.kind == "renewal", Order.status.not_in(_FINISHED_ORDER_STATUSES))
            .limit(1)
        )
    ) is not None


async def check_renewable(session: AsyncSession, account, *, user_id, store_id, now: dt.datetime | None = None) -> Eligibility:
    """Everything the core checks before it takes money for a renewal. Raises ``AppError`` (409) with a Persian message."""
    if account is None or account.user_id != user_id or account.store_id != store_id:
        raise AppError("ACCOUNT_NOT_RENEWABLE", "این اکانت قابل تمدید نیست.", 409)
    state = eligibility(account, now=now)
    state.raise_if_not_ok()
    if await has_open_renewal(session, account.id):
        raise AppError("RENEWAL_IN_PROGRESS", "یک تمدید برای این اکانت در حال انجام است؛ چند لحظه بعد دوباره بررسی کنید.", 409)
    return state


def describe(account, product, *, now: dt.datetime | None = None) -> dict:
    """The promise shown on every channel before payment: what the account will be after renewal."""
    now = _aware(now) or utcnow()
    t = target(product, now=now)
    expires = _aware(account.expires_at)
    left = max(0, (expires - now).days) if expires and expires > now else 0
    return {
        "new_expires_at": t.expires_at,
        "duration_days": t.duration_days,
        "traffic_gb": t.traffic_gb,  # 0 = unlimited
        "current_expires_at": expires,
        "remaining_days_replaced": left,  # days still left now: the renewal restarts the package, it does not add to them
        "renew_until": eligibility(account, now=now).renew_until,
    }


async def apply_to_panel(adapter, account, product, *, now: dt.datetime | None = None):
    """Make the panel account equal to the package: new expiry, package volume, usage back to zero.

    Safe to repeat (absolute values only). Returns the panel's view of the account afterwards.
    """
    t = target(product, now=now)
    pa = await adapter.extend_account(account.username, expire_at=t.expires_at, traffic_bytes=t.traffic_bytes)
    used = int(getattr(pa, "traffic_used_bytes", 0) or 0)
    if used:
        reset = getattr(adapter, "reset_traffic", None)
        if callable(reset):
            pa = await reset(account.username)
        elif t.traffic_bytes:
            # Panel cannot reset usage: raise the limit by what was already used, so the customer still gets the full package.
            pa = await adapter.extend_account(account.username, expire_at=t.expires_at, traffic_bytes=used + t.traffic_bytes)
    return pa


def landed(remote, product, *, now: dt.datetime | None = None) -> bool:
    """Does the panel's account already look renewed? Used to settle a timed-out renewal call without paying twice."""
    t = target(product, now=now)
    exp = _aware(getattr(remote, "expire_at", None))
    if exp is None or exp < t.expires_at - dt.timedelta(minutes=5):
        return False
    limit, used = int(remote.traffic_limit_bytes or 0), int(remote.traffic_used_bytes or 0)
    return limit == t.traffic_bytes or (t.traffic_bytes > 0 and limit - used == t.traffic_bytes)
