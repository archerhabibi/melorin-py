"""Account return (مرجوعی): the ONE place that decides whether a purchased account may be returned, and does it.

Business rules (owner's words, enforced here and nowhere else; bot and website only show Core's answer):

* only a VOLUME account can be returned; unlimited accounts are NOT returnable for now;
* within ``RETURN_MAX_DAYS`` (3) days of the purchase, and at most ``RETURN_MAX_USAGE_PERCENT`` (5 %) of the account's
  volume used (the usage is re-read from the VPN panel first, so it is live);
* at most ``RETURN_DAILY_LIMIT`` (3) returns per customer in any rolling 24 hours;
* the account must be a normal paid purchase that is still unrenewed (a renewal makes the original order impossible to
  take back on its own); test, revoked and archived accounts cannot be returned;
* the customer sees and returns ONLY his own accounts of the store he is using (``core.scope.StoreScope``).

A return is a normal order refund (money back to the customer's wallet of this store, the reseller's cost reversed, the
referral reward reversed, the account revoked in the panel) plus one ``account_returns`` row for the audit trail and the
daily counter.

Layering: this module sits in the ``vpn`` layer, which may not import ``orders``. It therefore only DECIDES (``prepare_return``
validates and stages the audit row); the refund itself is executed by ``melorin.modules.orders.service.account_return``.
"""

from __future__ import annotations

import dataclasses
import datetime as dt
import uuid

from sqlalchemy import func, select

from melorin.core.db import utcnow
from melorin.core.errors import AppError, NotFound
from melorin.core.scope import StoreScope
from melorin.domain.order_state import OrderStatus, VpnStatus
from melorin.kernel.models.identity import User
from melorin.kernel.models.orders import Order
from melorin.kernel.models.vpn import AccountReturn, VpnAccount
from melorin.modules.vpn import inquiry
from melorin.modules.vpn.renewal import _aware

RETURN_MAX_DAYS = 3
RETURN_MAX_USAGE_PERCENT = 5
RETURN_DAILY_LIMIT = 3
RULES_TEXT = (
    f"شرایط مرجوعی: فقط اکانت‌های حجمی؛ حداکثر {RETURN_MAX_DAYS} روز از زمان خرید و حداکثر {RETURN_MAX_USAGE_PERCENT} درصد حجم مصرف‌شده؛ "
    f"اکانت‌های نامحدود فعلاً قابل مرجوع نیستند؛ حداکثر {RETURN_DAILY_LIMIT} مرجوعی در روز. مبلغ به کیف پول همین فروشگاه برمی‌گردد."
)
# A renewal order in one of these states no longer counts against the account.
_DEAD_ORDER = (OrderStatus.CANCELLED, OrderStatus.REFUNDED, OrderStatus.PAYMENT_FAILED)


@dataclasses.dataclass(frozen=True)
class Eligibility:
    ok: bool
    code: str | None = None
    message: str | None = None

    def raise_if_not_ok(self) -> None:
        if not self.ok:
            raise AppError(self.code or "ACCOUNT_NOT_RETURNABLE", self.message or "این اکانت قابل مرجوع نیست.", 409)


def _no(code: str, message: str) -> Eligibility:
    return Eligibility(False, code, message)


def evaluate(
    account: VpnAccount,
    order: Order | None,
    *,
    renewed: bool,
    returns_last_day: int,
    now: dt.datetime | None = None,
) -> Eligibility:
    """Pure rule: may ``account`` (bought with ``order``) be returned right now? Ownership/store checks belong to the caller."""
    now = _aware(now) or utcnow()
    if account.is_test:
        return _no("ACCOUNT_NOT_RETURNABLE", "اکانت تست قابل مرجوع نیست.")
    if account.status in (VpnStatus.REVOKED, VpnStatus.ARCHIVED) or account.archived_at is not None:
        return _no("ACCOUNT_NOT_RETURNABLE", "این اکانت قابل مرجوع نیست.")
    if order is None or order.kind != "purchase" or order.status != OrderStatus.COMPLETED or (order.total or 0) <= 0:
        return _no("ACCOUNT_NOT_RETURNABLE", "این اکانت قابل مرجوع نیست.")
    limit = int(account.traffic_limit_bytes or 0)
    if limit <= 0:
        return _no("RETURN_UNLIMITED", "اکانت‌های نامحدود فعلاً قابل مرجوع نیستند.")
    if renewed:
        return _no("RETURN_RENEWED", "اکانتی که تمدید شده قابل مرجوع نیست.")
    bought = _aware(order.paid_at) or _aware(order.created_at) or _aware(account.created_at)
    if bought is not None and now - bought > dt.timedelta(days=RETURN_MAX_DAYS):
        return _no("RETURN_TOO_OLD", f"مهلت مرجوعی ({RETURN_MAX_DAYS} روز از زمان خرید) تمام شده است.")
    if int(account.traffic_used_bytes or 0) * 100 > limit * RETURN_MAX_USAGE_PERCENT:
        return _no("RETURN_TOO_MUCH_USED", f"بیش از {RETURN_MAX_USAGE_PERCENT} درصد حجم این اکانت مصرف شده و قابل مرجوع نیست.")
    if returns_last_day >= RETURN_DAILY_LIMIT:
        return _no("RETURN_DAILY_LIMIT", f"سقف مرجوعی ({RETURN_DAILY_LIMIT} مورد در روز) پر شده است؛ بعداً دوباره تلاش کنید.")
    return Eligibility(True)


async def _returns_last_day(session, user_id: uuid.UUID, now: dt.datetime) -> int:
    since = now - dt.timedelta(days=1)
    return int(
        await session.scalar(
            select(func.count()).select_from(AccountReturn).where(AccountReturn.user_id == user_id, AccountReturn.created_at >= since)
        )
        or 0
    )


async def eligibility_for(session, scope: StoreScope, accounts: list[VpnAccount]) -> dict[uuid.UUID, Eligibility]:
    """Eligibility of a page of the customer's accounts (three small queries, no per-account round trip)."""
    if not accounts:
        return {}
    now = utcnow()
    ids = [a.id for a in accounts]
    orders = {o.id: o for o in await session.scalars(select(Order).where(Order.id.in_([a.order_id for a in accounts])))}
    renewed = set(
        await session.scalars(
            select(Order.vpn_account_id).where(Order.vpn_account_id.in_(ids), Order.kind == "renewal", Order.status.not_in(_DEAD_ORDER))
        )
    )
    used_today = await _returns_last_day(session, scope.user_id, now)
    return {a.id: evaluate(a, orders.get(a.order_id), renewed=a.id in renewed, returns_last_day=used_today, now=now) for a in accounts}


def account_view(account: VpnAccount, elig: Eligibility | None):
    """``VpnAccountOut`` with the return fields filled from ``elig`` (``None`` leaves them closed)."""
    out = inquiry.account_out(account)
    if elig is not None:
        out.can_return, out.return_note = elig.ok, None if elig.ok else elig.message
    return out


async def prepare_return(session, scope: StoreScope, account_id: uuid.UUID) -> tuple[VpnAccount, Order]:
    """Lock and validate the customer's own account of THIS store and stage its ``AccountReturn`` audit row.

    Raises a 409 ``AppError`` with Core's words when the return is not allowed. The caller (orders layer) performs the refund,
    which commits the staged row together with the money movement.
    """
    account = await scope.lock(session, VpnAccount, account_id)  # row lock; other users'/stores' ids are never touched
    if account is None:
        raise NotFound("اکانت VPN")
    # the daily limit is counted under a lock on the user row, so parallel taps cannot jump over it
    await session.scalar(select(User.id).where(User.id == scope.user_id).with_for_update())
    # live usage from the panel (rate-limited per account); a panel that is down keeps the last synced numbers
    await inquiry.refresh_from_panel(session, account)
    now = utcnow()
    order = await session.get(Order, account.order_id, with_for_update=True, populate_existing=True)
    if order is not None and not scope.owns(order):
        order = None
    renewed = bool(
        await session.scalar(
            select(func.count())
            .select_from(Order)
            .where(Order.vpn_account_id == account.id, Order.kind == "renewal", Order.status.not_in(_DEAD_ORDER))
        )
    )
    evaluate(
        account, order, renewed=renewed, returns_last_day=await _returns_last_day(session, scope.user_id, now), now=now
    ).raise_if_not_ok()
    assert order is not None  # evaluate() refuses a missing order
    session.add(
        AccountReturn(
            user_id=scope.user_id,
            store_id=scope.store_id,
            order_id=order.id,
            vpn_account_id=account.id,
            used_bytes=int(account.traffic_used_bytes or 0),
            limit_bytes=int(account.traffic_limit_bytes or 0),
            amount=int(order.total),
        )
    )
    return account, order
