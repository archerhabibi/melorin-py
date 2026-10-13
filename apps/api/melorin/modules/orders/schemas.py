import datetime as dt
import uuid

from pydantic import BaseModel, Field


class CreateOrder(BaseModel):
    product_id: uuid.UUID
    payment_method: str = Field(default="wallet", pattern="^wallet$")  # v1.1: wallet-only checkout
    coupon_code: str | None = Field(default=None, max_length=50)
    kind: str = Field(default="purchase", pattern="^(purchase|renewal)$")
    vpn_account_id: uuid.UUID | None = None
    panel_group_id: uuid.UUID | None = None
    selected_panel_id: uuid.UUID | None = None
    account_name: str | None = Field(default=None, max_length=40)


class OrderOut(BaseModel):
    id: uuid.UUID
    number: str
    store_id: uuid.UUID
    user_id: uuid.UUID
    product_id: uuid.UUID
    kind: str
    status: str
    payment_method: str
    channel: str
    currency: str
    unit_price: int
    discount: int
    total: int
    coupon_code: str | None
    product_snapshot: dict
    vpn_account_id: uuid.UUID | None
    panel_group_id: uuid.UUID | None = None
    selected_panel_id: uuid.UUID | None = None
    requested_account_name: str | None = None
    needs_review: bool
    created_at: dt.datetime
    paid_at: dt.datetime | None
    completed_at: dt.datetime | None
    payment_id: uuid.UUID | None = None
    payment_instructions: dict | None = None


class AdminOrderOut(OrderOut):
    reseller_cost: int | None
    provisioning_attempts: int
    last_error: str | None
    pricing_snapshot: dict


class AdminOrderAction(BaseModel):
    reason: str | None = Field(default=None, max_length=500)


class AttachAccount(BaseModel):
    server_id: uuid.UUID
    username: str
    panel_ref: str | None = None
    subscription_url: str | None = None
    reason: str | None = None
