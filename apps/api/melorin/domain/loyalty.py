"""Customer loyalty club rules (docs/22). Pure: no database, no I/O, imports nothing of ours.

One club per store. A customer earns points on what he really paid (net of discount) for a completed order, a tier (decided by
the points he has EARNED over his lifetime, never by what he spent) multiplies the points of later orders, and points are spent
on rewards. A refund takes the points of that order back; what the customer already spent becomes a points debt that is recovered
from his future earnings, so a balance never goes negative (the same recovery rule the referral commissions use).
"""

from collections.abc import Callable
from dataclasses import dataclass

REWARD_KINDS = ("wallet_credit",)
EARN_KINDS = ("order_earn", "first_order_bonus", "referral_bonus", "admin_grant")  # points that raise the lifetime total
BASE_MULTIPLIER_BP = 10_000  # 1.0x
MAX_MULTIPLIER_BP = 50_000  # a tier never pays more than 5x
MAX_TIERS = 10
MAX_NAME = 64


class LoyaltyError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(code)
        self.code, self.message = code, message


@dataclass(frozen=True)
class Tier:
    name: str
    min_points: int  # lifetime earned points needed to reach the tier
    multiplier_bp: int = BASE_MULTIPLIER_BP


@dataclass(frozen=True)
class Program:
    earn_unit: int  # currency units that make one earning step (e.g. 1000)
    points_per_unit: int  # points granted per full step
    max_points_per_order: int | None = None
    first_order_bonus: int = 0
    referral_bonus: int = 0  # points the REFERRER gets when his invited friend completes the first order in this store


@dataclass(frozen=True)
class Reward:
    kind: str
    value: int  # currency amount credited to the wallet
    cost_points: int
    stock: int | None = None  # None = unlimited
    redeemed: int = 0
    per_user_limit: int | None = None
    active: bool = True


DEFAULT_TIERS: tuple[Tier, ...] = (
    Tier("برنزی", 0, 10_000),
    Tier("نقره‌ای", 500, 11_000),
    Tier("طلایی", 2_000, 12_500),
    Tier("الماسی", 5_000, 15_000),
)


# ---------------------------------------------------------------- tiers
def sort_tiers(tiers: list[Tier] | tuple[Tier, ...]) -> list[Tier]:
    return sorted(tiers, key=lambda t: t.min_points)


def tier_for(tiers: list[Tier] | tuple[Tier, ...], lifetime_earned: int) -> Tier | None:
    """The highest tier whose threshold the customer has reached (None when the store defines no tiers)."""
    reached = [t for t in sort_tiers(tiers) if t.min_points <= max(0, lifetime_earned)]
    return reached[-1] if reached else None


def next_tier(tiers: list[Tier] | tuple[Tier, ...], lifetime_earned: int) -> tuple[Tier | None, int]:
    """(the tier above the current one, points still missing to reach it). (None, 0) at the top."""
    for t in sort_tiers(tiers):
        if t.min_points > max(0, lifetime_earned):
            return t, t.min_points - max(0, lifetime_earned)
    return None, 0


def multiplier_for(tiers: list[Tier] | tuple[Tier, ...], lifetime_earned: int) -> int:
    t = tier_for(tiers, lifetime_earned)
    return t.multiplier_bp if t else BASE_MULTIPLIER_BP


# ---------------------------------------------------------------- earning
def order_points(net_paid: int, program: Program, multiplier_bp: int = BASE_MULTIPLIER_BP) -> int:
    """Points for ONE order: full earning steps of the net paid amount, times the tier multiplier, floored, then capped."""
    if net_paid <= 0 or program.earn_unit <= 0 or program.points_per_unit <= 0:
        return 0
    base = (net_paid // program.earn_unit) * program.points_per_unit
    points = base * max(0, multiplier_bp) // BASE_MULTIPLIER_BP
    if program.max_points_per_order is not None:
        points = min(points, program.max_points_per_order)
    return max(0, points)


def offset_with_debt(new_points: int, debt: int) -> tuple[int, int]:
    """Future earnings settle the outstanding points debt first. Return (credited, recovered)."""
    recovered = min(new_points, max(0, debt))
    return new_points - recovered, recovered


def split_reversal(amount: int, balance: int) -> tuple[int, int]:
    """Return (take_now, owed): what the balance can cover now, and the rest that becomes a points debt."""
    take = max(0, min(amount, balance))
    return take, amount - take


# ---------------------------------------------------------------- redeeming
def check_redeem(reward: Reward, balance: int, user_redeemed: int) -> None:
    """Raise the first violated rule; a reward the customer cannot take now never reaches the ledger."""
    if not reward.active:
        raise LoyaltyError("LOYALTY_REWARD_INACTIVE", "این جایزه فعال نیست.")
    if reward.stock is not None and reward.redeemed >= reward.stock:
        raise LoyaltyError("LOYALTY_REWARD_SOLD_OUT", "موجودی این جایزه تمام شده است.")
    if reward.per_user_limit is not None and user_redeemed >= reward.per_user_limit:
        raise LoyaltyError("LOYALTY_REWARD_LIMIT", "سقف دریافت این جایزه برای شما پر شده است.")
    if balance < reward.cost_points:
        raise LoyaltyError("LOYALTY_NOT_ENOUGH_POINTS", "امتیاز شما برای این جایزه کافی نیست.")


# ---------------------------------------------------------------- definition rules (admin / owner input)
_TierRule = tuple[Callable[[Tier], bool], str, str]

_TIER_RULES: tuple[_TierRule, ...] = (
    (lambda t: not t.name.strip() or len(t.name) > MAX_NAME, "LOYALTY_BAD_TIER_NAME", "نام سطح نامعتبر است."),
    (lambda t: t.min_points < 0, "LOYALTY_BAD_TIER_POINTS", "حداقل امتیاز سطح نامعتبر است."),
    (
        lambda t: not BASE_MULTIPLIER_BP <= t.multiplier_bp <= MAX_MULTIPLIER_BP,
        "LOYALTY_BAD_MULTIPLIER",
        "ضریب امتیاز باید بین ۱ تا ۵ برابر باشد.",
    ),
)


def validate_tiers(tiers: list[Tier]) -> None:
    """The ladder starts at 0 (everybody has a tier), thresholds strictly rise, names are unique."""
    if not tiers:
        raise LoyaltyError("LOYALTY_NO_TIERS", "حداقل یک سطح لازم است.")
    if len(tiers) > MAX_TIERS:
        raise LoyaltyError("LOYALTY_TOO_MANY_TIERS", f"حداکثر {MAX_TIERS} سطح مجاز است.")
    for tier in tiers:
        for is_violated, code, message in _TIER_RULES:
            if is_violated(tier):
                raise LoyaltyError(code, message)
    ordered = sort_tiers(tiers)
    if ordered[0].min_points != 0:
        raise LoyaltyError("LOYALTY_TIERS_START", "اولین سطح باید از صفر امتیاز شروع شود.")
    if len({t.min_points for t in ordered}) != len(ordered):
        raise LoyaltyError("LOYALTY_TIERS_DUPLICATE", "آستانهٔ امتیاز دو سطح نمی‌تواند یکسان باشد.")
    if len({t.name.strip() for t in ordered}) != len(ordered):
        raise LoyaltyError("LOYALTY_TIERS_NAME", "نام سطح‌ها باید یکتا باشد.")
    if any(b.multiplier_bp < a.multiplier_bp for a, b in zip(ordered, ordered[1:], strict=False)):
        raise LoyaltyError("LOYALTY_TIERS_MULTIPLIER", "ضریب سطح بالاتر نباید از سطح پایین‌تر کمتر باشد.")


_ProgramRule = tuple[Callable[[Program], bool], str, str]

_PROGRAM_RULES: tuple[_ProgramRule, ...] = (
    (lambda p: p.earn_unit <= 0, "LOYALTY_BAD_EARN_UNIT", "مبلغ هر مرحلهٔ امتیاز باید بیشتر از صفر باشد."),
    (lambda p: p.points_per_unit <= 0, "LOYALTY_BAD_POINTS", "امتیاز هر مرحله باید بیشتر از صفر باشد."),
    (lambda p: p.first_order_bonus < 0 or p.referral_bonus < 0, "LOYALTY_BAD_BONUS", "امتیاز پاداش نمی‌تواند منفی باشد."),
    (lambda p: p.max_points_per_order is not None and p.max_points_per_order <= 0, "LOYALTY_BAD_CAP", "سقف امتیاز هر سفارش نامعتبر است."),
)


def validate_program(program: Program) -> None:
    for is_violated, code, message in _PROGRAM_RULES:
        if is_violated(program):
            raise LoyaltyError(code, message)


_RewardRule = tuple[Callable[[Reward], bool], str, str]

_REWARD_RULES: tuple[_RewardRule, ...] = (
    (lambda r: r.kind not in REWARD_KINDS, "LOYALTY_BAD_REWARD_KIND", "نوع جایزه نامعتبر است."),
    (lambda r: r.value <= 0, "LOYALTY_BAD_REWARD_VALUE", "ارزش جایزه باید بیشتر از صفر باشد."),
    (lambda r: r.cost_points <= 0, "LOYALTY_BAD_REWARD_COST", "هزینهٔ امتیازی جایزه باید بیشتر از صفر باشد."),
    (lambda r: r.stock is not None and r.stock < 0, "LOYALTY_BAD_REWARD_STOCK", "موجودی جایزه نامعتبر است."),
    (lambda r: r.per_user_limit is not None and r.per_user_limit <= 0, "LOYALTY_BAD_REWARD_LIMIT", "سقف دریافت هر کاربر نامعتبر است."),
)


def validate_reward(reward: Reward) -> None:
    for is_violated, code, message in _REWARD_RULES:
        if is_violated(reward):
            raise LoyaltyError(code, message)
