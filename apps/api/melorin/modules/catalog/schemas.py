import datetime as dt
import uuid

from pydantic import BaseModel, Field


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


class QuoteOut(BaseModel):
    product_id: uuid.UUID
    unit_price: int
    discount: int
    total: int
    currency: str
    coupon_code: str | None


class StoreOut(BaseModel):
    id: uuid.UUID
    kind: str
    name: str
    slug: str
    currency: str
    branding: dict | None
    bot_username: str | None


class QuoteWalletOut(QuoteOut):
    wallet_balance: int
    sufficient_funds: bool
    payment: str = "wallet"  # v1.1: every purchase is wallet-funded


class CouponIn(BaseModel):
    code: str = Field(min_length=3, max_length=50, pattern=r"^[A-Za-z0-9_\-]+$")
    percent_bp: int = Field(default=0, ge=0, le=10_000)
    fixed: int = Field(default=0, ge=0)
    max_discount: int | None = Field(default=None, gt=0)
    min_amount: int = Field(default=0, ge=0)
    product_ids: list[uuid.UUID] | None = None
    starts_at: dt.datetime | None = None
    ends_at: dt.datetime | None = None
    max_redemptions: int | None = Field(default=None, gt=0)
    per_customer_limit: int | None = Field(default=1, gt=0)
    status: str = Field(default="active", pattern="^(active|disabled|archived)$")


class AdminCouponIn(CouponIn):
    scope: str = Field(default="store", pattern="^(store|domain)$")
    store_id: uuid.UUID | None = None
    allowed_store_ids: list[uuid.UUID] | None = None
    allowed_store_kinds: list[str] | None = None
    funded_by: str = Field(default="platform", pattern="^(store|platform)$")
    currency: str | None = None


class CouponPatch(BaseModel):
    status: str | None = Field(default=None, pattern="^(active|disabled|archived)$")
    ends_at: dt.datetime | None = None
    max_redemptions: int | None = Field(default=None, gt=0)
    per_customer_limit: int | None = Field(default=None, gt=0)
    max_discount: int | None = Field(default=None, gt=0)


class CouponValidateIn(BaseModel):
    product_id: uuid.UUID
    code: str = Field(min_length=1, max_length=50)
