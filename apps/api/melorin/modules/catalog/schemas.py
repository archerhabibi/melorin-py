import datetime as dt
import uuid
from typing import Literal

from pydantic import BaseModel, Field
from melorin.core.limits import MAX_COUNT, MAX_MONEY


class CatalogItem(BaseModel):
    product_id: uuid.UUID
    code: str
    name: str
    description: str | None
    category: str | None
    duration_days: int
    traffic_gb: int
    max_devices: int | None
    price: int
    currency: str


class QuoteRequest(BaseModel):
    product_id: uuid.UUID
    coupon_code: str | None = Field(default=None, max_length=50)
    bundle_id: uuid.UUID | None = None  # the bundle the customer picked (UI: بسته فروش)
    selected_panel_id: uuid.UUID | None = None  # manual bundles only
    vpn_account_id: uuid.UUID | None = None  # renewal: price comes from the bundle the account was sold through
    renewal_mode: str = Field(default="replace", pattern="^(replace|queue)$")  # PG-09: restart now, or prepay the next package


class BundlePanelOut(BaseModel):
    id: uuid.UUID
    label: str


class BundleOut(BaseModel):
    id: uuid.UUID
    name: str
    kind_label: str
    selection_mode: str
    naming_mode: str
    panels: list[BundlePanelOut]  # filled only for manual bundles: what the customer may choose between


class RenewalAfter(BaseModel):
    """What the account will be once the renewal is done (the same as a new account of the package)."""

    new_expires_at: dt.datetime
    duration_days: int
    traffic_gb: int  # 0 = unlimited
    current_expires_at: dt.datetime | None
    remaining_days_replaced: int  # days still left today: the renewal restarts the package, it does not add to them
    renew_until: dt.datetime | None


class QueueAfter(BaseModel):
    """PG-09 prepaid renewal: the package that starts when the current one ends (no invented start date)."""

    mode: str = "queue"
    starts: str = "when_current_ends"  # by time or by volume, whichever comes first (the panel's rule)
    duration_days: int
    traffic_gb: int  # 0 = unlimited
    current_expires_at: dt.datetime | None
    remaining_days_kept: int  # days still left on the current package are used up first, not replaced
    earliest_end_estimate: dt.datetime | None = None


class RenewalModeOut(BaseModel):
    """One way to renew, with whether it can be used right now and why not (Core's words, shown as is)."""

    mode: str  # replace | queue
    available: bool
    code: str | None = None
    message: str | None = None
    replace_after: RenewalAfter | None = None
    queue_after: QueueAfter | None = None


class RenewalOut(BaseModel):
    renewable: bool
    code: str | None = None  # why not (ACCOUNT_NOT_RENEWABLE, RENEWAL_WINDOW_PASSED, RENEWAL_IN_PROGRESS, ...)
    message: str | None = None
    renew_until: dt.datetime | None = None
    package: CatalogItem | None = None  # the account's own package at its current price in the original bundle
    after: RenewalAfter | None = None
    modes: list[RenewalModeOut] = []  # PG-09: "replace" always; "queue" when the panel and the package allow a prepaid renewal


class QuoteOut(BaseModel):
    product_id: uuid.UUID
    unit_price: int
    discount: int
    total: int
    currency: str
    coupon_code: str | None
    renewal: RenewalAfter | None = None  # filled for a renewal quote (mode replace)
    renewal_queue: QueueAfter | None = None  # filled for a prepaid renewal quote (mode queue)


class StoreOut(BaseModel):
    id: uuid.UUID
    kind: str
    name: str
    slug: str
    currency: str
    branding: dict | None
    bot_username: str | None
    domain: str | None = None  # public hostname of the store website (used by the bots' account button)
    bot_messages: dict | None = None  # public bot texts (welcome / support / rules) a reseller store customises


class QuoteWalletOut(QuoteOut):
    wallet_balance: int
    sufficient_funds: bool
    balance_after: int | None = None  # wallet balance once this purchase is paid; None when funds are insufficient
    shortfall: int = 0  # exact top-up needed when funds are insufficient, otherwise 0
    payment: str = "wallet"  # v1.1: every purchase is wallet-funded


# Closed vocabularies of a coupon. Literals (not regex patterns) so the OpenAPI document - and therefore the generated
# admin/store clients - carry real unions instead of bare strings.
CouponStatus = Literal["active", "disabled", "archived"]
CouponScope = Literal["store", "domain"]
CouponFunding = Literal["store", "platform"]
CouponCreator = Literal["admin", "reseller"]


class CouponIn(BaseModel):
    code: str = Field(min_length=3, max_length=50, pattern=r"^[A-Za-z0-9_\-]+$")
    percent_bp: int = Field(default=0, ge=0, le=10_000)
    fixed: int = Field(default=0, ge=0, le=MAX_MONEY)
    max_discount: int | None = Field(default=None, gt=0, le=MAX_MONEY)
    min_amount: int = Field(default=0, ge=0, le=MAX_MONEY)
    product_ids: list[uuid.UUID] | None = None
    starts_at: dt.datetime | None = None
    ends_at: dt.datetime | None = None
    max_redemptions: int | None = Field(default=None, gt=0, le=MAX_COUNT)
    per_customer_limit: int | None = Field(default=1, gt=0, le=MAX_COUNT)
    status: CouponStatus = "active"


class AdminCouponIn(CouponIn):
    scope: CouponScope = "store"
    store_id: uuid.UUID | None = None
    allowed_store_ids: list[uuid.UUID] | None = None
    allowed_store_kinds: list[str] | None = None
    funded_by: CouponFunding = "platform"
    currency: str | None = None


class CouponOut(BaseModel):
    """What every coupon route (admin and store-scoped) returns; mirrors ``service.coupon_out``."""

    id: uuid.UUID
    code: str
    scope: CouponScope
    store_id: uuid.UUID | None
    allowed_store_ids: list[uuid.UUID] | None
    allowed_store_kinds: list[str] | None
    product_ids: list[uuid.UUID] | None
    creator_type: CouponCreator
    funded_by: CouponFunding
    percent_bp: int
    fixed: int
    max_discount: int | None
    min_amount: int
    currency: str | None
    starts_at: dt.datetime | None
    ends_at: dt.datetime | None
    max_redemptions: int | None
    per_customer_limit: int | None
    redemptions: int
    combinable: bool
    status: CouponStatus


class CouponPatch(BaseModel):
    status: CouponStatus | None = None
    ends_at: dt.datetime | None = None
    max_redemptions: int | None = Field(default=None, gt=0, le=MAX_COUNT)
    per_customer_limit: int | None = Field(default=None, gt=0, le=MAX_COUNT)
    max_discount: int | None = Field(default=None, gt=0, le=MAX_MONEY)


class CouponValidateIn(BaseModel):
    product_id: uuid.UUID
    code: str = Field(min_length=1, max_length=50)
