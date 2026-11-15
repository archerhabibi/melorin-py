"""Customer loyalty club - one self-contained club PER STORE (docs/22).

Everything here belongs to ONE store: the program, the ladder, the rewards, every customer's purse and the expense account the
rewards are paid from. Nothing crosses stores, exactly like the referral programme (docs/17). Points are earned when an order
completes and taken back when it is refunded; a refund the customer already spent becomes a points debt recovered from his next
earnings, so a balance never goes negative. Every posting carries an idempotency key, so the outbox can retry safely.

This module is the stable facade: the implementation lives in ``common``, ``tiers``, ``program``, ``rewards``, ``ledger``,
``earning`` (order completed / refunded), ``redemption``, ``adjustments`` and ``summary``. Callers keep importing
``melorin.modules.loyalty.service``.
"""

from melorin.modules.loyalty.common import HISTORY_MAX, _REVERSIBLE, _fail, _json, _now  # noqa: F401
from melorin.modules.loyalty.tiers import load_tiers, ladder, tier_out  # noqa: F401
from melorin.modules.loyalty.program import program_rules, get_program, ensure_program, program_out, upsert_program, replace_tiers  # noqa: F401
from melorin.modules.loyalty.rewards import reward_out, list_rewards, save_reward  # noqa: F401
from melorin.modules.loyalty.ledger import get_account, _find_tx, _post, tx_out, history  # noqa: F401
from melorin.modules.loyalty.earning import _earn, _is_first_order, on_order_completed, _referrer_bonus, _notify_earned, on_order_refunded  # noqa: F401
from melorin.modules.loyalty.redemption import redeem  # noqa: F401
from melorin.modules.loyalty.adjustments import adjust  # noqa: F401
from melorin.modules.loyalty.summary import customer_summary, store_summary  # noqa: F401

__all__ = [
    "HISTORY_MAX",
    "_REVERSIBLE",
    "_fail",
    "_json",
    "_now",
    "load_tiers",
    "ladder",
    "tier_out",
    "program_rules",
    "get_program",
    "ensure_program",
    "program_out",
    "upsert_program",
    "replace_tiers",
    "reward_out",
    "list_rewards",
    "save_reward",
    "get_account",
    "_find_tx",
    "_post",
    "tx_out",
    "history",
    "_earn",
    "_is_first_order",
    "on_order_completed",
    "_referrer_bonus",
    "_notify_earned",
    "on_order_refunded",
    "redeem",
    "adjust",
    "customer_summary",
    "store_summary",
]
