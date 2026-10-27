"""Commission/reward plans (doc 07 v1.1). Admin chooses a model per plan (product); attribution is first-touch.

Spent-commission recovery (open decision #8, default proposal implemented): a refund always records a
reversal. What the referrer wallet can cover is taken now; the remainder becomes an outstanding clawback
offset from future commissions. The referrer wallet never goes negative because of a reversal.
"""

from collections.abc import Callable
from dataclasses import dataclass

KINDS = ("signup_reward", "commission")
MODELS = ("fixed", "percent")
MAX_PERCENT_BP = 10_000  # 100 %: a plan never pays out more than the order's net amount


class PlanError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(code)
        self.code, self.message = code, message


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


# Definition rules, checked in order; the first violated rule wins: ``(is_violated(plan), error_code, message)``.
_PlanRule = tuple[Callable[[Plan], bool], str, str]

_PLAN_RULES: tuple[_PlanRule, ...] = (
    (lambda p: p.kind not in KINDS, "REFERRAL_BAD_KIND", "نوع طرح نامعتبر است."),
    (lambda p: p.model not in MODELS, "REFERRAL_BAD_MODEL", "مدل طرح باید ثابت یا درصدی باشد."),
    (lambda p: p.value < 0, "REFERRAL_BAD_VALUE", "مقدار طرح نامعتبر است."),
    (
        lambda p: p.model == "percent" and p.value > MAX_PERCENT_BP,
        "REFERRAL_BAD_VALUE",
        "درصد پاداش نمی‌تواند بیشتر از ۱۰۰٪ باشد.",
    ),
    (lambda p: p.max_amount is not None and p.max_amount <= 0, "REFERRAL_BAD_CAP", "سقف پاداش نامعتبر است."),
)


def validate_plan(plan: Plan) -> None:
    """Checked when a plan is created/updated (by Admin for any store, or by a reseller for its own store)."""
    for is_violated, code, message in _PLAN_RULES:
        if is_violated(plan):
            raise PlanError(code, message)
