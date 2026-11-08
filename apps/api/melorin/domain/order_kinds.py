"""Order kinds and which of them are *sales*.

``purchase`` and ``renewal`` are real sales. The other two kinds are bookkeeping carriers for a VPN account that was NOT sold
through Melorin: they always have ``total = 0`` and no reseller cost, and they never count anywhere money or rewards are computed.

* ``test``   - a free trial account (per-store quota, ``TestAccountGrant``). Announced in the test-accounts topic.
* ``manual`` - a panel user created by hand on the panel that an admin assigned to a store/customer (PG-04, decision 1).
  The order exists only because ``vpn_accounts.order_id`` is NOT NULL. Rule (decided, not configurable):

  =====================  ==========================================================================
  Sales / revenue         excluded (orders, revenue, wholesale cost, charts, CSV counters)
  Reseller commission     excluded (``reseller_cost`` is NULL: no wholesale debit, nothing to settle)
  Referral reward         excluded (not a purchase, ``total = 0``; also not "store history")
  Loyalty club points     excluded (no points, not a first order, no tier progress)
  Returns / refunds       impossible (nothing was paid; ``kind != purchase``)
  Events / Telegram       silent in the orders topic; one line in the manual-accounts audit trail
  Renewal                 allowed: a renewal is a NEW ``renewal`` order with a real price and counts normally
  =====================  ==========================================================================
"""

from sqlalchemy import ColumnElement

PURCHASE = "purchase"
RENEWAL = "renewal"
TEST = "test"
MANUAL = "manual"

#: kinds that are never a sale: no revenue, no commission, no referral reward, no loyalty points.
NON_REVENUE_KINDS: frozenset[str] = frozenset({TEST, MANUAL})


def is_revenue(kind: str | None) -> bool:
    """True for an order that is a real sale (purchase / renewal)."""
    return (kind or PURCHASE) not in NON_REVENUE_KINDS


def revenue_only(kind_column) -> ColumnElement[bool]:
    """SQL filter: ``Order.kind`` is a real sale. Use ``revenue_only(Order.kind)`` in every sales / reward query."""
    return kind_column.not_in(sorted(NON_REVENUE_KINDS))


def not_manual(kind_column) -> ColumnElement[bool]:
    """SQL filter for plain sales/status reports that always counted test orders (shown as their own kind) but never manual ones."""
    return kind_column != MANUAL
