"""Coupon rules (doc 07 v1.1). Pure: validation, scope, quota and discount math live only in Core.

V1 rules:
- creator is Admin or an authorised Reseller; a Reseller only creates coupons for its own Store;
- scope is one Store (scope="store") or an Admin-approved domain of Stores (scope="domain");
- not combinable by default; Core applies exactly one valid coupon;
- discount <= eligible amount and <= max_discount; start/end validity; global and per-customer quota.
"""
import datetime as dt
from dataclasses import dataclass, field


class CouponError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(code)
        self.code, self.message = code, message


@dataclass(frozen=True)
class CouponRule:
    code: str
    status: str = "active"  # active | disabled | archived
    creator_type: str = "admin"  # admin | reseller
    scope: str = "store"  # store | domain
    store_id: str | None = None  # owning store (scope=store)
    allowed_store_ids: tuple[str, ...] = ()  # scope=domain, set by Admin only
    allowed_store_kinds: tuple[str, ...] = ()  # scope=domain, e.g. ("reseller",)
    product_ids: tuple[str, ...] = ()  # empty = every product of the store
    percent_bp: int = 0  # basis points, 10000 = 100%
    fixed: int = 0
    max_discount: int | None = None
    min_amount: int = 0
    starts_at: dt.datetime | None = None
    ends_at: dt.datetime | None = None
    max_redemptions: int | None = None
    per_customer_limit: int | None = 1
    redemptions: int = 0
    currency: str | None = None
    combinable: bool = False


@dataclass(frozen=True)
class CouponUse:
    store_id: str
    store_kind: str
    product_id: str
    amount: int  # eligible amount (customer unit price)
    currency: str
    customer_redemptions: int = 0
    now: dt.datetime = field(default_factory=lambda: dt.datetime.now(dt.UTC))


def in_scope(rule: CouponRule, store_id: str, store_kind: str) -> bool:
    if rule.scope == "store":
        return rule.store_id == store_id
    if rule.scope == "domain":
        if rule.creator_type != "admin":
            return False  # only Admin may define multi-store domains
        return store_id in rule.allowed_store_ids or (bool(rule.allowed_store_kinds) and store_kind in rule.allowed_store_kinds)
    return False


def validate_definition(rule: CouponRule, *, creator_store_id: str | None = None) -> None:
    """Checked when a coupon is created/updated."""
    if not rule.code or len(rule.code) > 50:
        raise CouponError("COUPON_BAD_CODE", "کد تخفیف نامعتبر است.")
    if not 0 <= rule.percent_bp <= 10_000 or rule.fixed < 0:
        raise CouponError("COUPON_BAD_VALUE", "مقدار تخفیف نامعتبر است.")
    if rule.percent_bp == 0 and rule.fixed == 0:
        raise CouponError("COUPON_BAD_VALUE", "تخفیف باید درصدی یا مبلغ ثابت داشته باشد.")
    if rule.max_discount is not None and rule.max_discount <= 0:
        raise CouponError("COUPON_BAD_VALUE", "سقف تخفیف نامعتبر است.")
    if rule.starts_at and rule.ends_at and rule.ends_at <= rule.starts_at:
        raise CouponError("COUPON_BAD_WINDOW", "بازه اعتبار نامعتبر است.")
    if rule.max_redemptions is not None and rule.max_redemptions <= 0:
        raise CouponError("COUPON_BAD_QUOTA", "سقف مصرف نامعتبر است.")
    if rule.per_customer_limit is not None and rule.per_customer_limit <= 0:
        raise CouponError("COUPON_BAD_QUOTA", "سقف مصرف هر مشتری نامعتبر است.")
    if rule.combinable:
        raise CouponError("COUPON_COMBINABLE_UNSUPPORTED", "ترکیب کدهای تخفیف در V1 مجاز نیست.")
    if rule.creator_type == "reseller":
        if rule.scope != "store" or not creator_store_id or rule.store_id != creator_store_id:
            raise CouponError("COUPON_SCOPE_FORBIDDEN", "نماینده فقط برای فروشگاه خودش کد تخفیف می‌سازد.")
    if rule.scope == "store" and not rule.store_id:
        raise CouponError("COUPON_SCOPE_FORBIDDEN", "فروشگاه کد تخفیف مشخص نیست.")
    if rule.scope == "domain" and not (rule.allowed_store_ids or rule.allowed_store_kinds):
        raise CouponError("COUPON_SCOPE_FORBIDDEN", "دامنه مجاز کد تخفیف خالی است.")


def _aware(d: dt.datetime | None) -> dt.datetime | None:
    if d is None:
        return None
    return d if d.tzinfo else d.replace(tzinfo=dt.UTC)


def evaluate(rule: CouponRule, use: CouponUse) -> int:
    """Return discount amount or raise CouponError. Never trusts any amount sent by a channel."""
    if rule.status != "active":
        raise CouponError("COUPON_INVALID", "کد تخفیف معتبر نیست.")
    if not in_scope(rule, use.store_id, use.store_kind):
        raise CouponError("COUPON_INVALID", "کد تخفیف معتبر نیست.")
    now = _aware(use.now)
    if rule.starts_at and now < _aware(rule.starts_at):
        raise CouponError("COUPON_NOT_STARTED", "زمان استفاده از این کد تخفیف هنوز نرسیده است.")
    if rule.ends_at and now >= _aware(rule.ends_at):
        raise CouponError("COUPON_EXPIRED", "کد تخفیف منقضی شده است.")
    if rule.product_ids and use.product_id not in rule.product_ids:
        raise CouponError("COUPON_NOT_APPLICABLE", "این کد تخفیف برای این محصول نیست.")
    if rule.currency and rule.currency != use.currency:
        raise CouponError("COUPON_NOT_APPLICABLE", "واحد پول کد تخفیف با فروشگاه یکسان نیست.")
    if use.amount < rule.min_amount:
        raise CouponError("COUPON_MIN_AMOUNT", "مبلغ خرید برای این کد تخفیف کافی نیست.")
    if rule.max_redemptions is not None and rule.redemptions >= rule.max_redemptions:
        raise CouponError("COUPON_EXHAUSTED", "ظرفیت این کد تخفیف تمام شده است.")
    if rule.per_customer_limit is not None and use.customer_redemptions >= rule.per_customer_limit:
        raise CouponError("COUPON_CUSTOMER_LIMIT", "سقف استفاده شما از این کد تخفیف پر شده است.")
    return discount_amount(rule, use.amount)


def discount_amount(rule: CouponRule, eligible: int) -> int:
    if eligible <= 0:
        return 0
    amount = eligible * rule.percent_bp // 10_000 + rule.fixed
    if rule.max_discount is not None:
        amount = min(amount, rule.max_discount)
    return max(0, min(amount, eligible))


def pick_one(codes: list[str]) -> str | None:
    """V1: coupons are not combinable. More than one distinct code is a client error."""
    uniq = {c.strip().upper() for c in codes if c and c.strip()}
    if len(uniq) > 1:
        raise CouponError("COUPON_NOT_COMBINABLE", "در هر خرید فقط یک کد تخفیف قابل استفاده است.")
    return next(iter(uniq), None)
