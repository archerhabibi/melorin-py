"""Commission/reward plans (doc 07 v1.1). Admin chooses a model per plan (product); attribution is first-touch.

Spent-commission recovery (open decision #8, default proposal implemented): a refund always records a
reversal. What the referrer wallet can cover is taken now; the remainder becomes an outstanding clawback
offset from future commissions. The referrer wallet never goes negative because of a reversal.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class Plan:
    kind: str  # signup_reward | commission
    model: str  # fixed | percent
    value: int  # fixed amount, or basis points for percent
    max_amount: int | None = None
    active: bool = True


def amount_for(plan: Plan | None, net_paid: int) -> int:
    if not plan or not plan.active or net_paid <= 0 or plan.value <= 0:
        return 0
    if plan.model == "fixed":
        amt = plan.value
    elif plan.model == "percent":
        amt = net_paid * plan.value // 10_000
    else:
        return 0
    if plan.max_amount is not None:
        amt = min(amt, plan.max_amount)
    return max(0, amt)


def pick_plan(plans: list[tuple[str | None, Plan]], product_id: str, kind: str) -> Plan | None:
    """Product-specific plan wins over the default (product None)."""
    specific = [p for pid, p in plans if pid == product_id and p.kind == kind and p.active]
    if specific:
        return specific[0]
    default = [p for pid, p in plans if pid is None and p.kind == kind and p.active]
    return default[0] if default else None


def split_reversal(amount: int, wallet_balance: int) -> tuple[int, int]:
    """Return (take_now, outstanding)."""
    take = max(0, min(amount, wallet_balance))
    return take, amount - take


def offset_with_outstanding(new_amount: int, outstanding: int) -> tuple[int, int]:
    """Future commission first settles outstanding clawbacks. Return (pay_out, recovered)."""
    recovered = min(new_amount, max(0, outstanding))
    return new_amount - recovered, recovered
