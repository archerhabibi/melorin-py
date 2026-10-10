from dataclasses import asdict, dataclass


class PricingError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(code)
        self.code, self.message = code, message


@dataclass(frozen=True)
class Discount:
    code: str
    percent: int = 0  # 0..100
    fixed: int = 0
    max_amount: int | None = None


@dataclass(frozen=True)
class Quote:
    store_kind: str
    product_id: str
    unit_price: int
    discount: int
    total: int
    reseller_cost: int | None
    currency: str
    coupon_code: str | None
    reseller_currency: str | None = None
    coupon_funded_by: str | None = None

    def snapshot(self) -> dict:
        return asdict(self)


def compute_discount(price: int, d: Discount | None) -> int:
    if not d:
        return 0
    amount = price * d.percent // 100 + d.fixed
    if d.max_amount is not None:
        amount = min(amount, d.max_amount)
    return max(0, min(amount, price))


def quote(
    *,
    store_kind: str,
    product_id: str,
    main_price: int,
    reseller_price: int,
    customer_price: int | None,
    currency: str,
    discount: Discount | None = None,
    reseller_currency: str | None = None,
    platform_funded: bool = False,
) -> Quote:
    """Main store sells at main_price. Reseller store sells at customer_price and costs reseller_price."""
    if store_kind == "main":
        unit, cost = main_price, None
    elif store_kind == "reseller":
        if customer_price is None or customer_price <= 0:
            raise PricingError("PRICE_NOT_SET", "قیمت این محصول توسط نماینده تعیین نشده است.")
        unit, cost = customer_price, reseller_price
    else:
        raise PricingError("BAD_STORE", "نوع فروشگاه نامعتبر است.")
    if unit < 0:
        raise PricingError("BAD_PRICE", "قیمت نامعتبر است.")
    disc = compute_discount(unit, discount)
    if cost is not None and platform_funded and disc:
        # Platform-funded coupon (Admin domain): the reseller's cost shrinks by the same amount.
        if reseller_currency and reseller_currency != currency:
            raise PricingError("CURRENCY_MISMATCH", "کد تخفیف پلتفرم برای فروشگاه با ارز متفاوت قابل استفاده نیست.")
        cost = max(0, cost - disc)
    return Quote(
        store_kind, product_id, unit, disc, unit - disc, cost, currency, discount.code if discount else None,
        reseller_currency if cost is not None else None,
        ("platform" if platform_funded else "store") if discount else None,
    )
