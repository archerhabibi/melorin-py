"""Order reward policy: the ONE written answer to "how do coupon, referral and loyalty combine on an order".

Rules (architecture review 2026-11-13, section 4.6):
  1. Coupon is a SALE discount. It is already inside ``order.total``; it is never a reward and never stacks as one.
  2. Referral and loyalty both compute from ``order.total`` (the amount actually charged, i.e. AFTER the coupon).
     Neither is computed from the list price, so a coupon can not inflate a reward.
  3. Settlement order is fixed: referral first (attribution + cash commission), loyalty second (points, incl. the
     referrer's loyalty bonus, which reads the relationship referral already established).
  4. Refund reverses in the opposite order: loyalty first, then referral.
  5. Only revenue orders with ``total > 0`` earn anything.
  6. Every grant carries its own idempotency key; re-running a step is a no-op.
"""

from enum import StrEnum


class RewardEngine(StrEnum):
    REFERRAL = "referral"
    LOYALTY = "loyalty"


SETTLE_ORDER: tuple[RewardEngine, ...] = (RewardEngine.REFERRAL, RewardEngine.LOYALTY)
REVERSE_ORDER: tuple[RewardEngine, ...] = tuple(reversed(SETTLE_ORDER))


def reward_base(total: int, *, is_revenue: bool) -> int:
    """The amount rewards are computed from: what the customer paid (coupon already applied); 0 when nothing is earned."""
    if not is_revenue or total <= 0:
        return 0
    return total
