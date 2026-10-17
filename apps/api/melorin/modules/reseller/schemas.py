import datetime as dt
import uuid

from pydantic import BaseModel, Field, HttpUrl, model_validator


class ApplicationIn(BaseModel):
    """Reseller application. ``domain`` and ``bot_token`` are given together (web form: one-step) or both omitted
    (Telegram: request first, details are collected after the admin approves)."""

    store_name: str = Field(min_length=2, max_length=200)
    message: str | None = Field(default=None, max_length=2000)
    target_store_id: uuid.UUID | None = None
    domain: str | None = Field(
        default=None, min_length=4, max_length=255, description="store hostname, e.g. shop.example.com (scheme/path are stripped)"
    )
    bot_token: str | None = Field(
        default=None,
        min_length=20,
        max_length=100,
        repr=False,
        description="reseller Telegram bot token from BotFather; stored encrypted, never returned",
    )

    @model_validator(mode="after")
    def _both_or_neither(self):
        if (self.domain is None) != (self.bot_token is None):
            raise ValueError("domain and bot_token must be sent together")
        return self


class ApplicationDetailsIn(BaseModel):
    """Second step of an approved request: the store hostname and the reseller's bot token."""

    domain: str = Field(min_length=4, max_length=255)
    bot_token: str = Field(min_length=20, max_length=100, repr=False)


class StoreBrandingUpdate(BaseModel):
    branding: dict | None = None
    bot_messages: dict | None = None


class CustomerOut(BaseModel):
    user_id: uuid.UUID
    display_name: str | None
    email: str | None
    status: str
    joined_at: dt.datetime


class CustomerWalletAdjustment(BaseModel):
    """Reseller top-up/correction of its own customer's wallet in its own store (v1.1)."""

    amount: int = Field(description="positive = top-up (cash received by the reseller), negative = correction within balance")
    reason: str = Field(min_length=3, max_length=500)
    reference: str | None = Field(default=None, max_length=200, description="receipt / transfer reference")
    idempotency_key: str = Field(min_length=8, max_length=100)


class PaymentConfigIn(BaseModel):
    is_enabled: bool = True
    public_config: dict = Field(default_factory=dict, description="manual_card: card_number, holder, bank, min_amount, max_amount")
    secret: dict | None = Field(default=None, description="gateway secrets, e.g. {merchant_id}; write-only")


class PaymentReview(BaseModel):
    approve: bool
    note: str | None = Field(default=None, max_length=500)


class ApiCredentialIn(BaseModel):
    name: str = Field(min_length=2, max_length=100)
    scopes: list[str] = Field(default_factory=lambda: ["catalog:read", "customers:read", "orders:read"])
    rate_limit_per_minute: int = Field(default=120, ge=1, le=6000)
    ip_allowlist: list[str] | None = None
    activate: bool = True
    expires_at: dt.datetime | None = None


class WebhookEndpointIn(BaseModel):
    url: HttpUrl
    events: list[str] = Field(default_factory=list)
    description: str | None = Field(default=None, max_length=200)


class WebhookEndpointPatch(BaseModel):
    url: HttpUrl | None = None
    events: list[str] | None = None
    description: str | None = Field(default=None, max_length=200)
    status: str | None = Field(default=None, pattern="^(active|disabled)$")


class PriceIn(BaseModel):
    """Retail price of one product in the reseller's own store. Null or 0 removes the price (product hidden)."""

    customer_price: int | None = Field(default=None, ge=0)


class PriceBatchItem(BaseModel):
    """One price edit: ``bundle_id`` = the sales bundle the price is for, or null for the store-wide price of the package.
    ``customer_price`` null or 0 removes that price (a bundle then falls back to the store-wide price)."""

    bundle_id: uuid.UUID | None = None
    product_id: uuid.UUID
    customer_price: int | None = Field(default=None, ge=0, le=10**12)


class PriceBatchIn(BaseModel):
    items: list[PriceBatchItem] = Field(min_length=1, max_length=500)
