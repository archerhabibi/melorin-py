"""Referral attribution and configurable commission plans - one self-contained program PER STORE.

Everything here belongs to ONE store (the main store or one reseller's shop/bot): the referral link, the attribution, the
plan that decides the amount, the wallet the reward lands in and the expense account it is paid from. Nothing crosses stores
(docs/17). Attribution is first-touch inside the store: once a relationship exists there it is never replaced. Plans are
managed by Admin for any store, and by the reseller for his own store. Refunds always create a reversal; if the referrer
spent the reward, the uncovered amount becomes a clawback offset against future commissions of the same store.

The implementation lives in ``attach``, ``commissions``, ``rules``; this module stays the stable import surface.
"""

from melorin.modules.referral.attach import _MAX_CHAIN_DEPTH, _closes_a_loop, attach, has_store_history, is_store_member  # noqa: F401
from melorin.modules.referral.commissions import _plan, earnings, on_order_completed, on_order_refunded, store_summary  # noqa: F401
from melorin.modules.referral.rules import _audit_view, _check_product, list_rules, program_for, rule_out, upsert_rule  # noqa: F401

__all__ = [
    "is_store_member",
    "has_store_history",
    "_MAX_CHAIN_DEPTH",
    "_closes_a_loop",
    "attach",
    "_plan",
    "on_order_completed",
    "on_order_refunded",
    "earnings",
    "store_summary",
    "rule_out",
    "_audit_view",
    "list_rules",
    "_check_product",
    "upsert_rule",
    "program_for",
]
